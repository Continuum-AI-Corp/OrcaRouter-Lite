"""The desktop settings that steer routing, as the engine reads them.

The app saves them in `workspace.settings_json["desktop"]` through
`PUT /v1/app/settings` (validated by `DesktopSettings` in
app/routes/desktop.py). Chat routing reads them on every request, so they're
cached for a couple of seconds, and `note_settings_changed()` (called by the
budget gate's hook of the same name, which the settings route calls) forgets
the cache so a change applies to the very next request.

The reader is lenient: a value that doesn't parse is treated as unset rather
than failing the request, because a broken setting must never stop an agent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_model_fallback import AGENT_KEY_PREFIX

CACHE_SECONDS = 2.0
HostedModels = Literal["free", "all"]


@dataclass(frozen=True)
class AgentModels:
    """D2: what an agent's requests are served by. None = what it asked for."""

    main: str | None = None
    background: str | None = None
    fallback_to_auto: bool = True


@dataclass(frozen=True)
class DesktopPrefs:
    hosted_models: HostedModels = "free"
    agent_models: dict[str, AgentModels] = field(default_factory=dict)
    agent_budgets: dict[str, int] = field(default_factory=dict)
    kept_substitutions: list[str] = field(default_factory=list)
    dismissed_offers: dict[str, str] = field(default_factory=dict)
    local_models: list[str] | None = None
    router_num_retries: int | None = None
    router_cooldown_seconds: int | None = None


DEFAULTS = DesktopPrefs()
_cache: dict[str, tuple[float, DesktopPrefs]] = {}


def note_settings_changed() -> None:
    _cache.clear()


def agent_of(key_name: str | None) -> str | None:
    """The agent id behind an `agent:<id>` key, or None for any other key."""
    if key_name and key_name.startswith(AGENT_KEY_PREFIX):
        return key_name[len(AGENT_KEY_PREFIX):] or None
    return None


async def load(db: AsyncSession | None, workspace_id: str) -> DesktopPrefs:
    """The workspace's routing preferences (defaults when none are saved)."""
    if db is None:
        return DEFAULTS
    hit = _cache.get(workspace_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from packages.db.models.workspace import Workspace

    raw = (
        await db.execute(select(Workspace.settings_json).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    parsed = parse(((raw or {}).get("desktop") or {}) if isinstance(raw, dict) else {})
    _cache[workspace_id] = (time.monotonic() + CACHE_SECONDS, parsed)
    return parsed


def parse(raw: dict) -> DesktopPrefs:
    """Saved settings → DesktopPrefs, dropping anything that doesn't parse."""
    return DesktopPrefs(
        hosted_models=raw.get("hosted_models") if raw.get("hosted_models") in ("free", "all") else "free",
        agent_models=_agent_models(raw.get("agent_models")),
        agent_budgets={
            k: v for k, v in _dict(raw.get("agent_budgets")).items()
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0
        },
        kept_substitutions=[s for s in _list(raw.get("kept_substitutions")) if isinstance(s, str)],
        dismissed_offers={k: v for k, v in _dict(raw.get("dismissed_offers")).items() if isinstance(v, str)},
        local_models=(
            [s for s in raw["local_models"] if isinstance(s, str)]
            if isinstance(raw.get("local_models"), list) else None
        ),
        router_num_retries=_int_in(raw.get("router_num_retries"), 0, 5),
        router_cooldown_seconds=_int_in(raw.get("router_cooldown_seconds"), 0, 3600),
    )


def _agent_models(raw) -> dict[str, AgentModels]:
    out: dict[str, AgentModels] = {}
    for agent, m in _dict(raw).items():
        if not isinstance(m, dict):
            continue
        out[agent] = AgentModels(
            main=m.get("main") if isinstance(m.get("main"), str) and m.get("main") else None,
            background=m.get("background") if isinstance(m.get("background"), str) and m.get("background") else None,
            fallback_to_auto=m.get("fallback_to_auto") is not False,
        )
    return out


def _dict(v) -> dict:
    return {k: x for k, x in v.items() if isinstance(k, str)} if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _int_in(v, lo: int, hi: int) -> int | None:
    if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi:
        return v
    return None
