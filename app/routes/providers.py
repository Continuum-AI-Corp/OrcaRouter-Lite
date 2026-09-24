"""Provider keys CRUD — BYOK credentials for upstream LLM providers.

Single-tenant invariant: at most ONE active key per provider. Two
sources, both honored by the runtime router with DB taking precedence:

  1. DB rows in `provider_keys` (set via dashboard PUT, encrypted at rest).
  2. Environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)
     loaded by `Settings` and exposed via `settings.env_provider_keys()`.

The list endpoint surfaces BOTH so operators can see what's actually
configured. Without that, an operator who set keys in `.env` would see
an empty providers page in the dashboard, assume nothing is wired up,
and either re-set keys (creating a confusing duplicate) or worry that
their `auto` chats are silently failing — when in reality the env-sourced
key is serving traffic just fine.

Env-sourced rows carry `source: "env"`. Editing an env entry from the
dashboard writes a new DB row (which then takes precedence — matches
the runtime resolver in `router_cache.py:58`). Deleting the DB row
falls back to the env value transparently. Env entries themselves
aren't deletable from this API; the operator must edit `.env` and
restart to remove an env-set key (12-factor: env config lives in env).

Delete is a HARD delete, not a soft tombstone. Reasoning:
  - BYOK keys aren't user data; there's no audit/recovery story.
  - Soft-delete + new-PUT historically created ghost rows: query
    filtered `is_deleted=0`, missed the tombstone, INSERT'd a new
    row, leaving N tombstones piled up forever.
  - Hard delete keeps the table at most 1 row per provider, matching
    the single-tenant 1-key-per-provider invariant.

Migration note: existing dev DBs may carry tombstones from before this
change. The PUT path opportunistically wipes them when an operator
sets a new key for the same provider.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cache_invalidation_bus
from app.config import get_settings
from app.deps import get_db, get_key_context
from app.router_cache import usable_providers_from_db
from packages.auth.encryption import encrypt_credential
from packages.auth.types import KeyContext
from packages.db.models.provider_key import ProviderKey

router = APIRouter(prefix="/v1/providers", tags=["providers"])

# Dashboard sends this literal when the operator saves the provider form
# without retyping the secret (masked display value round-trips as "no change").
DASHBOARD_KEY_PLACEHOLDER = "[REDACTED]"


def _is_dashboard_key_placeholder(api_key: str) -> bool:
    return api_key == DASHBOARD_KEY_PLACEHOLDER


class SetProviderKey(BaseModel):
    api_key: str


class ProviderKeyOut(BaseModel):
    provider: str
    key_prefix: str
    is_enabled: bool
    # "db" = stored in provider_keys table (editable + deletable from dashboard)
    # "env" = loaded from .env / process env (read-only here; edit .env to change)
    source: str = "db"
    warnings: list[str] = []


def _dump_provider_key(out: ProviderKeyOut) -> dict:
    """Serialize a provider-key payload. Empty `warnings` are omitted so
    list responses and matching-prefix PUTs stay compatible with the
    pre-warning API (`warnings` only appears when there is one)."""
    payload = out.model_dump()
    if not payload["warnings"]:
        del payload["warnings"]
    return payload


def _mask_key(api_key: str) -> str:
    """Display-safe key prefix. Long keys show first 8 + last 4; short
    keys show 2 + 2 to give the operator some hint of which account
    they're looking at without exposing enough to be useful as a credential."""
    if len(api_key) > 12:
        return api_key[:8] + "..." + api_key[-4:]
    if len(api_key) > 4:
        return api_key[:2] + "..." + api_key[-2:]
    return "..."


# Soft prefix checks for known upstreams. Unknown providers are not guessed
# at — BYOK can be anything. A miss here is a WARNING on PUT, never a
# rejection: unusual-but-valid keys must still store. Together is omitted
# because live keys are not a stable prefix (historically hex, now mixed)
# and a false warning is noisier than silence there.
_KNOWN_KEY_PREFIXES: dict[str, tuple[str, ...]] = {
    "openai": ("sk-",),
    "anthropic": ("sk-ant-",),
    "groq": ("gsk_",),
    "xai": ("xai-",),
    "deepseek": ("sk-",),
    "fireworks": ("fw_",),
    "orcarouter": ("sk-orca-",),
}

_PROVIDER_DISPLAY = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "groq": "Groq",
    "xai": "xAI",
    "deepseek": "DeepSeek",
    "fireworks": "Fireworks",
    "orcarouter": "OrcaRouter",
}


def _google_key_matches(key: str) -> bool:
    """Google keys are either an AI Studio / Cloud API key (`AIza…`) or a
    service-account JSON blob (starts with `{`)."""
    return key.startswith("AIza") or key.startswith("{")


def provider_key_format_warning(provider: str, api_key: str) -> str | None:
    """Return a warning if `api_key` is obviously the wrong shape for a
    known provider. `None` means "looks fine" or "provider is unknown —
    don't guess". The caller still stores the key either way."""
    key = api_key.strip()
    if _is_dashboard_key_placeholder(key):
        return None
    slug = provider.strip().lower()
    if slug == "google":
        if _google_key_matches(key):
            return None
        expected = "'AIza...' or service-account JSON"
    else:
        prefixes = _KNOWN_KEY_PREFIXES.get(slug)
        if not prefixes:
            return None
        if any(key.startswith(p) for p in prefixes):
            return None
        expected = " or ".join(f"'{p}...'" for p in prefixes)

    # Never echo a short secret in full — 5 chars of a 5-char key is the
    # whole credential. Longer keys still get a tiny identifying prefix.
    shown = key[:5] if len(key) > 5 else "<too-short>"
    label = _PROVIDER_DISPLAY.get(slug, slug)
    return (
        f"Key prefix '{shown}' doesn't match known {label} format "
        f"(expected {expected}). Verify this is correct."
    )


