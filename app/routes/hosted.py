"""Hosted-fallback status endpoint.

Powers the dashboard's "Hosted fallback" card: tells the SPA whether
hosted upstream is configured (env or DB), where the configuration came
from, the token-console URL where users copy their sk-orca-* key, and
the signup URL for users without an account yet (free $5 trial credit).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import get_db, get_key_context
from app.router_cache import HOSTED_PROVIDER_NAME, hosted_key_source
from packages.auth.types import KeyContext
from packages.db.models.provider_key import ProviderKey

router = APIRouter(prefix="/v1/hosted", tags=["hosted"])


@router.get("")
async def hosted_status(
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()
    rows = (
        await db.execute(
            select(ProviderKey).where(
                ProviderKey.provider == HOSTED_PROVIDER_NAME,
                ProviderKey.is_deleted == 0,
            )
        )
    ).scalars().all()

    source = hosted_key_source(
        env_key=settings.orcarouter_api_key,
        db_keys=list(rows),
    )

    return {
        "configured": source is not None,
        "source": source,
        "base_url": settings.orcarouter_base_url,
        "signup_url": settings.orcarouter_signup_url,
        "token_url": settings.orcarouter_token_url,
        "provider_name": HOSTED_PROVIDER_NAME,
    }
