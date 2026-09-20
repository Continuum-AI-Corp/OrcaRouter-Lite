"""API key management — list, create, update allowlist, revoke."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
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
    row = (
        await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.is_deleted == 0)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found")

    # A restricted key (non-None allowlist) may update its own allowlist
    # to a non-null list, including [] (deny-everything). JSON null would
    # store None = unrestricted and let the key holder drop the operator
    # constraint, so that (and any other key) requires an unrestricted
    # operator key.
    if kc.model_allowlist is not None and (
        kc.key_id != row.id or body.model_allowlist is None
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Restricted API keys cannot clear their own model_allowlist."
                if kc.key_id == row.id
                else "Restricted API keys can only update their own model_allowlist."
            ),
        )

    row.model_allowlist = _validate_model_allowlist(body.model_allowlist)
    await db.commit()
    await db.refresh(row)
    return _key_public(row)


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: str,
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.is_deleted == 0)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found")

    row.is_active = False
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=204)
