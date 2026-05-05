"""API key management — list, create, revoke."""

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

router = APIRouter(prefix="/v1/keys", tags=["keys"])


class CreateKey(BaseModel):
    name: str


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
    return {
        "keys": [
            {
                "id": r.id,
                "name": r.name,
                "key_prefix": r.key_prefix,
                "is_active": r.is_active,
                "last_used_at": iso_utc(r.last_used_at),
                "revoked_at": iso_utc(r.revoked_at),
                "created_at": iso_utc(r.created_at),
            }
            for r in rows
        ]
    }


@router.post("", status_code=201)
async def create_key(
    body: CreateKey,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    full_key, key_hash, key_prefix = generate_api_key()
    row = ApiKey(
        workspace_id=kc.workspace_id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "api_key": full_key,  # plaintext shown ONCE
    }


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
