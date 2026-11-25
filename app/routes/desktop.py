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
import contextlib
import hashlib
import hmac
import os
import shutil
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import route_notes
from app.deps import get_db, get_key_context
from packages.auth.hashing import generate_api_key
from packages.auth.types import KeyContext
from packages.db.models.api_key import ApiKey
from packages.db.models.provider_key import ProviderKey
from packages.db.models.request_log import RequestLog
from packages.db.models.workspace import Workspace
from packages.desktop import agents as ag
from packages.desktop import updates
from packages.litellm_adapter.hosted_catalog import is_free_hosted

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
    route_note: str | None = None
    model_requested: str = ""
    model_resolved: str = ""


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


@router.post("/agents/disconnect-all")
async def disconnect_all_agents(
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restore every connected agent and revoke its key (before uninstalling, say)."""
    disconnected: list[str] = []
    failed: list[dict] = []
    for status in ag.detect_agents(home=ctx.home, state_dir=ctx.state_dir, which=ctx.which):
        if not status.connected:
            continue
        async with _agent_locks[status.id]:
            await _revoke_agent_keys(db, kc.workspace_id, status.id)
            await db.flush()
            try:
                ag.disconnect_agent(status.id, home=ctx.home, state_dir=ctx.state_dir)
            except (ag.AgentConfigError, OSError) as exc:
                await db.rollback()
                failed.append({"name": status.name, "error": str(exc)})
                continue
            await db.commit()
        disconnected.append(status.name)
    return {"disconnected": disconnected, "failed": failed}


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


_AgentId = Annotated[str, Field(min_length=1, max_length=64)]


class AgentModelMap(BaseModel):
    main: str | None = Field(default=None, max_length=200)
    background: str | None = Field(default=None, max_length=200)
    fallback_to_auto: bool = True


class DesktopSettings(BaseModel):
    daily_budget_cents: int | None = Field(default=None, ge=0)
    # "alert": notify at 80% and 100%. "stop": also refuse coding agents'
    # requests once today's spend reaches the budget.
    budget_mode: Literal["alert", "stop"] = "alert"
    # Connected agents point at this engine, so after a restart it has to be
    # running before the user thinks to open the app.
    start_at_login: bool = True
    # Routing preferences, read by the engine through packages/desktop/prefs.py.
    # "free": OrcaRouter serves only its free models; "all": paid ones too.
    hosted_models: Literal["free", "all"] = "free"
    # Per agent id: which model serves its main and background requests.
    agent_models: dict[_AgentId, AgentModelMap] = Field(default_factory=dict)
    # Per agent id: daily cap in cents; the agent is paused once it's reached.
    agent_budgets: dict[_AgentId, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    # Requested model ids whose substitution the user chose to keep.
    kept_substitutions: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list)
    # Offer id -> the day it was dismissed (an offer shows at most once a day).
    dismissed_offers: dict[_AgentId, Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]] = Field(
        default_factory=dict
    )
    # Local model ids auto may use; None means every discovered one with tools.
    local_models: list[Annotated[str, Field(max_length=300)]] | None = None
    # Router knobs that servers set in the environment (which still wins).
    router_num_retries: int | None = Field(default=None, ge=0, le=5)
    router_cooldown_seconds: int | None = Field(default=None, ge=0, le=3600)


# The desktop app runs one engine per home and its panel and setup window both
# save through it, so serializing writes inside this process covers them.
_SETTINGS_WRITE_LOCK = asyncio.Lock()


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
    # Partial update: fields the caller didn't send keep their saved values.
    # The panel and the setup window can save at the same time, each with its
    # own session, so read-merge-write one at a time and re-read the row
    # inside the lock; otherwise a later save would write back the stale
    # copy it read and drop the other's change.
    async with _SETTINGS_WRITE_LOCK:
        ws = await _workspace(db, kc.workspace_id)
        await db.refresh(ws, ["settings_json"])
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


# ── benchmark key (Artificial Analysis) ─────────────────────────────────


class BenchmarkKey(BaseModel):
    api_key: str | None = Field(default=None, max_length=512)


@router.get("/benchmark-key")
async def get_benchmark_key(
    _kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Whether a key is set and where it comes from; never the key."""
    from app import benchmark_key

    await benchmark_key.ensure_loaded(db)
    return benchmark_key.status()


@router.put("/benchmark-key")
async def put_benchmark_key(
    body: BenchmarkKey,
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Save (or with null, clear) the key, encrypted. The environment
    variable, when set, still wins."""
    from app import benchmark_key

    async with _SETTINGS_WRITE_LOCK:  # same row as the settings; don't interleave
        await benchmark_key.save(db, (body.api_key or "").strip() or None, workspace_id=kc.workspace_id)
    return benchmark_key.status()


# ── provider key check ──────────────────────────────────────────────────


class ProviderKeyCheck(BaseModel):
    api_key: str = Field(min_length=1, max_length=8192)


@router.post("/providers/{provider}/check")
async def check_provider_key_route(
    provider: str,
    body: ProviderKeyCheck,
    _kc: KeyContext = Depends(require_app_caller),
) -> dict:
    """Ask the provider whether a key works before setup saves it."""
    import httpx

    from packages.desktop import provider_check

    env = dict(os.environ)
    from app.config import get_settings

    env.setdefault("ORCAROUTER_BASE_URL", get_settings().orcarouter_base_url)
    async with httpx.AsyncClient() as client:
        return await provider_check.check_key(provider.strip().lower(), body.api_key.strip(), client=client, env=env)


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

    # Only providers the user has now: request logs also name deleted ones
    # and "unknown" (failures no provider was attributed to).
    out = []
    for provider in sorted(configured):
        rows = [r for r in recent if r.provider == provider]
        if not rows:
            state = "idle"
        else:
            failed = sum(1 for r in rows if r.status_code >= 400)
            state = "degraded" if failed * 2 >= len(rows) else "healthy"
        out.append({"provider": provider, "source": configured[provider], "state": state})
    return out


def _gateway_info(ctx: DesktopContext) -> dict | None:
    from packages.desktop import gateway as gw

    url = gw.load(ctx.state_dir.parent)
    return {"url": url} if url else None


def _local_month_start_utc(now: datetime, tz_offset_minutes: int) -> datetime:
    local = now + timedelta(minutes=tz_offset_minutes)
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(minutes=tz_offset_minutes)


def _local_date(now: datetime, tz_offset_minutes: int) -> str:
    return (now + timedelta(minutes=tz_offset_minutes)).date().isoformat()


async def _log_rows(db: AsyncSession, workspace_id: str, since: datetime) -> list[_Row]:
    # Plain rows, not ORM entities: normalising timestamps must never mark
    # log rows as modified (that would autoflush UPDATEs into the log).
    result = await db.execute(
        select(
            RequestLog.api_key_id, RequestLog.provider, RequestLog.status_code, RequestLog.cost_microcents,
            RequestLog.input_tokens, RequestLog.output_tokens, RequestLog.fallback_level,
            RequestLog.created_at, RequestLog.route_note, RequestLog.model_requested, RequestLog.model_resolved,
        ).where(
            RequestLog.workspace_id == workspace_id,
            RequestLog.is_deleted == 0,
            RequestLog.created_at >= since,
        )
    )
    return [
        _Row(r.api_key_id, r.provider, r.status_code, int(r.cost_microcents or 0), r.input_tokens,
             r.output_tokens, r.fallback_level, _aware(r.created_at), r.route_note, r.model_requested or "",
             r.model_resolved or "")
        for r in result.all()
    ]


async def _agent_key_ids(db: AsyncSession, workspace_id: str) -> dict[str, str]:
    """api key id -> agent id, for every key an agent has had (reconnecting
    mints a new one; revoked keys still own their past requests)."""
    keys = (await db.execute(select(ApiKey.id, ApiKey.name).where(ApiKey.workspace_id == workspace_id))).all()
    return {kid: name[len(AGENT_KEY_PREFIX):] for kid, name in keys if name.startswith(AGENT_KEY_PREFIX)}


async def _hosted_configured(db: AsyncSession) -> bool:
    from app.config import get_settings
    from app.router_cache import HOSTED_PROVIDER_NAME, usable_providers_from_db

    if get_settings().orcarouter_api_key:
        return True
    # Only a key the router can use: a row that no longer decrypts (after an
    # encryption-key change) deploys nothing.
    rows = (
        await db.execute(
            select(ProviderKey).where(ProviderKey.provider == HOSTED_PROVIDER_NAME, ProviderKey.is_deleted == 0)
        )
    ).scalars().all()
    return HOSTED_PROVIDER_NAME in usable_providers_from_db(list(rows))


async def _hosted_month(db: AsyncSession, workspace_id: str, since: datetime) -> tuple[int, int, int]:
    """(spend, requests, rescued) through OrcaRouter since `since` (H4)."""
    from sqlalchemy import case, func

    from app.route_notes import HOSTED_PROVIDER

    count, spend, rescued = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(RequestLog.cost_microcents), 0),
                func.coalesce(func.sum(case((RequestLog.fallback_level > 0, 1), else_=0)), 0),
            ).where(
                RequestLog.workspace_id == workspace_id,
                RequestLog.is_deleted == 0,
                RequestLog.provider == HOSTED_PROVIDER,
                RequestLog.status_code < 400,
                RequestLog.created_at >= since,
            )
        )
    ).one()
    return int(spend or 0), int(count or 0), int(rescued or 0)


def _hosted_links(source: str) -> dict:
    from app.config import get_settings
    from packages.desktop.links import with_ref

    s = get_settings()
    return {
        "console_url": with_ref(s.orcarouter_console_url, source),
        "billing_url": with_ref(s.orcarouter_billing_url, source),
        "token_url": with_ref(s.orcarouter_token_url, source),
        "signup_url": with_ref(s.orcarouter_signup_url, source),
    }


def _backup_offer(failed: list[_Row], agent_of: dict[str, str]) -> dict | None:
    """H2: today's failures with no other provider left, for the provider that
    failed most. None when nothing failed that way."""
    if not failed:
        return None
    provider, count = Counter(r.provider for r in failed).most_common(1)[0]
    mine = [r for r in failed if r.provider == provider]
    agents = Counter(agent_of[r.api_key_id] for r in mine if r.api_key_id in agent_of)
    models = Counter(r.model_resolved or r.model_requested for r in mine)
    return {
        "id": "backup",
        "failed_today": count,
        "provider": provider,
        "agent": agents.most_common(1)[0][0] if agents else None,
        "models": [m for m, _n in models.most_common(5) if m],
    }


def _is_substitution(r: _Row) -> bool:
    """The agent named a model and a different one answered, without the
    user's own model map choosing it. "free" and "local" outrank
    "substituted" as notes, so those rows are compared by name."""
    if r.route_note == route_notes.SUBSTITUTED:
        return True
    if r.route_note not in (route_notes.FREE, route_notes.LOCAL) or r.model_requested in ("", "auto"):
        return False
    from app.auto_routing import canonical_model_base

    def base(m: str) -> str:
        return canonical_model_base(m.rsplit("/", 1)[-1]).replace(".", "-")

    return base(r.model_requested) != base(r.model_resolved)


def _substitutions(rows: list[_Row], kept: set[str]) -> list[dict]:
    """H3: what an agent asked for and what answered instead."""
    pairs = Counter(
        (r.model_requested, r.model_resolved) for r in rows
        if _is_substitution(r) and r.model_requested not in kept
    )
    return [{"requested": req, "served": served, "count": n} for (req, served), n in pairs.most_common()]


def _agent_state(status: ag.AgentStatus | None) -> str:
    if status is None or not status.connected:
        return "disconnected"
    return "changed" if status.changed else "connected"


# The panel polls the summary; it must never wait for local discovery (up to
# a second per runtime). It shows the last result and refreshes it here.
_local_refresh: asyncio.Task | None = None


def _refresh_local_models_in_background() -> None:
    global _local_refresh
    from packages.desktop import local_models

    if local_models.disabled() or (_local_refresh is not None and not _local_refresh.done()):
        return

    async def _run() -> None:
        with contextlib.suppress(Exception):
            await local_models.discover()

    _local_refresh = asyncio.get_running_loop().create_task(_run())


def _local_summary() -> dict:
    from packages.desktop import local_models

    _refresh_local_models_in_background()
    return {"runtimes": [
        {"id": r.id, "name": r.name, "url": r.url, "running": r.running, "models": len(r.models)}
        for r in local_models.last()
    ]}


@router.get("/summary")
async def summary(
    tz_offset_minutes: int = Query(0, ge=-14 * 60, le=14 * 60),
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from packages.desktop import hosted_state
    from packages.desktop.links import PANEL
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    today_start = _local_midnight_utc(now, tz_offset_minutes)
    rows = await _log_rows(db, kc.workspace_id, min(week_start, today_start))

    ok = [r for r in rows if r.status_code < 400]
    week = [r for r in ok if r.created_at >= week_start]
    today = [r for r in ok if r.created_at >= today_start]
    today_all = [r for r in rows if r.created_at >= today_start]

    agent_of = await _agent_key_ids(db, kc.workspace_id)
    settings = _desktop_settings(await _workspace(db, kc.workspace_id))
    # Off the event loop: detection checks PATH and reads each agent's config.
    statuses = {
        s.id: s for s in await asyncio.to_thread(
            ag.detect_agents, home=ctx.home, state_dir=ctx.state_dir, which=ctx.which,
        )
    }

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
                "state": _agent_state(statuses.get(agent_id)) if spec else "other",
                "substitutions": [],
                "budget_cents": settings.agent_budgets.get(agent_id) if spec else None,
                "paused": False,
            }
        return buckets[agent_id]

    # Every connected agent shows, even before it has spent anything.
    for status in statuses.values():
        if status.connected:
            _bucket(status.id)
    for r in week:
        b = _bucket(agent_of.get(r.api_key_id, "other"))
        b["week_microcents"] += r.cost_microcents
        b["requests_week"] += 1
    for r in today:
        _bucket(agent_of.get(r.api_key_id, "other"))["today_microcents"] += r.cost_microcents
    kept = set(settings.kept_substitutions)
    for agent_id, b in buckets.items():
        if agent_id == "other":
            continue
        b["substitutions"] = _substitutions([r for r in today if agent_of.get(r.api_key_id) == agent_id], kept)
        if b["budget_cents"] is not None:
            b["paused"] = b["today_microcents"] >= b["budget_cents"] * 10_000

    spend_today = sum(r.cost_microcents for r in today)
    spend_week = sum(r.cost_microcents for r in week)
    baseline = CATALOG_BY_ID.get(BASELINE_MODEL)
    saved = max(0, _baseline_microcents(week, baseline) - spend_week) if baseline else 0
    local_week = [r for r in week if r.provider == route_notes.LOCAL_PROVIDER]

    recent = [r for r in rows if r.created_at >= now - HEALTH_WINDOW]
    hosted_configured = await _hosted_configured(db)
    month_spend, month_requests, month_rescued = await _hosted_month(
        db, kc.workspace_id, _local_month_start_utc(now, tz_offset_minutes)
    )

    offers = []
    if not hosted_configured and settings.dismissed_offers.get("backup") != _local_date(now, tz_offset_minutes):
        offer = _backup_offer([r for r in today_all if r.route_note == route_notes.NO_FALLBACK], agent_of)
        if offer:
            offers.append(offer)

    return {
        "currency": "USD",
        "generated_at": now.isoformat(),
        "today": {
            "spend_microcents": spend_today,
            "requests": len(today),
            # Every free answer, whatever its note (a model map can choose a
            # free model too).
            "free_requests": sum(
                1 for r in today
                if r.route_note == route_notes.FREE or (r.provider == "orcarouter" and is_free_hosted(r.model_resolved))
            ),
            # Spend through OrcaRouter today: its free models cost nothing,
            # so this is what its paid models cost.
            "paid_spend_microcents": sum(r.cost_microcents for r in today if r.provider == route_notes.HOSTED_PROVIDER),
        },
        "week": {
            "spend_microcents": spend_week,
            "requests": len(week),
            "saved_microcents": saved,
            "baseline_model": BASELINE_MODEL,
            "failures_avoided": sum(1 for r in week if (r.fallback_level or 0) > 0),
            # Served on this computer at $0; priced at the baseline, that's
            # what they would have cost (already part of saved_microcents).
            "local_requests": len(local_week),
            "local_saved_microcents": _baseline_microcents(local_week, baseline) if baseline else 0,
            "hosted_requests": sum(1 for r in week if r.provider == route_notes.HOSTED_PROVIDER),
        },
        "budget": _budget(settings.daily_budget_cents, spend_today, settings.budget_mode),
        "agents": sorted(buckets.values(), key=lambda b: (b["id"] == "other", -b["week_microcents"])),
        "providers": await _providers(db, kc.workspace_id, recent),
        "hosted": {
            "configured": hosted_configured,
            "models": settings.hosted_models,
            "out_of_credit": hosted_state.out_of_credit(),
            "month_spend_microcents": month_spend,
            "month_requests": month_requests,
            "month_rescued": month_rescued,
            "needs_paid_today": sum(1 for r in today_all if r.route_note == route_notes.NEEDS_PAID),
            **_hosted_links(PANEL),
        },
        "offers": offers,
        "local": _local_summary(),
        "gateway": _gateway_info(ctx),
        "update": updates.CHECKER.latest,
    }


# ── model picker (H5) ───────────────────────────────────────────────────


async def _own_providers(db: AsyncSession) -> set[str]:
    from app.config import get_settings
    from app.router_cache import HOSTED_PROVIDER_NAME, usable_providers_from_db

    rows = (await db.execute(select(ProviderKey).where(ProviderKey.is_deleted == 0))).scalars().all()
    own = set(usable_providers_from_db(list(rows))) | set(get_settings().env_provider_keys())
    own.discard(HOSTED_PROVIDER_NAME)
    return own


@router.get("/models")
async def picker_models(
    q: str | None = Query(None, max_length=200),
    limit: int = Query(80, ge=1, le=1000),
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Every model a picker can offer: own keys, this computer, OrcaRouter's
    free and paid models, with prices per million tokens."""
    from packages.desktop import local_models, model_picker

    settings = _desktop_settings(await _workspace(db, kc.workspace_id))
    hosted = await _hosted_configured(db)
    inputs = model_picker.PickerInputs(
        own_providers=frozenset(await _own_providers(db)),
        runtimes=tuple(local_models.last()),
        local_selection=settings.local_models,
        hosted_configured=hosted,
        hosted_models=settings.hosted_models,
    )
    return {"groups": model_picker.groups(inputs, q=q, limit=limit), "hosted_configured": hosted}


# ── models on this computer (P2) ────────────────────────────────────────


def _local_out(runtimes: list, selection: list[str] | None) -> dict:
    from packages.desktop import local_models

    out = []
    for rt in runtimes:
        allowed = {m.id for m in local_models.enabled(list(rt.models), selection)}
        out.append({
            "id": rt.id, "name": rt.name, "url": rt.url, "running": rt.running,
            "models": [
                {"id": m.id, "name": m.name, "tools": m.tools, "vision": m.vision, "context": m.context,
                 "enabled": m.id in allowed}
                for m in rt.models
            ],
        })
    return {"runtimes": out}


@router.get("/local")
async def local_runtimes(
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ollama, LM Studio and llama.cpp on this computer, with their models and
    whether auto may use each (cached; at most a second per runtime)."""
    from packages.desktop import local_models

    runtimes = local_models.last() if local_models.disabled() else await local_models.discover()
    settings = _desktop_settings(await _workspace(db, kc.workspace_id))
    return _local_out(runtimes, settings.local_models)


@router.post("/local/refresh")
async def refresh_local_runtimes(
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Look again now (a runtime was just started) and rebuild the router so
    the models found can serve the next request."""
    from app import router_cache
    from packages.desktop import local_models

    runtimes = await local_models.discover(force=True)
    router_cache.invalidate_router()
    settings = _desktop_settings(await _workspace(db, kc.workspace_id))
    return _local_out(runtimes, settings.local_models)


# ── per-agent request log (D3) ──────────────────────────────────────────


@router.get("/agents/{agent_id}/requests")
async def agent_requests(
    agent_id: str,
    limit: int = Query(50, ge=1, le=500),
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The agent's latest requests, newest first, through every key it has had."""
    if agent_id not in ag.AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    key_ids = select(ApiKey.id).where(
        ApiKey.workspace_id == kc.workspace_id, ApiKey.name == f"{AGENT_KEY_PREFIX}{agent_id}"
    )
    rows = (
        await db.execute(
            select(
                RequestLog.created_at, RequestLog.model_requested, RequestLog.model_resolved, RequestLog.provider,
                RequestLog.input_tokens, RequestLog.output_tokens, RequestLog.cost_microcents,
                RequestLog.latency_ms, RequestLog.status_code, RequestLog.fallback_level, RequestLog.route_note,
            )
            .where(
                RequestLog.workspace_id == kc.workspace_id,
                RequestLog.is_deleted == 0,
                RequestLog.api_key_id.in_(key_ids),
            )
            .order_by(RequestLog.created_at.desc())
            .limit(limit)
        )
    ).all()
    return {"requests": [
        {
            "at": _aware(r.created_at).isoformat(),
            "model_requested": r.model_requested,
            "model": r.model_resolved,
            "provider": r.provider,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_microcents": int(r.cost_microcents or 0),
            "latency_ms": r.latency_ms,
            "status": r.status_code,
            "rescued": r.status_code < 400 and (r.fallback_level or 0) > 0,
            "note": r.route_note,
        }
        for r in rows
    ]}


# ── test an agent (D4) ──────────────────────────────────────────────────


def get_agent_test_transport():
    """How the test request travels: the network, to the engine's own port
    (tests deliver it in-process)."""
    return None


async def _failed_test_row(db: AsyncSession, workspace_id: str, agent_id: str, since: datetime):
    from packages.desktop import agent_test

    key_ids = select(ApiKey.id).where(ApiKey.workspace_id == workspace_id,
                                      ApiKey.name == f"{AGENT_KEY_PREFIX}{agent_id}")
    row = (
        await db.execute(
            select(RequestLog.provider, RequestLog.error_type, RequestLog.status_code)
            .where(
                RequestLog.workspace_id == workspace_id,
                RequestLog.api_key_id.in_(key_ids),
                RequestLog.status_code >= 400,
                RequestLog.created_at >= since,
            )
            .order_by(RequestLog.created_at.desc())
            .limit(1)
        )
    ).first()
    return agent_test.FailedRow(row.provider, row.error_type, row.status_code) if row else None


@router.post("/agents/{agent_id}/test")
async def test_agent(
    agent_id: str,
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
    transport=Depends(get_agent_test_transport),
) -> dict:
    """Send one tiny request the way the agent would, and say how it went."""
    from packages.desktop import agent_test

    spec = ag.AGENTS.get(agent_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent_id}")
    out: dict = {"ok": False, "model": None, "seconds": None, "config_path": None, "error": None}

    def done(**kw) -> dict:
        out.update(kw)
        agent_test.remember(agent_id, out["ok"], out["error"])
        return out

    if spec.setup != "auto":
        return done(ok=None, error=f"Paste the key into {spec.name}, then test from the agent.")
    status = next(s for s in ag.detect_agents(home=ctx.home, state_dir=ctx.state_dir, which=ctx.which)
                  if s.id == agent_id)
    path = agent_test.display_path(ctx.home / spec.config_file, ctx.home) if spec.config_file else None
    out["config_path"] = path
    if not status.connected:
        return done(error=f"{spec.name} isn't connected to Orca. Connect it, then test.")
    if status.changed:
        return done(error=f"Something replaced Orca's settings in {path}, probably {spec.name}'s last update. "
                          f"Reconnect {spec.name}, then test again.")
    try:
        ep = await asyncio.to_thread(agent_test.read_endpoint, agent_id, home=ctx.home, state_dir=ctx.state_dir)
    except agent_test.ConfigError as exc:
        return done(error=str(exc))

    # Logged rows carry second-precision timestamps on SQLite.
    started = datetime.now(timezone.utc) - timedelta(seconds=2)
    result = await agent_test.send(ep, transport=transport)
    failed = None
    if not result.ok and result.status is not None:
        failed = await _failed_test_row(db, kc.workspace_id, agent_id, started)
    shown_base = ep.base_url.rstrip("/").removesuffix("/v1")
    return done(
        ok=result.ok,
        model=result.model,
        seconds=result.seconds,
        config_path=agent_test.display_path(ep.config_path, ctx.home),
        error=agent_test.explain(result, agent_name=spec.name, base_url=shown_base, failed=failed),
    )


# ── diagnostics (D8) ────────────────────────────────────────────────────


async def _routing_line(db: AsyncSession, workspace_id: str, settings: DesktopSettings, hosted: bool) -> str:
    from packages.db.models.routing_config import RoutingConfig

    row = (
        await db.execute(
            select(RoutingConfig.strategy).where(RoutingConfig.workspace_id == workspace_id,
                                                 RoutingConfig.is_deleted == 0)
        )
    ).first()
    strategy = row.strategy if row else "balanced"
    if not hosted:
        orca = "not set up"
    else:
        orca = "free models only" if settings.hosted_models == "free" else "free and paid models"
    return f"{strategy} · OrcaRouter: {orca} · budget: {settings.budget_mode}"


@router.get("/diagnostics")
async def diagnostics_report(
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Versions, agents, providers, routing, local runtimes and the engine
    log's tail, with keys masked, paths under ~ and no prompt text."""
    from packages.desktop import agent_test, local_models
    from packages.desktop import diagnostics as dg

    settings = _desktop_settings(await _workspace(db, kc.workspace_id))
    recent = await _log_rows(db, kc.workspace_id, datetime.now(timezone.utc) - HEALTH_WINDOW)
    statuses = await asyncio.to_thread(ag.detect_agents, home=ctx.home, state_dir=ctx.state_dir, which=ctx.which)
    app_version, engine_version = dg.versions()
    text = dg.build(
        version=app_version,
        engine_version=engine_version,
        engine=f"running at {ctx.base_url}",
        agents=dg.agent_rows(statuses, agent_test.LAST),
        providers=await _providers(db, kc.workspace_id, recent),
        routing=await _routing_line(db, kc.workspace_id, settings, await _hosted_configured(db)),
        local=dg.local_lines(local_models.last()),
        log_lines=await asyncio.to_thread(dg.log_tail, ctx.state_dir.parent / "engine.log"),
        home=ctx.home,
    )
    return {"text": text}


# ── weekly report (H7) ──────────────────────────────────────────────────

_ReportFormat = Literal["markdown", "md", "csv"]
_ReportWeek = Literal["last", "this"]


async def _weekly(db: AsyncSession, workspace_id: str, fmt: str, week: str, tz_offset_minutes: int):
    """(filename, content) of one Monday-to-Sunday week in the caller's timezone."""
    from packages.desktop import report

    now = datetime.now(timezone.utc)
    local_today = (now + timedelta(minutes=tz_offset_minutes)).date()
    monday = local_today - timedelta(days=local_today.weekday())
    if week == "last":
        monday -= timedelta(days=7)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc) - timedelta(minutes=tz_offset_minutes)
    end = start + timedelta(days=7)
    rows = [r for r in await _log_rows(db, workspace_id, start) if r.created_at < end and r.status_code < 400]
    agent_of = await _agent_key_ids(db, workspace_id)

    def name(api_key_id: str) -> str:
        spec = ag.AGENTS.get(agent_of.get(api_key_id, ""))
        return spec.name if spec else "Other apps"

    built = report.build_week(monday, rows, name)
    kind = "csv" if fmt == "csv" else "markdown"
    return report.filename(built, kind), report.weekly(built, kind)


@router.get("/report")
async def weekly_report(
    format: _ReportFormat = Query("markdown"),  # noqa: A002 - the query parameter's name
    week: _ReportWeek = Query("last"),
    tz_offset_minutes: int = Query(0, ge=-14 * 60, le=14 * 60),
    kc: KeyContext = Depends(require_app_caller),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One week's spend by agent and model, Monday to Sunday, as Markdown to
    copy or CSV to save (the same code as `orca report`)."""
    name, content = await _weekly(db, kc.workspace_id, format, week, tz_offset_minutes)
    return {"filename": name, "content": content}


class ReportSave(BaseModel):
    format: _ReportFormat = "csv"
    week: _ReportWeek = "last"
    tz_offset_minutes: int = Field(default=0, ge=-14 * 60, le=14 * 60)


def _write_new(path: Path, content: str) -> None:
    # "x": fail rather than replace a file that appeared since the check.
    with open(path, "x", encoding="utf-8") as f:
        f.write(content)


@router.post("/report/save")
async def save_weekly_report(
    body: ReportSave,
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Write the report to ~/Downloads (or the home folder without one)."""
    from packages.desktop.agent_test import display_path

    name, content = await _weekly(db, kc.workspace_id, body.format, body.week, body.tz_offset_minutes)
    folder = ctx.home / "Downloads"
    if not folder.is_dir():
        folder = ctx.home
    stem, dot, ext = name.rpartition(".")
    path = folder / name
    n = 2
    while path.exists():  # never overwrite an earlier save
        path = folder / f"{stem}-{n}{dot}{ext}"
        n += 1
    try:
        await asyncio.to_thread(_write_new, path, content)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't save {display_path(path, ctx.home)}: "
                                                    f"{exc.strerror or exc}") from exc
    return {"path": display_path(path, ctx.home)}


# ── sharing (V2, V3) ────────────────────────────────────────────────────


@router.get("/share/card")
async def share_card(
    tz_offset_minutes: int = Query(0, ge=-14 * 60, le=14 * 60),
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The week's totals for the savings card: no prompts, models or keys."""
    from packages.desktop.links import CARD, LANDING_URL, with_ref

    s = await summary(tz_offset_minutes=tz_offset_minutes, kc=kc, ctx=ctx, db=db)
    week = s["week"]
    return {
        "week_saved_microcents": week["saved_microcents"],
        "week_spend_microcents": week["spend_microcents"],
        "rescued": week["failures_avoided"],
        "agents": [a["name"] for a in s["agents"] if a["id"] != "other" and a["requests_week"] > 0],
        "local_requests": week["local_requests"],
        "link": with_ref(LANDING_URL, CARD),
    }


@router.get("/share/setup")
async def share_setup(
    kc: KeyContext = Depends(require_app_caller),
    ctx: DesktopContext = Depends(get_desktop_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """An orca://setup link a teammate can open: agent ids and the daily
    budget only, never a key."""
    settings = _desktop_settings(await _workspace(db, kc.workspace_id))
    agents = [s.id for s in ag.detect_agents(home=ctx.home, state_dir=ctx.state_dir, which=ctx.which) if s.connected]
    params = []
    if agents:
        params.append(f"agents={','.join(agents)}")
    if settings.daily_budget_cents is not None:
        params.append(f"budget={settings.daily_budget_cents}")
    return {"link": "orca://setup" + (f"?{'&'.join(params)}" if params else "")}
