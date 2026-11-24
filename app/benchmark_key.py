"""The Artificial Analysis key, saved from the desktop app (D7).

The quality and balanced strategies rank models by AA's benchmark scores,
which need an API key. Servers set ARTIFICIAL_ANALYSIS_API_KEY; the desktop
app has no .env, so it can save one with `PUT /v1/app/benchmark-key`. The
key is encrypted like provider keys and kept apart from them (in
`workspace.settings_json["benchmark"]`), so it never shows up as a model
provider. The environment variable wins when both are set.

The quality resolver reads it synchronously on every auto request, so the
stored key is decrypted once into memory: on first use with a database
session (`ensure_loaded`) and whenever it's saved.
"""

from __future__ import annotations

import base64

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.auth.encryption import decrypt_credential, encrypt_credential

SETTINGS_SECTION = "benchmark"
FIELD = "artificial_analysis_key"

_stored: str | None = None
_loaded = False


def reset() -> None:
    """Forget the in-memory copy (tests; it's re-read on next use)."""
    global _stored, _loaded
    _stored, _loaded = None, False


def _env_key() -> str:
    from app.config import get_settings

    return get_settings().artificial_analysis_api_key or ""


def effective_key() -> str:
    """The key the quality resolver should use ("" for none)."""
    return _env_key() or (_stored or "")


async def ensure_loaded(db: AsyncSession | None) -> None:
    if _loaded or db is None:
        return
    await load(db)


async def load(db: AsyncSession, workspace_id: str = "default") -> str | None:
    global _stored, _loaded
    from packages.db.models.workspace import Workspace

    raw = (
        await db.execute(select(Workspace.settings_json).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    sealed = ((raw or {}).get(SETTINGS_SECTION) or {}).get(FIELD) if isinstance(raw, dict) else None
    try:
        _stored = decrypt_credential(base64.b64decode(sealed)) if sealed else None
    except Exception:
        # Sealed with an encryption key that's since been rotated: treat
        # as unset, the user can save it again.
        _stored = None
    _loaded = True
    return _stored


async def save(db: AsyncSession, api_key: str | None, workspace_id: str = "default") -> None:
    global _stored, _loaded
    from packages.db.models.workspace import Workspace

    ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one()
    await db.refresh(ws, ["settings_json"])
    merged = dict(ws.settings_json or {})
    section = dict(merged.get(SETTINGS_SECTION) or {})
    if api_key:
        section[FIELD] = base64.b64encode(encrypt_credential(api_key)).decode("ascii")
    else:
        section.pop(FIELD, None)
    merged[SETTINGS_SECTION] = section
    ws.settings_json = merged  # reassign so SQLAlchemy sees the JSON change
    await db.commit()
    _stored, _loaded = (api_key or None), True
    from app.quality_scores import invalidate_metrics_cache

    invalidate_metrics_cache(None)


def hint(key: str) -> str:
    """Enough of a key to recognise it, never enough to use it."""
    return f"{key[:3]}…{key[-3:]}" if len(key) > 8 else "…"


def status() -> dict:
    env = _env_key()
    if env:
        return {"configured": True, "source": "env", "hint": hint(env)}
    if _stored:
        return {"configured": True, "source": "app", "hint": hint(_stored)}
    return {"configured": False, "source": None, "hint": None}
