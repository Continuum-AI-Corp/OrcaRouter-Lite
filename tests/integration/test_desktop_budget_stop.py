"""Optional hard stop: with budget_mode "stop", coding agents are refused
(400, or 429 on the Anthropic surface, marked not to be retried) once
today's spend reaches the daily budget. "alert" (the default)
never blocks. Only agent keys are stopped, and only on generation calls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.test_desktop_api import (  # noqa: F401  (fixtures)
    _auth,
    _client,
    _key_id,
    _log,
    desktop_app,
    desktop_dirs,
    seeded,
)


@pytest.fixture
def app_with_models(desktop_app, monkeypatch):
    """The desktop API plus stand-in model endpoints, in desktop mode."""
    from fastapi import APIRouter

    from app import config
    from packages.desktop import budget

    monkeypatch.setenv("ORCA_DESKTOP_MODE", "1")
    monkeypatch.setenv("HOST", "127.0.0.1")
    config.get_settings.cache_clear()
    budget.reset_cache()
    stub = APIRouter()

    @stub.post("/v1/chat/completions")
    async def _chat():
        return {"ok": True}

    @stub.post("/v1/responses")
    async def _responses():
        return {"ok": True}

    @stub.post("/v1/messages/count_tokens")
    async def _count():
        return {"input_tokens": 1}

    @stub.get("/v1/models")
    async def _models():
        return {"data": []}

    desktop_app.include_router(stub)
    yield desktop_app
    config.get_settings.cache_clear()
    budget.reset_cache()


async def _agent_key(c, root, home):
    await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    return json.loads((home / ".claude" / "settings.json").read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]


async def _spend(db_session, microcents):
    root_id = await _key_id(db_session, "default")
    db_session.add(_log(root_id, microcents, datetime.now(timezone.utc) - timedelta(minutes=1)))
    await db_session.commit()


async def test_budget_mode_round_trips_and_defaults_to_alert(app_with_models, seeded):
    root, _ = seeded
    async with _client(app_with_models) as c:
        assert (await c.get("/v1/app/settings", headers=_auth(root))).json()["budget_mode"] == "alert"
        r = await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 100, "budget_mode": "stop"})
        assert r.status_code == 200
        assert (await c.get("/v1/app/settings", headers=_auth(root))).json()["budget_mode"] == "stop"
        bad = await c.put("/v1/app/settings", headers=_auth(root), json={"budget_mode": "panic"})
    assert bad.status_code == 422


async def test_stop_mode_refuses_agents_at_the_limit(app_with_models, seeded, desktop_dirs, db_session):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        agent = await _agent_key(c, root, home)
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 100, "budget_mode": "stop"})
        await _spend(db_session, 1_000_000)  # $1.00 == the $1.00 budget
        r = await c.post("/v1/chat/completions", headers=_auth(agent), json={})
        messages = await c.post("/v1/messages", headers=_auth(agent), json={})
        gemini = await c.post("/v1beta/models/gemini-2.5-flash:generateContent", headers=_auth(agent), json={})
    assert r.status_code == 400
    assert "daily budget" in r.text.lower()
    assert "$1.00" in r.text
    # Agents retry 429s on their own; each response tells them not to.
    for resp in (r, messages, gemini):
        assert resp.headers["x-should-retry"] == "false"
        assert 0 < int(resp.headers["retry-after"]) <= 25 * 3600
    assert messages.status_code == 429
    assert messages.json()["error"]["type"] == "rate_limit_error"
    assert gemini.status_code == 400
    assert gemini.json()["error"]["status"] == "FAILED_PRECONDITION"


async def test_alert_mode_never_blocks(app_with_models, seeded, desktop_dirs, db_session):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        agent = await _agent_key(c, root, home)
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 100, "budget_mode": "alert"})
        await _spend(db_session, 5_000_000)
        r = await c.post("/v1/chat/completions", headers=_auth(agent), json={})
    assert r.status_code == 200


async def test_stop_mode_under_the_limit_lets_agents_through(app_with_models, seeded, desktop_dirs, db_session):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        agent = await _agent_key(c, root, home)
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 100, "budget_mode": "stop"})
        await _spend(db_session, 990_000)
        r = await c.post("/v1/chat/completions", headers=_auth(agent), json={})
    assert r.status_code == 200


async def test_stop_mode_leaves_non_generation_calls_and_other_keys_alone(app_with_models, seeded, desktop_dirs,
                                                                         db_session):
    from packages.auth.hashing import generate_api_key
    from packages.db.models.api_key import ApiKey

    root, _ = seeded
    home, _ = desktop_dirs
    other, h, prefix = generate_api_key()
    db_session.add(ApiKey(workspace_id="default", name="my-script", key_hash=h, key_prefix=prefix))
    await db_session.commit()
    async with _client(app_with_models) as c:
        agent = await _agent_key(c, root, home)
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 100, "budget_mode": "stop"})
        await _spend(db_session, 5_000_000)
        models = await c.get("/v1/models", headers=_auth(agent))
        count = await c.post("/v1/messages/count_tokens", headers=_auth(agent), json={})
        script = await c.post("/v1/chat/completions", headers=_auth(other), json={})
    assert models.status_code == 200
    assert count.status_code == 200
    assert script.status_code == 200


async def test_agent_keys_may_call_the_responses_api(app_with_models, seeded, desktop_dirs):
    """Codex speaks only the Responses API: an agent key must reach
    /v1/responses (it is a model endpoint) while the app API stays closed."""
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        agent = await _agent_key(c, root, home)
        r = await c.post("/v1/responses", headers=_auth(agent), json={})
        app_api = await c.get("/v1/app/summary", headers=_auth(agent))
    assert r.status_code == 200
    assert app_api.status_code == 403


async def test_summary_reports_the_budget_mode(app_with_models, seeded):
    root, _ = seeded
    async with _client(app_with_models) as c:
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 100, "budget_mode": "stop"})
        r = await c.get("/v1/app/summary", headers=_auth(root))
    assert r.json()["budget"]["mode"] == "stop"
