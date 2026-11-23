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


def reset_cache() -> None:
    _cache.clear()


def is_generation(path: str) -> bool:
    if path.startswith("/v1/chat/completions"):
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


async def stop_reason(session: AsyncSession, workspace_id: str) -> str | None:
    """A user-facing reason to refuse an agent's request, or None to allow it."""
    spent, limit, mode = await _state(session, workspace_id)
    if mode != "stop" or limit is None:
        return None
    if spent < limit * 10_000:
        return None
    return (
        f"Today's daily budget of {_money(limit * 10_000)} is used up ({_money(spent)} spent), "
        "so Orca paused your coding agents. Raise the budget in Orca, or switch it to alert-only."
    )


def note_settings_changed() -> None:
    """Settings changed: forget cached limits so the change applies at once."""
    reset_cache()
