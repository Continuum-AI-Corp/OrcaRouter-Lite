"""/v1/app — local API for the Orca desktop app and the `orca` CLI.

Mounted only in desktop mode (see `Settings.orca_desktop_mode`). Every route
needs an unrestricted key that is not itself an agent key: an agent must not
be able to rewire other agents or read the user's spend.

Agents are attributed by key. Connecting an agent mints a dedicated key named
`agent:<id>` and writes it into the agent's config, so spend per agent is a
plain group-by on `requests_log.api_key_id`.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

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
from packages.desktop import updates

router = APIRouter(prefix="/v1/app", tags=["desktop"])
# Unauthenticated on purpose: it proves which process owns the port before
# any client sends it a key. See Settings.orca_instance_secret.
identity_router = APIRouter(tags=["desktop"])

AGENT_KEY_PREFIX = "agent:"
APP_KEY_NAME = "desktop-app"
_agent_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
BASELINE_MODEL = "gpt-4o"
WARN_AT_PERCENT = 80.0
HEALTH_WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class _Row:
    api_key_id: str
    provider: str
    status_code: int
    cost_microcents: int
    input_tokens: int
    output_tokens: int
    fallback_level: int
    created_at: datetime


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
    """Only the desktop app's own key (~/.orcarouter-lite/app.key) may use /v1/app."""
    if kc.name != APP_KEY_NAME or kc.model_allowlist is not None or kc.budget_limit_cents is not None:
        raise HTTPException(status_code=403, detail="Only the desktop app's key can manage the desktop app.")
    return kc


@identity_router.get("/health/identity")
async def identity(challenge: str = Query(..., min_length=16, max_length=128)) -> dict:
    from app.config import get_settings

    secret = get_settings().orca_instance_secret
    if not secret:
        raise HTTPException(status_code=404, detail="Not Found")
    proof = hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()
    return {"proof": proof}


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
    async with _agent_locks[agent_id]:
        # Stage the key change in the transaction first, then write the
        # agent's config, then commit. If the commit fails, the config is put
        # back, so a config never points at a key the database doesn't have.
        await _revoke_agent_keys(db, kc.workspace_id, agent_id)
        db.add(
            ApiKey(
                workspace_id=kc.workspace_id,
                name=f"{AGENT_KEY_PREFIX}{agent_id}",
                key_hash=key_hash,
                key_prefix=key_prefix,
            )
        )
        await db.flush()
        try:
            result = ag.connect_agent(
                agent_id, home=ctx.home, state_dir=ctx.state_dir, base_url=ctx.base_url, api_key=full_key
            )
        except (ag.AgentConfigError, OSError) as exc:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            await db.commit()
        except Exception as exc:
            await db.rollback()
            try:
                ag.disconnect_agent(agent_id, home=ctx.home, state_dir=ctx.state_dir)
            except ag.AgentConfigError:
                pass
            raise HTTPException(
                status_code=503,
                detail=f"Couldn't save the new key, so {spec.name}'s original settings were restored. Try again.",
            ) from exc

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
    async with _agent_locks[agent_id]:
        await _revoke_agent_keys(db, kc.workspace_id, agent_id)
        await db.flush()
        try:
            ag.disconnect_agent(agent_id, home=ctx.home, state_dir=ctx.state_dir)
        except (ag.AgentConfigError, OSError) as exc:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await db.commit()
    return _agent_out(ctx, agent_id)


# ── team gateway ────────────────────────────────────────────────────────


class GatewayJoin(BaseModel):
    url: str = Field(min_length=1, max_length=512)
    key: str = Field(min_length=1, max_length=512)


