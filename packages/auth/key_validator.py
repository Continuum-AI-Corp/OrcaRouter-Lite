"""API key validation — single-workspace edition.

Always returns workspace_id="default". Drops the role/admin/session-token
branches that the SaaS edition needs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.auth.hashing import api_key_lookup_hashes
from packages.auth.types import KeyContext
from packages.db.models.api_key import ApiKey


class AuthError(Exception):
    """Raised when key validation fails. Maps to HTTP 401."""

    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def validate_api_key(raw_key: str, session: AsyncSession) -> KeyContext:
    """Look up an sk-orca-* key. Raise AuthError on miss / revoked / inactive."""
    if not raw_key.startswith("sk-orca-"):
        raise AuthError("Invalid API key format")

    legacy_hash, peppered_hash = api_key_lookup_hashes(raw_key)
    candidates = {legacy_hash, peppered_hash}

    stmt = select(ApiKey).where(
        ApiKey.key_hash.in_(candidates),
        ApiKey.is_deleted == 0,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()

    if row is None:
        raise AuthError("Invalid API key")
    if not row.is_active or row.revoked_at is not None:
        raise AuthError("API key revoked")

    # Best-effort last-used update; doesn't fail the request if it errors.
    try:
        row.last_used_at = datetime.now(timezone.utc)
        await session.flush()
        await session.commit()
    except Exception:
        pass

    return KeyContext(
        key_id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        key_type="standard",
        budget_limit_cents=row.budget_limit_cents,
        model_allowlist=row.model_allowlist,
    )
