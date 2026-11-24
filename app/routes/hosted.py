"""Hosted-gateway status endpoint.

Powers the dashboard's OrcaRouter card: tells the SPA whether hosted
upstream is configured (env or DB), where the configuration came from,
the token-console URL where users copy their sk-orca-* key, the
signup URL for users without an account yet, and the console and billing
pages where spend and credit are managed. Every link carries
`ref=lite-setup` (H8) and nothing about the user. OrcaRouter is a hosted
gateway: one key for every model, failover between providers, free
models to start and pay per request for paid models.
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
from packages.desktop.links import SETUP, with_ref

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
        "signup_url": with_ref(settings.orcarouter_signup_url, SETUP),
        "token_url": with_ref(settings.orcarouter_token_url, SETUP),
        "console_url": with_ref(settings.orcarouter_console_url, SETUP),
        "billing_url": with_ref(settings.orcarouter_billing_url, SETUP),
        "provider_name": HOSTED_PROVIDER_NAME,
    }
