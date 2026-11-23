"""/v1/app — local API for the Orca desktop app and the `orca` CLI.

Mounted only in desktop mode (see `Settings.orca_desktop_mode`). Every route
needs an unrestricted key that is not itself an agent key: an agent must not
be able to rewire other agents or read the user's spend.

Agents are attributed by key. Connecting an agent mints a dedicated key named
`agent:<id>` and writes it into the agent's config, so spend per agent is a
plain group-by on `requests_log.api_key_id`.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_key_context
from packages.auth.hashing import generate_api_key
from packages.auth.types import KeyContext
from packages.db.models.api_key import ApiKey
from packages.db.models.provider_key import ProviderKey
from packages.db.models.request_log import RequestLog
from packages.db.models.workspace import Workspace
from packages.desktop import agents as ag

router = APIRouter(prefix="/v1/app", tags=["desktop"])

AGENT_KEY_PREFIX = "agent:"
BASELINE_MODEL = "gpt-4o"
WARN_AT_PERCENT = 80.0
HEALTH_WINDOW = timedelta(hours=1)


@dataclass
class DesktopContext:
    home: Path
    state_dir: Path
    base_url: str
    which: Callable[[str], str | None] = shutil.which


def default_orca_home() -> Path:
    from app.config import get_settings

    configured = get_settings().orca_home
    return Path(configured).expanduser() if configured else Path.home() / ".orcarouter-lite"


def get_desktop_context() -> DesktopContext:
    from app.config import get_settings

    s = get_settings()
    base = s.orca_public_base_url or f"http://127.0.0.1:{s.port}"
    state = default_orca_home() / "agents"
    state.mkdir(parents=True, exist_ok=True)
    os.chmod(state, 0o700)
    return DesktopContext(home=Path.home(), state_dir=state, base_url=base.rstrip("/"))


def require_app_caller(kc: KeyContext = Depends(get_key_context)) -> KeyContext:
    if kc.name.startswith(AGENT_KEY_PREFIX):
        raise HTTPException(status_code=403, detail="Agent keys can't manage the desktop app.")
    if kc.model_allowlist is not None or kc.budget_limit_cents is not None:
        raise HTTPException(status_code=403, detail="Restricted keys can't manage the desktop app.")
    return kc


# ── agents ──────────────────────────────────────────────────────────────


def _agent_list(ctx: DesktopContext) -> list[dict]:
    return [asdict(a) for a in ag.detect_agents(home=ctx.home, state_dir=ctx.state_dir, which=ctx.which)]


def _agent_out(ctx: DesktopContext, agent_id: str) -> dict:
    return next(a for a in _agent_list(ctx) if a["id"] == agent_id)


async def _revoke_agent_keys(db: AsyncSession, workspace_id: str, agent_id: str) -> None:
    await db.execute(
        update(ApiKey)
        .where(
            ApiKey.workspace_id == workspace_id,
            ApiKey.name == f"{AGENT_KEY_PREFIX}{agent_id}",
            # Not `is_active`: SQLite stores its server default as the text
            # 'true', which never equals TRUE. Every revoke sets revoked_at.
            ApiKey.revoked_at.is_(None),
        )
        .values(is_active=False, revoked_at=datetime.now(timezone.utc))
    )


@router.get("/agents")
async def list_agents(
    _kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
) -> dict:
    return {"agents": _agent_list(ctx), "base_url": ctx.base_url}


@router.post("/agents/{agent_id}/connect")
async def connect_agent(
    agent_id: str,
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    spec = ag.AGENTS.get(agent_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    if spec.setup == "unsupported":
        raise HTTPException(status_code=409, detail=spec.note)

    full_key, key_hash, key_prefix = generate_api_key()
    try:
        result = ag.connect_agent(
            agent_id, home=ctx.home, state_dir=ctx.state_dir, base_url=ctx.base_url, api_key=full_key
        )
    except ag.AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # The config now holds the new key; retire the old one and store the new.
    await _revoke_agent_keys(db, kc.workspace_id, agent_id)
    db.add(
        ApiKey(
            workspace_id=kc.workspace_id,
            name=f"{AGENT_KEY_PREFIX}{agent_id}",
            key_hash=key_hash,
            key_prefix=key_prefix,
        )
    )
    await db.commit()

    out = _agent_out(ctx, agent_id)
    out["manual"] = result.manual
    if result.manual:
        # Shown once so the user can paste it into the agent's own settings.
        out["base_url"] = result.base_url
        out["api_key"] = result.api_key
    return out


@router.post("/agents/{agent_id}/disconnect")
async def disconnect_agent(
    agent_id: str,
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if agent_id not in ag.AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    try:
        ag.disconnect_agent(agent_id, home=ctx.home, state_dir=ctx.state_dir)
    except ag.AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _revoke_agent_keys(db, kc.workspace_id, agent_id)
    await db.commit()
    return _agent_out(ctx, agent_id)


# ── settings ────────────────────────────────────────────────────────────


class DesktopSettings(BaseModel):
    daily_budget_cents: int | None = Field(default=None, ge=0)


async def _workspace(db: AsyncSession, workspace_id: str) -> Workspace:
    ws = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _desktop_settings(ws: Workspace) -> DesktopSettings:
    raw = (ws.settings_json or {}).get("desktop") or {}
    return DesktopSettings(**{k: v for k, v in raw.items() if k in DesktopSettings.model_fields})


@router.get("/settings")
async def get_settings_route(
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return _desktop_settings(await _workspace(db, kc.workspace_id)).model_dump()


@router.put("/settings")
async def put_settings_route(
    body: DesktopSettings,
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    ws = await _workspace(db, kc.workspace_id)
    merged = dict(ws.settings_json or {})
    merged["desktop"] = body.model_dump()
    ws.settings_json = merged  # reassign so SQLAlchemy sees the JSON change
    await db.commit()
    return body.model_dump()


# ── summary ─────────────────────────────────────────────────────────────


def _local_midnight_utc(now: datetime, tz_offset_minutes: int) -> datetime:
    local = now + timedelta(minutes=tz_offset_minutes)
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=tz_offset_minutes)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _budget(daily_cents: int | None, spent_today_microcents: int) -> dict:
    if daily_cents is None:
        return {"daily_cents": None, "used_percent": None, "state": "none"}
    if daily_cents == 0:
        pct = 100.0 if spent_today_microcents > 0 else 0.0
    else:
        pct = round(100 * spent_today_microcents / (daily_cents * 10_000), 1)
    state = "over" if pct >= 100 else "warn" if pct >= WARN_AT_PERCENT else "ok"
    return {"daily_cents": daily_cents, "used_percent": pct, "state": state}


def _baseline_microcents(rows, model) -> int:
    return sum(
        int(
            (r.input_tokens or 0) * model.input_cost_per_token * 1_000_000
            + (r.output_tokens or 0) * model.output_cost_per_token * 1_000_000
        )
        for r in rows
    )


async def _providers(db: AsyncSession, workspace_id: str, recent: list) -> list[dict]:
    from app.config import get_settings
    from app.router_cache import HOSTED_PROVIDER_NAME, usable_providers_from_db

    db_rows = (
        await db.execute(select(ProviderKey).where(ProviderKey.is_deleted == 0))
    ).scalars().all()
    configured: dict[str, str] = {}
    for p in usable_providers_from_db(list(db_rows)):
        configured[p] = "db"
    for p in get_settings().env_provider_keys():
        configured.setdefault(p, "env")
    if get_settings().orcarouter_api_key:
        configured.setdefault(HOSTED_PROVIDER_NAME, "env")

    seen = {r.provider for r in recent}
    out = []
    for provider in sorted(set(configured) | seen):
        rows = [r for r in recent if r.provider == provider]
        if not rows:
            state = "idle"
        else:
            failed = sum(1 for r in rows if r.status_code >= 400)
            state = "degraded" if failed * 2 >= len(rows) else "healthy"
        out.append({"provider": provider, "source": configured.get(provider, "unknown"), "state": state})
    return out


@router.get("/summary")
async def summary(
    tz_offset_minutes: int = Query(0, ge=-14 * 60, le=14 * 60),
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    today_start = _local_midnight_utc(now, tz_offset_minutes)
    window_start = min(week_start, today_start)

    rows = (
        await db.execute(
            select(RequestLog).where(
                RequestLog.workspace_id == kc.workspace_id,
                RequestLog.is_deleted == 0,
                RequestLog.created_at >= window_start,
            )
        )
    ).scalars().all()
    for r in rows:
        r.created_at = _aware(r.created_at)

    ok = [r for r in rows if r.status_code < 400]
    week = [r for r in ok if r.created_at >= week_start]
    today = [r for r in ok if r.created_at >= today_start]

    keys = (
        await db.execute(select(ApiKey.id, ApiKey.name).where(ApiKey.workspace_id == kc.workspace_id))
    ).all()
    agent_of = {kid: name[len(AGENT_KEY_PREFIX):] for kid, name in keys if name.startswith(AGENT_KEY_PREFIX)}

    buckets: dict[str, dict] = {}

    def _bucket(agent_id: str) -> dict:
        if agent_id not in buckets:
            spec = ag.AGENTS.get(agent_id)
            buckets[agent_id] = {
                "id": agent_id,
                "name": spec.name if spec else "Other apps",
                "today_microcents": 0,
                "week_microcents": 0,
                "requests_week": 0,
            }
        return buckets[agent_id]

    for r in week:
        b = _bucket(agent_of.get(r.api_key_id, "other"))
        b["week_microcents"] += int(r.cost_microcents or 0)
        b["requests_week"] += 1
    for r in today:
        _bucket(agent_of.get(r.api_key_id, "other"))["today_microcents"] += int(r.cost_microcents or 0)

    spend_today = sum(int(r.cost_microcents or 0) for r in today)
    spend_week = sum(int(r.cost_microcents or 0) for r in week)
    baseline = CATALOG_BY_ID.get(BASELINE_MODEL)
    saved = max(0, _baseline_microcents(week, baseline) - spend_week) if baseline else 0

    settings = _desktop_settings(await _workspace(db, kc.workspace_id))
    recent = [r for r in rows if r.created_at >= now - HEALTH_WINDOW]

    from app.config import get_settings
    from app.router_cache import HOSTED_PROVIDER_NAME

    hosted_db = (
        await db.execute(
            select(ProviderKey.id).where(
                ProviderKey.provider == HOSTED_PROVIDER_NAME, ProviderKey.is_deleted == 0
            )
        )
    ).first()

    return {
        "currency": "USD",
        "generated_at": now.isoformat(),
        "today": {"spend_microcents": spend_today, "requests": len(today)},
        "week": {
            "spend_microcents": spend_week,
            "requests": len(week),
            "saved_microcents": saved,
            "baseline_model": BASELINE_MODEL,
            "failures_avoided": sum(1 for r in week if (r.fallback_level or 0) > 0),
        },
        "budget": _budget(settings.daily_budget_cents, spend_today),
        "agents": sorted(buckets.values(), key=lambda b: (b["id"] == "other", -b["week_microcents"])),
        "providers": await _providers(db, kc.workspace_id, recent),
        "hosted": {"configured": bool(get_settings().orcarouter_api_key or hosted_db)},
    }
