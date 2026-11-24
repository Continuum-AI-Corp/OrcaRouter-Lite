"""/v1/app — the local API behind the Orca desktop app and `orca` CLI.

Only mounted in desktop mode (the engine bound to 127.0.0.1 on the user's
own machine), because it edits files in the user's home directory.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from packages.desktop import agents as ag


@pytest.fixture
def desktop_dirs(tmp_path):
    home = tmp_path / "home"
    state = tmp_path / "state"
    home.mkdir()
    state.mkdir()
    (home / ".claude").mkdir()
    return home, state


@pytest.fixture
async def seeded(db_session):
    from app.seed import seed_initial_state
    from packages.auth.hashing import generate_api_key
    from packages.db.models.api_key import ApiKey

    await seed_initial_state(db_session)
    app_key, h, prefix = generate_api_key()
    db_session.add(ApiKey(workspace_id="default", name="desktop-app", key_hash=h, key_prefix=prefix))
    full, h, prefix = generate_api_key()
    db_session.add(ApiKey(workspace_id="default", name="restricted", key_hash=h, key_prefix=prefix,
                          model_allowlist=["gpt-4o-mini"]))
    await db_session.commit()
    return app_key, full


def _patch_sessions(monkeypatch, db_session):
    from packages.db import session as session_mod

    class _Passthrough:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(session_mod, "_session_factory", lambda: _Passthrough())


@pytest.fixture
def desktop_app(db_session, monkeypatch, desktop_dirs):
    monkeypatch.setenv("DATABASE_URL", str(db_session.bind.url))
    _patch_sessions(monkeypatch, db_session)
    from fastapi import FastAPI

    from app.middleware.auth import AuthMiddleware
    from app.routes import desktop

    home, state = desktop_dirs
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(desktop.router)
    app.dependency_overrides[desktop.get_desktop_context] = lambda: desktop.DesktopContext(
        home=home, state_dir=state, base_url="http://127.0.0.1:8765", which=lambda _n: None
    )
    return app


def _client(app):
    from httpx import ASGITransport, AsyncClient

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8765")


def _auth(key):
    return {"Authorization": f"Bearer {key}"}


# ── mounting ────────────────────────────────────────────────────────────


async def _create_app(monkeypatch, db_session, desktop: bool):
    from app import config

    monkeypatch.setenv("DATABASE_URL", str(db_session.bind.url))
    if desktop and "HOST" not in __import__("os").environ:
        monkeypatch.setenv("HOST", "127.0.0.1")
    if desktop:
        monkeypatch.setenv("ORCA_DESKTOP_MODE", "1")
    else:
        monkeypatch.delenv("ORCA_DESKTOP_MODE", raising=False)
    config.get_settings.cache_clear()
    _patch_sessions(monkeypatch, db_session)
    from app.main import create_app

    try:
        return create_app()
    finally:
        config.get_settings.cache_clear()


async def test_app_api_is_not_mounted_outside_desktop_mode(monkeypatch, db_session, seeded):
    root, _ = seeded
    app = await _create_app(monkeypatch, db_session, desktop=False)
    async with _client(app) as c:
        r = await c.get("/v1/app/agents", headers=_auth(root))
    assert r.status_code == 404


async def test_app_api_is_mounted_in_desktop_mode(monkeypatch, db_session, seeded):
    root, _ = seeded
    app = await _create_app(monkeypatch, db_session, desktop=True)
    async with _client(app) as c:
        r = await c.get("/v1/app/settings", headers=_auth(root))
    assert r.status_code == 200


# ── agents ──────────────────────────────────────────────────────────────


async def test_list_agents(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/agents", headers=_auth(root))
    assert r.status_code == 200
    by_id = {a["id"]: a for a in r.json()["agents"]}
    assert by_id["claude-code"]["installed"] is True
    assert by_id["claude-code"]["connected"] is False
    assert by_id["codex"]["setup"] == "auto"
    assert by_id["cline"]["setup"] == "manual"


async def test_connect_writes_config_with_a_dedicated_working_key(desktop_app, seeded, desktop_dirs, db_session):
    from packages.auth.key_validator import validate_api_key

    root, _ = seeded
    home, _state = desktop_dirs
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True
    assert "api_key" not in body  # auto-configured agents never get the key echoed back

    env = json.loads((home / ".claude" / "settings.json").read_text())["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8765"
    kc = await validate_api_key(env["ANTHROPIC_AUTH_TOKEN"], db_session)
    assert kc.name == "agent:claude-code"


async def test_reconnect_revokes_the_previous_agent_key(desktop_app, seeded, desktop_dirs, db_session):
    from packages.auth.key_validator import AuthError, validate_api_key

    root, _ = seeded
    home, _state = desktop_dirs
    settings = home / ".claude" / "settings.json"
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        first = json.loads(settings.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    second = json.loads(settings.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
    assert first != second
    with pytest.raises(AuthError):
        await validate_api_key(first, db_session)


async def test_disconnect_restores_config_and_revokes_key(desktop_app, seeded, desktop_dirs, db_session):
    from packages.auth.key_validator import AuthError, validate_api_key

    root, _ = seeded
    home, _state = desktop_dirs
    settings = home / ".claude" / "settings.json"
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        key = json.loads(settings.read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
        r = await c.post("/v1/app/agents/claude-code/disconnect", headers=_auth(root))
    assert r.status_code == 200
    assert r.json()["connected"] is False
    assert not settings.exists()
    with pytest.raises(AuthError):
        await validate_api_key(key, db_session)


async def test_manual_agent_gets_its_key_once(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/cursor/connect", headers=_auth(root))
    body = r.json()
    assert body["manual"] is True
    assert body["base_url"] == "http://127.0.0.1:8765/v1"
    assert body["api_key"].startswith("sk-orca-")


async def test_unsupported_agent_returns_409_with_reason(desktop_app, seeded, monkeypatch):
    from packages.desktop import agents as ag

    monkeypatch.setitem(ag.AGENTS, "future", ag.AgentSpec(
        id="future", name="Future", binaries=(), config_dirs=(), setup="unsupported", note="Needs a newer Lite."))
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/future/connect", headers=_auth(root))
    assert r.status_code == 409
    assert "Needs a newer Lite" in r.text


async def test_connect_codex_writes_a_working_bearer_token(desktop_app, seeded, desktop_dirs, db_session):
    import tomllib

    from packages.auth.key_validator import validate_api_key

    root, _ = seeded
    home, _state = desktop_dirs
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/codex/connect", headers=_auth(root))
    assert r.status_code == 200, r.text
    provider = tomllib.loads((home / ".codex" / "config.toml").read_text())["model_providers"]["orca"]
    assert provider["base_url"] == "http://127.0.0.1:8765/v1"
    kc = await validate_api_key(provider["experimental_bearer_token"], db_session)
    assert kc.name == "agent:codex"


async def test_unknown_agent_is_404(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/notepad/connect", headers=_auth(root))
    assert r.status_code == 404


async def test_broken_agent_config_is_reported_not_overwritten(desktop_app, seeded, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    (home / ".claude" / "settings.json").write_text("{ nope")
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    assert r.status_code == 422
    assert (home / ".claude" / "settings.json").read_text() == "{ nope"


async def test_restricted_key_cannot_use_the_app_api(desktop_app, seeded):
    _, restricted = seeded
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/claude-code/connect", headers=_auth(restricted))
    assert r.status_code == 403


async def test_agent_key_cannot_use_the_app_api(desktop_app, seeded, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        agent_key = json.loads((home / ".claude" / "settings.json").read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
        r = await c.get("/v1/app/summary", headers=_auth(agent_key))
    assert r.status_code == 403


# ── settings ────────────────────────────────────────────────────────────


async def test_daily_budget_round_trip(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 2000})
        assert r.status_code == 200
        r = await c.get("/v1/app/settings", headers=_auth(root))
    assert r.json()["daily_budget_cents"] == 2000


async def test_daily_budget_can_be_cleared(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 2000})
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": None})
        r = await c.get("/v1/app/settings", headers=_auth(root))
    assert r.json()["daily_budget_cents"] is None


async def test_negative_budget_is_rejected(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": -5})
    assert r.status_code == 422


# ── summary ─────────────────────────────────────────────────────────────


async def _key_id(db_session, name):
    from packages.db.models.api_key import ApiKey

    return (await db_session.execute(select(ApiKey.id).where(ApiKey.name == name, ApiKey.revoked_at.is_(None)))).scalar_one()


def _log(api_key_id, cost_microcents, when, *, fallback=0, status=200, provider="anthropic",
         model="claude-3-5-haiku-latest", tokens=(1000, 500)):
    from packages.db.models.request_log import RequestLog

    return RequestLog(
        workspace_id="default", api_key_id=api_key_id, trace_id="t", model_requested="auto",
        model_resolved=model, provider=provider, routing_strategy="balanced", fallback_level=fallback,
        input_tokens=tokens[0], output_tokens=tokens[1], cost_microcents=cost_microcents, latency_ms=100,
        status_code=status, created_at=when,
    )


async def test_summary_splits_spend_by_agent_and_period(desktop_app, seeded, db_session):
    root, _ = seeded
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        cc = await _key_id(db_session, "agent:claude-code")
        root_id = await _key_id(db_session, "default")
        now = datetime.now(timezone.utc)
        db_session.add_all([
            _log(cc, 1_000_000, now - timedelta(minutes=5)),       # $1.00 today
            _log(cc, 600_000, now - timedelta(minutes=10)),        # $0.60 today
            _log(cc, 2_000_000, now - timedelta(days=3)),          # $2.00 this week
            _log(cc, 9_000_000, now - timedelta(days=9)),          # outside the week
            _log(root_id, 400_000, now - timedelta(minutes=1)),    # $0.40 today, not an agent
            _log(cc, 5_000_000, now - timedelta(minutes=2), status=500),  # failed: no spend
        ])
        await db_session.commit()
        r = await c.get("/v1/app/summary", headers=_auth(root), params={"tz_offset_minutes": 0})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["today"]["spend_microcents"] == 2_000_000
    assert s["week"]["spend_microcents"] == 4_000_000
    by = {a["id"]: a for a in s["agents"]}
    assert by["claude-code"]["today_microcents"] == 1_600_000
    assert by["claude-code"]["week_microcents"] == 3_600_000
    assert by["other"]["today_microcents"] == 400_000


async def test_summary_today_follows_the_callers_timezone(desktop_app, seeded, db_session):
    root, _ = seeded
    root_id = await _key_id(db_session, "default")
    offset = 120  # UTC+2
    now_local = datetime.now(timezone.utc) + timedelta(minutes=offset)
    local_midnight_utc = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=offset)
    db_session.add_all([
        _log(root_id, 700_000, local_midnight_utc + timedelta(seconds=30)),   # after local midnight
        _log(root_id, 300_000, local_midnight_utc - timedelta(seconds=30)),   # before it
    ])
    await db_session.commit()
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/summary", headers=_auth(root), params={"tz_offset_minutes": offset})
    assert r.json()["today"]["spend_microcents"] == 700_000


@pytest.mark.parametrize(
    "spent,state",
    [(0, "ok"), (1_500_000, "ok"), (1_700_000, "warn"), (2_000_000, "over"), (2_500_000, "over")],
)
async def test_summary_budget_state(desktop_app, seeded, db_session, spent, state):
    root, _ = seeded
    root_id = await _key_id(db_session, "default")
    if spent:
        db_session.add(_log(root_id, spent, datetime.now(timezone.utc) - timedelta(minutes=1)))
        await db_session.commit()
    async with _client(desktop_app) as c:
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 200})  # $2.00
        r = await c.get("/v1/app/summary", headers=_auth(root), params={"tz_offset_minutes": 0})
    b = r.json()["budget"]
    assert b["daily_cents"] == 200
    assert b["state"] == state


async def test_summary_without_budget(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/summary", headers=_auth(root))
    assert r.json()["budget"] == {"daily_cents": None, "used_percent": None, "state": "none", "mode": "alert"}


async def test_summary_counts_failures_avoided_and_savings(desktop_app, seeded, db_session):
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    root, _ = seeded
    root_id = await _key_id(db_session, "default")
    now = datetime.now(timezone.utc)
    db_session.add_all([
        _log(root_id, 100_000, now - timedelta(hours=1), fallback=1),
        _log(root_id, 100_000, now - timedelta(hours=2), fallback=1),
        _log(root_id, 100_000, now - timedelta(hours=3)),
    ])
    await db_session.commit()
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/summary", headers=_auth(root))
    s = r.json()
    assert s["week"]["failures_avoided"] == 2
    base = CATALOG_BY_ID["gpt-4o"]
    baseline = 3 * int(1000 * base.input_cost_per_token * 1_000_000 + 500 * base.output_cost_per_token * 1_000_000)
    assert s["week"]["baseline_model"] == "gpt-4o"
    assert s["week"]["saved_microcents"] == max(0, baseline - 300_000)


async def test_summary_reports_provider_health(desktop_app, seeded, db_session):
    root, _ = seeded
    root_id = await _key_id(db_session, "default")
    now = datetime.now(timezone.utc)
    db_session.add_all([
        _log(root_id, 1, now - timedelta(minutes=3), provider="anthropic"),
        _log(root_id, 0, now - timedelta(minutes=2), provider="openai", status=429),
        _log(root_id, 0, now - timedelta(minutes=1), provider="openai", status=500),
    ])
    await db_session.commit()
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/summary", headers=_auth(root))
    health = {p["provider"]: p["state"] for p in r.json()["providers"]}
    assert health["anthropic"] == "healthy"
    assert health["openai"] == "degraded"


# ── desktop UI served by the engine ─────────────────────────────────────


async def test_desktop_ui_is_served_in_desktop_mode(monkeypatch, db_session, seeded):
    app = await _create_app(monkeypatch, db_session, desktop=True)
    async with _client(app) as c:
        r = await c.get("/desktop/panel.html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # The page never carries a credential: the app injects it at runtime.
    assert "sk-orca-" not in r.text


async def test_desktop_ui_is_not_served_outside_desktop_mode(monkeypatch, db_session, seeded):
    app = await _create_app(monkeypatch, db_session, desktop=False)
    async with _client(app) as c:
        r = await c.get("/desktop/panel.html")
    assert r.status_code == 404



# ── review fixes ────────────────────────────────────────────────────────


async def test_only_the_desktop_app_key_can_use_the_app_api(desktop_app, db_session, seeded):
    from app.seed import seed_initial_state  # noqa: F401  (seeded already ran it)
    from packages.auth.hashing import generate_api_key
    from packages.db.models.api_key import ApiKey

    other, h, prefix = generate_api_key()
    db_session.add(ApiKey(workspace_id="default", name="some-script", key_hash=h, key_prefix=prefix))
    await db_session.commit()
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/summary", headers=_auth(other))
    assert r.status_code == 403


async def test_failed_db_commit_leaves_the_agent_config_untouched(desktop_app, seeded, desktop_dirs, db_session,
                                                                 monkeypatch):
    root, _ = seeded
    home, _ = desktop_dirs
    settings = home / ".claude" / "settings.json"
    settings.write_text('{"model": "opus"}')

    async def boom():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(db_session, "commit", boom)
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    assert r.status_code >= 500 or r.status_code == 503
    assert settings.read_text() == '{"model": "opus"}'
    assert not ag.detect_agents(home=home, state_dir=desktop_dirs[1], which=lambda _n: None)[0].connected


async def test_unwritable_config_is_a_clear_error(desktop_app, seeded, monkeypatch):
    root, _ = seeded

    def denied(*_a, **_k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(ag, "_write_atomic", denied)
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    assert r.status_code == 422
    assert "Permission denied" in r.text


async def test_summary_never_writes_to_the_request_log(desktop_app, seeded, db_session):
    from sqlalchemy import event

    root, _ = seeded
    root_id = await _key_id(db_session, "default")
    db_session.add(_log(root_id, 100, datetime.now(timezone.utc) - timedelta(minutes=1)))
    await db_session.commit()
    updates = []

    def count(_conn, _cursor, statement, *_a):
        if statement.lstrip().upper().startswith("UPDATE REQUESTS_LOG"):
            updates.append(statement)

    sync_engine = db_session.bind.sync_engine if hasattr(db_session.bind, "sync_engine") else db_session.bind
    event.listen(sync_engine, "before_cursor_execute", count)
    try:
        async with _client(desktop_app) as c:
            await c.get("/v1/app/summary", headers=_auth(root))
            await c.get("/v1/app/settings", headers=_auth(root))
        await db_session.commit()
    finally:
        event.remove(sync_engine, "before_cursor_execute", count)
    assert updates == []


async def test_agent_keys_can_only_call_models(desktop_app, seeded, desktop_dirs, db_session, monkeypatch):
    from app.middleware.auth import AuthMiddleware
    from app.routes import keys as keys_routes
    from app.routes import models as models_routes

    root, _ = seeded
    home, _ = desktop_dirs
    desktop_app.include_router(keys_routes.router)
    desktop_app.include_router(models_routes.router)
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        agent_key = json.loads((home / ".claude" / "settings.json").read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
        mint = await c.post("/v1/keys", headers=_auth(agent_key), json={"name": "escalate"})
        listing = await c.get("/v1/keys", headers=_auth(agent_key))
        models = await c.get("/v1/models", headers=_auth(agent_key))
    assert mint.status_code == 403
    assert listing.status_code == 403
    assert models.status_code == 200
    assert AuthMiddleware  # imported for clarity: the rule lives in the middleware


async def test_desktop_mode_on_a_network_host_does_not_mount_the_app_api(monkeypatch, db_session, seeded):
    root, _ = seeded
    monkeypatch.setenv("HOST", "0.0.0.0")
    app = await _create_app(monkeypatch, db_session, desktop=True)
    async with _client(app) as c:
        r = await c.get("/v1/app/settings", headers=_auth(root))
    assert r.status_code == 404


async def test_docs_are_off_in_desktop_mode(monkeypatch, db_session, seeded):
    monkeypatch.setenv("HOST", "127.0.0.1")
    app = await _create_app(monkeypatch, db_session, desktop=True)
    async with _client(app) as c:
        assert (await c.get("/docs")).status_code == 404
        assert (await c.get("/openapi.json")).status_code == 404


async def test_identity_proves_the_engine_holds_the_instance_secret(monkeypatch, db_session, seeded):
    import hashlib
    import hmac

    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("ORCA_INSTANCE_SECRET", "s3cret")
    app = await _create_app(monkeypatch, db_session, desktop=True)
    async with _client(app) as c:
        r = await c.get("/health/identity", params={"challenge": "abc123abc123abc123abc123"})
    assert r.status_code == 200
    expected = hmac.new(b"s3cret", b"abc123abc123abc123abc123", hashlib.sha256).hexdigest()
    assert r.json()["proof"] == expected


# ── team gateway ────────────────────────────────────────────────────────


async def test_join_gateway_points_agents_at_it(desktop_app, seeded, desktop_dirs, monkeypatch):
    from packages.desktop import gateway as gw

    root, _ = seeded
    home, _ = desktop_dirs
    checked = []
    monkeypatch.setattr(gw, "verify", lambda url, key, **kw: checked.append((url, key)))
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/gateway", headers=_auth(root),
                         json={"url": "https://gw.example.com/", "key": "sk-orca-team"})
        summary = (await c.get("/v1/app/summary", headers=_auth(root))).json()
    assert r.status_code == 200, r.text
    assert checked == [("https://gw.example.com", "sk-orca-team")]
    env = json.loads((home / ".claude" / "settings.json").read_text())["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://gw.example.com"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-orca-team"
    assert summary["gateway"] == {"url": "https://gw.example.com"}
    assert "sk-orca-team" not in r.text  # the team key is never echoed back


async def test_join_gateway_with_a_bad_key_changes_nothing(desktop_app, seeded, desktop_dirs, monkeypatch):
    from packages.desktop import gateway as gw

    root, _ = seeded
    home, _ = desktop_dirs

    def bad(url, key, **kw):
        raise gw.GatewayError("The gateway didn't accept that key.")

    monkeypatch.setattr(gw, "verify", bad)
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/gateway", headers=_auth(root), json={"url": "https://gw.example.com", "key": "x"})
    assert r.status_code == 422
    assert "didn't accept" in r.text
    assert not (home / ".claude" / "settings.json").exists()


async def test_leave_gateway_restores_agents(desktop_app, seeded, desktop_dirs, monkeypatch):
    from packages.desktop import gateway as gw

    root, _ = seeded
    home, _ = desktop_dirs
    monkeypatch.setattr(gw, "verify", lambda url, key, **kw: None)
    async with _client(desktop_app) as c:
        await c.post("/v1/app/gateway", headers=_auth(root), json={"url": "https://gw.example.com", "key": "k"})
        r = await c.delete("/v1/app/gateway", headers=_auth(root))
        summary = (await c.get("/v1/app/summary", headers=_auth(root))).json()
    assert r.status_code == 200
    assert not (home / ".claude" / "settings.json").exists()
    assert summary["gateway"] is None


async def test_summary_reports_an_available_update(desktop_app, seeded, monkeypatch):
    from packages.desktop import updates

    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/summary", headers=_auth(root))
        assert r.json()["update"] is None
        release = {"version": "9.0.0", "url": "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/tag/v9.0.0"}
        monkeypatch.setattr(updates.CHECKER, "latest", release)
        r = await c.get("/v1/app/summary", headers=_auth(root))
    assert r.json()["update"] == release


async def test_disconnect_all_restores_every_agent_and_revokes_their_keys(desktop_app, seeded, desktop_dirs, db_session):
    from packages.auth.key_validator import AuthError, validate_api_key

    root, _ = seeded
    home, _state = desktop_dirs
    (home / ".claude").mkdir(exist_ok=True)
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        manual = (await c.post("/v1/app/agents/cursor/connect", headers=_auth(root))).json()
        claude_key = json.loads((home / ".claude" / "settings.json").read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
        r = await c.post("/v1/app/agents/disconnect-all", headers=_auth(root))
        assert r.status_code == 200, r.text
        assert sorted(r.json()["disconnected"]) == ["Claude Code", "Cursor"]
        agents = (await c.get("/v1/app/agents", headers=_auth(root))).json()["agents"]
    assert not any(a["connected"] for a in agents)
    assert not (home / ".claude" / "settings.json").exists()
    for key in (claude_key, manual["api_key"]):
        with pytest.raises(AuthError):
            await validate_api_key(key, db_session)


async def test_disconnect_all_with_nothing_connected_is_fine(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/agents/disconnect-all", headers=_auth(root))
    assert r.status_code == 200 and r.json() == {"disconnected": [], "failed": []}