@router.post("/gateway")
async def join_gateway(
    body: GatewayJoin,
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Point this computer's agents at a team's gateway with the key the team issued."""
    from starlette.concurrency import run_in_threadpool

    from packages.desktop import gateway as gw

    try:
        url = gw.normalize_url(body.url)
        await run_in_threadpool(gw.verify, url, body.key)
    except gw.GatewayError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    connected = []
    for status in ag.detect_agents(home=ctx.home, state_dir=ctx.state_dir, which=ctx.which):
        if not status.installed or status.setup != "auto":
            continue
        async with _agent_locks[status.id]:
            try:
                ag.connect_agent(status.id, home=ctx.home, state_dir=ctx.state_dir, base_url=url, api_key=body.key)
            except (ag.AgentConfigError, OSError) as exc:
                raise HTTPException(status_code=422, detail=f"{status.name}: {exc}") from exc
            # The agent now uses the team's key; retire its local one.
            await _revoke_agent_keys(db, kc.workspace_id, status.id)
            connected.append(status.id)
    await db.commit()
    gw.save(ctx.state_dir.parent, url)
    return {"gateway": {"url": url}, "connected": connected, "agents": _agent_list(ctx)}


@router.delete("/gateway")
async def leave_gateway(
    _kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
) -> dict:
    from packages.desktop import gateway as gw

    for status in ag.detect_agents(home=ctx.home, state_dir=ctx.state_dir, which=ctx.which):
        if status.connected and status.setup == "auto":
            async with _agent_locks[status.id]:
                try:
                    ag.disconnect_agent(status.id, home=ctx.home, state_dir=ctx.state_dir)
                except (ag.AgentConfigError, OSError) as exc:
                    raise HTTPException(status_code=422, detail=f"{status.name}: {exc}") from exc
    gw.forget(ctx.state_dir.parent)
    return {"gateway": None, "agents": _agent_list(ctx)}


# ── settings ────────────────────────────────────────────────────────────


class DesktopSettings(BaseModel):
    daily_budget_cents: int | None = Field(default=None, ge=0)
    # "alert": notify at 80% and 100%. "stop": also refuse coding agents'
    # requests once today's spend reaches the budget.
    budget_mode: Literal["alert", "stop"] = "alert"


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
    # Partial update: fields the caller didn't send keep their saved values.
    current = _desktop_settings(ws).model_dump()
    current.update(body.model_dump(exclude_unset=True))
    updated = DesktopSettings(**current)
    merged = dict(ws.settings_json or {})
    merged["desktop"] = updated.model_dump()
    ws.settings_json = merged  # reassign so SQLAlchemy sees the JSON change
    await db.commit()
    from packages.desktop import budget as budget_gate

    budget_gate.note_settings_changed()
    return updated.model_dump()


# ── summary ─────────────────────────────────────────────────────────────


def _local_midnight_utc(now: datetime, tz_offset_minutes: int) -> datetime:
    local = now + timedelta(minutes=tz_offset_minutes)
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=tz_offset_minutes)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _budget(daily_cents: int | None, spent_today_microcents: int, mode: str = "alert") -> dict:
    if daily_cents is None:
        return {"daily_cents": None, "used_percent": None, "state": "none", "mode": mode}
    if daily_cents == 0:
        pct = 100.0 if spent_today_microcents > 0 else 0.0
    else:
        pct = round(100 * spent_today_microcents / (daily_cents * 10_000), 1)
    state = "over" if pct >= 100 else "warn" if pct >= WARN_AT_PERCENT else "ok"
    return {"daily_cents": daily_cents, "used_percent": pct, "state": state, "mode": mode}


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


def _gateway_info(ctx: DesktopContext) -> dict | None:
    from packages.desktop import gateway as gw

    url = gw.load(ctx.state_dir.parent)
    return {"url": url} if url else None


@router.get("/summary")
async def summary(
    tz_offset_minutes: int = Query(0, ge=-14 * 60, le=14 * 60),
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    today_start = _local_midnight_utc(now, tz_offset_minutes)
    window_start = min(week_start, today_start)

    # Plain rows, not ORM entities: normalising timestamps must never mark
    # log rows as modified (that would autoflush UPDATEs into the log).
    rows = [
        _Row(r.api_key_id, r.provider, r.status_code, int(r.cost_microcents or 0), r.input_tokens,
             r.output_tokens, r.fallback_level, _aware(r.created_at))
        for r in (
            await db.execute(
                select(
                    RequestLog.api_key_id, RequestLog.provider, RequestLog.status_code, RequestLog.cost_microcents,
                    RequestLog.input_tokens, RequestLog.output_tokens, RequestLog.fallback_level,
                    RequestLog.created_at,
                ).where(
                    RequestLog.workspace_id == kc.workspace_id,
                    RequestLog.is_deleted == 0,
                    RequestLog.created_at >= window_start,
                )
            )
        ).all()
    ]

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
        "budget": _budget(settings.daily_budget_cents, spend_today, settings.budget_mode),
        "agents": sorted(buckets.values(), key=lambda b: (b["id"] == "other", -b["week_microcents"])),
        "providers": await _providers(db, kc.workspace_id, recent),
        "hosted": {"configured": bool(get_settings().orcarouter_api_key or hosted_db)},
        "gateway": _gateway_info(ctx),
        "update": updates.CHECKER.latest,
    }
