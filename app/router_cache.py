"""Router cache — single-workspace, single-router edition.

Replaces the SaaS edition's per-workspace LRU + Redis pub/sub invalidation with
a single cached `OrcaLiteLLMClient`. Rebuilt on demand when provider keys
change (callers invoke `invalidate_router()`).

`build_deployments()` is split out as pure-Python so it can be tested without
instantiating litellm.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from packages.auth.encryption import decrypt_credential
from packages.litellm_adapter.catalog import models_for_provider
from packages.litellm_adapter.hosted_catalog import HOSTED_MODELS
from packages.litellm_adapter.types import ProviderDeployment

if TYPE_CHECKING:
    from app.config import Settings
    from packages.db.models.provider_key import ProviderKey


HOSTED_PROVIDER_NAME = "orcarouter"


def build_deployments(
    *,
    env_keys: dict[str, str],
    db_keys: list["ProviderKey"],
    settings: "Settings",
) -> list[ProviderDeployment]:
    """Assemble the deployment list from env vars + DB rows + hosted upstream.

    Precedence:
      1. DB provider keys (UI-edited, authoritative; encrypted at rest)
      2. Env vars for providers not present in DB
      3. Hosted-as-upstream (one entry per catalog model) — DB key > env key
    """
    deployments: list[ProviderDeployment] = []
    db_provider_keys: dict[str, str] = {}

    for row in db_keys:
        if not row.is_enabled or row.is_deleted:
            continue
        try:
            db_provider_keys[row.provider] = decrypt_credential(row.encrypted_key)
        except Exception:
            continue

    # Step 1+2: provider keys (DB > env). The hosted "orcarouter" provider
    # has no rows in `models_for_provider`, so it's silently skipped here and
    # picked up in step 3.
    for provider, models in (
        (p, models_for_provider(p)) for p in {*db_provider_keys, *env_keys}
    ):
        api_key = db_provider_keys.get(provider) or env_keys.get(provider)
        if not api_key:
            continue
        for model in models:
            deployments.append(
                ProviderDeployment(
                    model_name=model.id,
                    litellm_model=f"{model.litellm_prefix}{model.id}",
                    api_key=api_key,
                    provider=provider,
                )
            )

    # Step 3: hosted-as-upstream. DB-stored "orcarouter" key (set via the
    # dashboard's Hosted fallback CTA) overrides the env key, mirroring step
    # 1+2 precedence. Either source enables every catalog model as a hosted
    # deployment so the long tail of providers never errors with "no key."
    hosted_key = db_provider_keys.get(HOSTED_PROVIDER_NAME) or settings.orcarouter_api_key
    if hosted_key:
        for provider, bare_id in HOSTED_MODELS:
            deployments.append(
                ProviderDeployment(
                    model_name=bare_id,
                    litellm_model=f"{provider}/{bare_id}",
                    api_key=hosted_key,
                    api_base=settings.orcarouter_base_url,
                    provider=HOSTED_PROVIDER_NAME,
                    custom_llm_provider="openai",
                    extra_headers={"X-OrcaRouter-beta-usd": "response"},
                )
            )

    return deployments


def hosted_key_source(
    *, env_key: str | None, db_keys: list["ProviderKey"]
) -> str | None:
    """Return where the hosted upstream key came from, or None if unconfigured.

    Mirrors the precedence used by `build_deployments`: a DB row beats env,
    BUT only if the row's encrypted_key actually decrypts. A row whose
    ciphertext is corrupt (post-rotation, DB tampering) is silently dropped
    by `build_deployments`, so reporting it as "configured" here would tell
    the dashboard "Active" while requests still 503 on hosted models.
    """
    if HOSTED_PROVIDER_NAME in usable_providers_from_db(db_keys):
        return "dashboard"
    if env_key:
        return "env"
    return None


def usable_providers_from_db(db_keys: list["ProviderKey"]) -> set[str]:
    """Set of provider names whose DB-stored key actually decrypts.

    Single source of truth for "is this provider deployable from a DB row?"
    Used by `hosted_key_source` and `/v1/analytics/unreachable` so the
    dashboard's "configured providers" view stays in lockstep with what
    `build_deployments` will actually wire up. Without this, an
    undecryptable row (after `CREDENTIAL_ENCRYPTION_KEY` rotation) would
    falsely suppress models from the unreachable list while the router
    can't reach them either.
    """
    out: set[str] = set()
    for row in db_keys:
        if not row.is_enabled or row.is_deleted:
            continue
        try:
            decrypt_credential(row.encrypted_key)
        except Exception:
            continue
        out.add(row.provider)
    return out


# ── Cached router instance ────────────────────────────────────────────────

_cached_client: object | None = None
_cache_lock = asyncio.Lock()


async def get_router(session) -> object:
    """Return the cached OrcaLiteLLMClient, building it on first call.

    Imports `OrcaLiteLLMClient` lazily so unit tests of `build_deployments`
    don't drag in litellm.
    """
    global _cached_client
    if _cached_client is not None:
        return _cached_client
    async with _cache_lock:
        if _cached_client is not None:
            return _cached_client

        from sqlalchemy import select

        from app.auto_routing import litellm_routing_strategy
        from app.config import get_settings
        from app.seed import DEFAULT_WORKSPACE_ID
        from packages.db.models.provider_key import ProviderKey
        from packages.db.models.routing_config import RoutingConfig
        from packages.litellm_adapter.client import OrcaLiteLLMClient

        settings = get_settings()
        rows = (
            await session.execute(
                select(ProviderKey).where(ProviderKey.is_deleted == 0)
            )
        ).scalars().all()
        deployments = build_deployments(
            env_keys=settings.env_provider_keys(),
            db_keys=list(rows),
            settings=settings,
        )

        routing_row = (
            await session.execute(
                select(RoutingConfig).where(
                    RoutingConfig.workspace_id == DEFAULT_WORKSPACE_ID,
                    RoutingConfig.is_deleted == 0,
                )
            )
        ).scalar_one_or_none()
        strategy = routing_row.strategy if routing_row else "balanced"
        preferred_models = (
            list(routing_row.preferred_models or []) if routing_row else []
        )

        _cached_client = OrcaLiteLLMClient(
            deployments=deployments,
            strategy=strategy,
            preferred_models=preferred_models,
            litellm_routing_strategy=litellm_routing_strategy(strategy),
            # Wire LiteLLM Router built-ins from settings so a deployment
            # that 404s once stays cooled down (no immediate re-pick), and
            # the cascade engine has policy for which errors fail fast.
            cooldown_time=float(settings.router_cooldown_seconds),
            allowed_fails=settings.router_allowed_fails,
            enable_pre_call_checks=settings.router_pre_call_checks,
            num_retries=settings.router_num_retries_default,
        )
        return _cached_client


def invalidate_router() -> None:
    """Drop the cached router so the next request rebuilds it."""
    global _cached_client
    _cached_client = None
