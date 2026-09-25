"""API key management — list, create, update allowlist, revoke."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app._time_util import iso_utc
from app.deps import get_db, get_key_context
from packages.auth.hashing import generate_api_key
from packages.auth.types import KeyContext
from packages.db.models.api_key import ApiKey
from packages.litellm_adapter.catalog import CATALOG_BY_ID

router = APIRouter(prefix="/v1/keys", tags=["keys"])


class CreateKey(BaseModel):
    name: str
    # None (omitted) = unrestricted. [] = deny everything. See UpdateKey.
    model_allowlist: list[str] | None = None


class UpdateKey(BaseModel):
    # Required so JSON null (clear → unrestricted) is distinct from [].
    # `is not None` semantics: [] is a deny-everything lock, not "no restriction".
    model_allowlist: list[str] | None


def _validate_model_allowlist(ids: list[str] | None) -> list[str] | None:
    """Reject unknown catalog ids at write time.

    None stays None (unrestricted). An explicit empty list is valid — it is
    the operator's deny-everything signal, and must not be coerced to None.
    """
    if ids is None:
        return None
    unknown = sorted({m for m in ids if m not in CATALOG_BY_ID})
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown model id(s): {unknown}. "
                "Allowlist entries must match the catalog."
            ),
        )
    return ids


def _key_public(r: ApiKey) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "key_prefix": r.key_prefix,
        "is_active": r.is_active,
        "model_allowlist": r.model_allowlist,
        "last_used_at": iso_utc(r.last_used_at),
        "revoked_at": iso_utc(r.revoked_at),
        "created_at": iso_utc(r.created_at),
    }


async def _begin_sqlite_immediate(db: AsyncSession) -> None:
    """Take SQLite's reserved lock before the authz read.

    Postgres row locks (``FOR UPDATE``) already pin the caller until commit.
    SQLite drops ``FOR UPDATE``, and WAL lets another connection commit a
    restrict after this session has read the caller. ``BEGIN IMMEDIATE``
    grabs the write lock first, so that restrict either lands before the
    read or waits until this transaction commits.
    """
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return
    await db.execute(text("BEGIN IMMEDIATE"))


async def _lock_key(db: AsyncSession, key_id: str) -> ApiKey | None:
    """Re-read a key and take a write lock (SELECT FOR UPDATE).

    Auth-time ``kc.model_allowlist`` is a snapshot from ``validate_api_key``.
    An operator may restrict the caller between authenticate and commit, so
    every write re-loads the caller (and the target, when different) under
    ``FOR UPDATE`` and re-runs the restriction check against that fresh
    value. On SQLite the caller lock is paired with ``BEGIN IMMEDIATE``
    (see ``_lock_caller``) because ``FOR UPDATE`` is a no-op there.
    """
    return (
        await db.execute(
            select(ApiKey)
            .where(ApiKey.id == key_id, ApiKey.is_deleted == 0)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def _lock_caller(db: AsyncSession, key_id: str) -> ApiKey:
    await _begin_sqlite_immediate(db)
    caller = await _lock_key(db, key_id)
    if caller is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return caller


def _require_create_within_allowlist(
    caller_allowlist: list[str] | None,
    new_allowlist: list[str] | None,
) -> None:
    """Restricted callers may only mint a non-null subset of their own list."""
    if caller_allowlist is None:
        return
    if new_allowlist is None:
        raise HTTPException(
            status_code=403,
            detail="Restricted API keys cannot create unrestricted keys.",
        )
    if not set(new_allowlist) <= set(caller_allowlist):
        raise HTTPException(
            status_code=403,
            detail=(
                "Restricted API keys can only create keys whose "
                "model_allowlist is a subset of their own."
            ),
        )


def _require_update_within_allowlist(
    caller_allowlist: list[str] | None,
    caller_id: str,
    target_id: str,
    new_allowlist: list[str] | None,
) -> None:
    """Unrestricted operator may set any value, including None.

    A restricted caller may only update its own row, and only to a
    non-null list that is a subset of its current allowlist.
    """
    if caller_allowlist is None:
        return
    if caller_id != target_id:
        raise HTTPException(
            status_code=403,
            detail="Restricted API keys can only update their own model_allowlist.",
        )
    if new_allowlist is None:
        raise HTTPException(
            status_code=403,
            detail="Restricted API keys cannot clear their own model_allowlist.",
        )
    if not set(new_allowlist) <= set(caller_allowlist):
        raise HTTPException(
            status_code=403,
            detail="Restricted API keys can only narrow their own model_allowlist.",
        )


def _require_revoke_allowed(
    caller_allowlist: list[str] | None,
    caller_id: str,
    target_id: str,
) -> None:
    """A restricted key may revoke itself, never a sibling or operator key."""
    if caller_allowlist is not None and caller_id != target_id:
        raise HTTPException(
            status_code=403,
            detail="Restricted API keys can only revoke themselves.",
        )


@router.get("")
async def list_keys(
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(ApiKey).where(ApiKey.is_deleted == 0).order_by(ApiKey.created_at)
        )
    ).scalars().all()
    return {"keys": [_key_public(r) for r in rows]}


@router.post("", status_code=201)
async def create_key(
    body: CreateKey,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    caller = await _lock_caller(db, kc.key_id)
    _require_create_within_allowlist(caller.model_allowlist, body.model_allowlist)

    allowlist = _validate_model_allowlist(body.model_allowlist)
    full_key, key_hash, key_prefix = generate_api_key()
    row = ApiKey(
        workspace_id=kc.workspace_id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        model_allowlist=allowlist,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return {
        **_key_public(row),
        "api_key": full_key,  # plaintext shown ONCE
    }


@router.put("/{key_id}")
async def update_key(
    key_id: str,
    body: UpdateKey,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Lock the caller first so a concurrent restrict is visible (and held)
    # before we decide whether this write is still authorized.
    caller = await _lock_caller(db, kc.key_id)
    if key_id == caller.id:
        row = caller
    else:
        row = await _lock_key(db, key_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Key not found")

    _require_update_within_allowlist(
        caller.model_allowlist, caller.id, row.id, body.model_allowlist
    )

    row.model_allowlist = _validate_model_allowlist(body.model_allowlist)
    await db.commit()
    await db.refresh(row)
    return _key_public(row)


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    caller = await _lock_caller(db, kc.key_id)
    if key_id == caller.id:
        row = caller
    else:
        row = await _lock_key(db, key_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Key not found")

    _require_revoke_allowed(caller.model_allowlist, caller.id, row.id)

    row.is_active = False
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=204)
