"""POST /v1/app/agents/{id}/test (D4): one tiny request through the agent's own
config, answered by the engine itself and attributed to the agent."""

from __future__ import annotations

import json

import httpx
import pytest

from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, own

BASE = "http://127.0.0.1:8765"


@pytest.fixture
async def app_engine(engine, tmp_path):
    """The routing harness engine, plus the desktop app's key, a home folder
    and agent test requests delivered to the engine in-process."""
    from app.routes import desktop
    from packages.auth.hashing import generate_api_key
    from packages.db.models.api_key import ApiKey

    full, h, prefix = generate_api_key()
    async with engine.factory() as s:
        s.add(ApiKey(workspace_id="default", name="desktop-app", key_hash=h, key_prefix=prefix))
        await s.commit()
    home, state = tmp_path / "home", tmp_path / "state"
    for d in (".claude", ".codex", ".gemini", ".config/opencode"):
        (home / d).mkdir(parents=True)
    state.mkdir()
    engine.app.dependency_overrides[desktop.get_desktop_context] = lambda: desktop.DesktopContext(
        home=home, state_dir=state, base_url=BASE, which=lambda _n: None)
    engine.app.dependency_overrides[desktop.get_agent_test_transport] = lambda: httpx.ASGITransport(app=engine.app)
    engine.router = FakeRouter(own("openai", "gpt-4o-mini", "gpt-4.1"))
    engine.app_key, engine.home = full, home
    yield engine
    engine.app.dependency_overrides.clear()


async def _call(engine, method, path):
    async with engine.client(engine.app_key) as c:
        r = await c.request(method, path)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("agent_id,config", [
    ("claude-code", "~/.claude/settings.json"),
    ("codex", "~/.codex/config.toml"),
    ("gemini-cli", "~/.gemini/.env"),
    ("opencode", "~/.config/opencode/opencode.json"),
])
async def test_a_connected_agent_passes_and_the_request_is_its_own(app_engine, agent_id, config):
    from packages.db.models.api_key import ApiKey

    await _call(app_engine, "POST", f"/v1/app/agents/{agent_id}/connect")
    result = await _call(app_engine, "POST", f"/v1/app/agents/{agent_id}/test")
    assert result == {"ok": True, "model": result["model"], "seconds": result["seconds"], "config_path": config,
                      "error": None}
    assert result["model"] in ("gpt-4o-mini", "gpt-4.1")
    assert isinstance(result["seconds"], float)
    call = app_engine.router.calls[-1]
    assert call.get("max_tokens") == 1 or call.get("max_completion_tokens") == 1
    log = await app_engine.last_log()
    async with app_engine.factory() as s:
        key = await s.get(ApiKey, log.api_key_id)
    assert key.name == f"agent:{agent_id}"


async def test_a_provider_rejecting_its_key(app_engine):
    app_engine.router.failing["openai"] = UpstreamProviderError("bad key", http_status=503,
                                                                error_type="upstream_auth_error")
    await _call(app_engine, "POST", "/v1/app/agents/claude-code/connect")
    result = await _call(app_engine, "POST", "/v1/app/agents/claude-code/test")
    assert result["ok"] is False
    assert result["error"] == "OpenAI rejected the key (401). Replace it in Providers, then test again."


async def test_a_provider_that_is_down(app_engine):
    app_engine.router.failing["openai"] = UpstreamProviderError("down", http_status=503, error_type="upstream_error")
    await _call(app_engine, "POST", "/v1/app/agents/opencode/connect")
    result = await _call(app_engine, "POST", "/v1/app/agents/opencode/test")
    assert result["ok"] is False
    assert result["error"].startswith("OpenAI isn't answering right now")


async def test_a_broken_agent_key(app_engine):
    # The config still holds the key Orca wrote, but the engine no longer
    # accepts it (revoked, or the Orca folder was reset).
    from datetime import datetime, timezone

    from sqlalchemy import update

    from packages.db.models.api_key import ApiKey

    await _call(app_engine, "POST", "/v1/app/agents/codex/connect")
    async with app_engine.factory() as s:
        await s.execute(update(ApiKey).where(ApiKey.name == "agent:codex")
                        .values(is_active=False, revoked_at=datetime.now(timezone.utc)))
        await s.commit()
    result = await _call(app_engine, "POST", "/v1/app/agents/codex/test")
    assert result["ok"] is False
    assert result["error"] == "Orca didn't accept Codex's key. Connect Codex again, then test."


async def test_orca_unreachable(app_engine):
    from app.routes import desktop

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    app_engine.app.dependency_overrides[desktop.get_agent_test_transport] = lambda: httpx.MockTransport(refuse)
    await _call(app_engine, "POST", "/v1/app/agents/claude-code/connect")
    result = await _call(app_engine, "POST", "/v1/app/agents/claude-code/test")
    assert result["error"] == f"Orca isn't reachable at {BASE}."


async def test_a_changed_agent_is_not_sent_anywhere(app_engine):
    await _call(app_engine, "POST", "/v1/app/agents/claude-code/connect")
    (app_engine.home / ".claude/settings.json").write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://x.test"}}))
    calls = len(app_engine.router.calls)
    result = await _call(app_engine, "POST", "/v1/app/agents/claude-code/test")
    assert result["ok"] is False and "Reconnect Claude Code" in result["error"]
    assert len(app_engine.router.calls) == calls


async def test_not_connected(app_engine):
    result = await _call(app_engine, "POST", "/v1/app/agents/claude-code/test")
    assert result["ok"] is False and result["error"] == "Claude Code isn't connected to Orca. Connect it, then test."


async def test_manual_agent(app_engine):
    await _call(app_engine, "POST", "/v1/app/agents/cursor/connect")
    result = await _call(app_engine, "POST", "/v1/app/agents/cursor/test")
    assert result == {"ok": None, "model": None, "seconds": None, "config_path": None,
                      "error": "Paste the key into Cursor, then test from the agent."}


async def test_unknown_agent(app_engine):
    async with app_engine.client(app_engine.app_key) as c:
        assert (await c.post("/v1/app/agents/notepad/test")).status_code == 404
