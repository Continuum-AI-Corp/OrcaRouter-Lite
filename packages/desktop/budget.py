"""Daily budget hard stop for coding agents (desktop mode).

With the desktop setting `budget_mode == "stop"`, a coding agent's generation
request is refused with 429 once today's spend reaches the daily budget.
"alert" (the default) only notifies. "Today" is the engine's local day: the
desktop engine runs on the user's own computer, in the user's timezone.

Only generation calls are gated (chat completions, Anthropic messages, Gemini
generateContent); listing models or counting tokens costs nothing. Spend is
cached for a couple of seconds so a burst of agent calls costs one query.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

CACHE_SECONDS = 2.0
_cache: dict[str, tuple[float, int, int | None, str]] = {}
_agent_cache: dict[str, tuple[float, int]] = {}


def reset_cache() -> None:
    _cache.clear()
    _agent_cache.clear()


def is_generation(path: str) -> bool:
    if path.startswith(("/v1/chat/completions", "/v1/responses")):
        return True
    if path.startswith("/v1/messages"):
        return not path.startswith("/v1/messages/count_tokens")
    if path.startswith("/v1beta/"):
        return ":generateContent" in path or ":streamGenerateContent" in path
    return False


def _local_midnight_utc(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(timezone.utc)).astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _money(microcents: int) -> str:
    cents = (max(0, microcents) + 5_000) // 10_000
    return f"${cents // 100:,}.{cents % 100:02d}"


async def _state(session: AsyncSession, workspace_id: str) -> tuple[int, int | None, str]:
    from packages.db.models.request_log import RequestLog
    from packages.db.models.workspace import Workspace

    hit = _cache.get(workspace_id)
    if hit and hit[0] > time.monotonic():
        return hit[1], hit[2], hit[3]
    ws = (await session.execute(select(Workspace.settings_json).where(Workspace.id == workspace_id))).scalar_one_or_none()
    desktop = (ws or {}).get("desktop") or {}
    limit = desktop.get("daily_budget_cents")
    mode = desktop.get("budget_mode") or "alert"
    spent = 0
    if limit is not None and mode == "stop":
        spent = int(
            (
                await session.execute(
                    select(func.coalesce(func.sum(RequestLog.cost_microcents), 0)).where(
                        RequestLog.workspace_id == workspace_id,
                        RequestLog.is_deleted == 0,
                        RequestLog.status_code < 400,
                        RequestLog.created_at >= _local_midnight_utc(),
                    )
                )
            ).scalar_one()
        )
    _cache[workspace_id] = (time.monotonic() + CACHE_SECONDS, spent, limit, mode)
    return spent, limit, mode


async def stop_reason(session: AsyncSession, workspace_id: str, *, key_name: str | None = None) -> str | None:
    """A user-facing reason to refuse an agent's request, or None to allow it.

    Two gates: the workspace's daily budget in "stop" mode pauses every
    agent; an agent's own daily cap (D3, `agent_budgets` in the desktop
    settings) pauses that agent only, whatever the budget mode.
    """
    spent, limit, mode = await _state(session, workspace_id)
    if mode == "stop" and limit is not None and spent >= limit * 10_000:
        return (
            f"Today's daily budget of {_money(limit * 10_000)} is used up ({_money(spent)} spent), "
            "so Orca paused your coding agents. Raise the budget in Orca, or switch it to alert-only."
        )
    return await _agent_stop_reason(session, workspace_id, key_name)


async def _agent_stop_reason(session: AsyncSession, workspace_id: str, key_name: str | None) -> str | None:
    from packages.desktop import prefs

    agent = prefs.agent_of(key_name)
    if agent is None:
        return None
    cap = (await prefs.load(session, workspace_id)).agent_budgets.get(agent)
    if cap is None:
        return None
    if await _agent_spent_today(session, workspace_id, key_name) < cap * 10_000:
        return None
    from packages.desktop.agents import AGENTS

    name = AGENTS[agent].name if agent in AGENTS else agent
    return f"Today's budget for {name} ({_money(cap * 10_000)}) is used up, so Orca paused it. Raise it in Orca."


async def _agent_spent_today(session: AsyncSession, workspace_id: str, key_name: str) -> int:
    """Today's spend through every key the agent has had (reconnecting mints
    a new one), cached like the workspace total."""
    from packages.db.models.api_key import ApiKey
    from packages.db.models.request_log import RequestLog

    cache_key = f"{workspace_id}\x00{key_name}"
    hit = _agent_cache.get(cache_key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    key_ids = select(ApiKey.id).where(ApiKey.workspace_id == workspace_id, ApiKey.name == key_name)
    spent = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(RequestLog.cost_microcents), 0)).where(
                    RequestLog.workspace_id == workspace_id,
                    RequestLog.api_key_id.in_(key_ids),
                    RequestLog.is_deleted == 0,
                    RequestLog.status_code < 400,
                    RequestLog.created_at >= _local_midnight_utc(),
                )
            )
        ).scalar_one()
    )
    _agent_cache[cache_key] = (time.monotonic() + CACHE_SECONDS, spent)
    return spent


def note_settings_changed() -> None:
    """Settings changed: forget cached limits and routing preferences so the
    change applies at once. (The router itself is rebuilt lazily when the
    preferences it was built with differ; see app/router_cache.py.)"""
    from packages.desktop import prefs

    reset_cache()
    prefs.note_settings_changed()