@router.get("")
async def list_providers(
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(ProviderKey).where(ProviderKey.is_deleted == 0)
        )
    ).scalars().all()

    # The runtime resolver (`router_cache.build_deployments`) only honors
    # a DB row when it's BOTH `is_enabled` AND its `encrypted_key` decrypts.
    # `usable_providers_from_db` already encodes that contract — reuse it
    # here so the listing's notion of "DB row authoritative" stays in
    # lockstep with what actually serves traffic. Without this, a disabled
    # row or one with corrupt ciphertext (e.g. after a
    # CREDENTIAL_ENCRYPTION_KEY rotation) would suppress the env entry
    # in the dashboard while the runtime quietly falls back to env —
    # operators would see a "DB" source label but the env key is what's
    # actually authenticating their requests.
    usable_db = usable_providers_from_db(rows)

    out: list[dict] = []
    for r in rows:
        # Render every non-deleted DB row so operators still see disabled /
        # broken rows and can fix them. is_enabled flag tells the dashboard
        # to render appropriately; the env-suppression check below is the
        # part that depends on USABILITY, not just presence.
        out.append(
            _dump_provider_key(
                ProviderKeyOut(
                    provider=r.provider,
                    key_prefix=r.key_prefix,
                    is_enabled=r.is_enabled,
                    source="db",
                )
            )
        )

    # Surface env-configured keys the runtime is already using. DB takes
    # precedence ONLY when usable — matches the runtime resolver in
    # `router_cache.py:build_deployments` which silently skips disabled or
    # undecryptable rows and falls back to env. Suppressing env here based
    # on a non-usable DB row would lie to the operator about which
    # credential is actually authenticating their requests.
    for prov, raw_key in get_settings().env_provider_keys().items():
        if prov in usable_db:
            continue
        out.append(
            _dump_provider_key(
                ProviderKeyOut(
                    provider=prov,
                    key_prefix=_mask_key(raw_key),
                    is_enabled=True,
                    source="env",
                )
            )
        )

    return {"providers": out}


@router.put("/{provider}")
async def set_provider_key(
    provider: str,
    body: SetProviderKey,
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=422, detail="api_key cannot be empty")

    # Wipe any soft-deleted ghost rows for this provider before upsert.
    # Migration aid: pre-PR dev DBs might carry tombstones from old soft-delete
    # behavior. Without this cleanup, the upsert query below — which filters
    # `is_deleted=0` — would miss the ghost and INSERT a new row, leaving
    # the tombstone piled up. After this PR, DELETE is a hard delete so no
    # new tombstones can form, but old ones still need scrubbing.
    await db.execute(
        sql_delete(ProviderKey).where(
            ProviderKey.provider == provider,
            ProviderKey.is_deleted == 1,
        )
    )

    existing = (
        await db.execute(
            select(ProviderKey).where(
                ProviderKey.provider == provider,
                ProviderKey.is_deleted == 0,
            )
        )
    ).scalar_one_or_none()

    if _is_dashboard_key_placeholder(api_key):
        if existing is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "api_key cannot be the dashboard placeholder when no "
                    "stored key exists for this provider"
                ),
            )
        return _dump_provider_key(
            ProviderKeyOut(
                provider=existing.provider,
                key_prefix=existing.key_prefix,
                is_enabled=existing.is_enabled,
                source="db",
            )
        )

    encrypted = encrypt_credential(api_key)
    prefix_visible = _mask_key(api_key)

    if existing is not None:
        existing.encrypted_key = encrypted
        existing.key_prefix = prefix_visible
        existing.is_enabled = True
    else:
        existing = ProviderKey(
            provider=provider,
            encrypted_key=encrypted,
            key_prefix=prefix_visible,
        )
        db.add(existing)

    await db.commit()
    await cache_invalidation_bus.broadcast_router_cache_invalidation()

    # Soft format check: store anyway (BYOK), but tell the operator at
    # write time so an obvious typo doesn't surface later as a 401/cooldown.
    warning = provider_key_format_warning(provider, api_key)
    return _dump_provider_key(
        ProviderKeyOut(
            provider=existing.provider,
            key_prefix=existing.key_prefix,
            is_enabled=existing.is_enabled,
            source="db",
            warnings=[warning] if warning else [],
        )
    )


@router.delete("/{provider}", status_code=204)
async def delete_provider_key(
    provider: str,
    _kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Hard-delete the DB row for this provider. After this, runtime
    resolution falls back to the env value (if `.env` has one) or
    treats the provider as unconfigured.

    Returns 204 even if no DB row existed — the operator's intent
    ('no DB-managed key for this provider') is satisfied either way.
    Removing an env-only entry isn't supported here: edit `.env` and
    restart the server (env config is file-managed by design).
    """
    result = await db.execute(
        sql_delete(ProviderKey).where(ProviderKey.provider == provider)
    )
    await db.commit()
    if result.rowcount == 0:
        # No DB row, but the operator may have meant the env-sourced one.
        # Surface the situation explicitly instead of silently 204'ing —
        # otherwise a dashboard "Remove" click on an env row appears to
        # succeed yet the key remains active on next page load.
        if provider in get_settings().env_provider_keys():
            raise HTTPException(
                status_code=409,
                detail=(
                    f"'{provider}' is configured via environment variable "
                    f"({provider.upper()}_API_KEY). Remove it from your .env "
                    f"and restart the server to deconfigure."
                ),
            )
        raise HTTPException(status_code=404, detail="Provider key not found")
    await cache_invalidation_bus.broadcast_router_cache_invalidation()
    return Response(status_code=204)
