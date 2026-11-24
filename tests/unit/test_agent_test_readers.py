"""D4: read each agent's config the way the agent does (packages.desktop.agent_test)."""

from __future__ import annotations

import json

import httpx
import pytest

from packages.desktop import agent_test as at
from packages.desktop import agents as ag

BASE = "http://127.0.0.1:8765"
KEY = "sk-orca-0123456789abcdef0123456789abcdef"
PROTOCOL = {"claude-code": "anthropic", "codex": "responses", "gemini-cli": "gemini"}


@pytest.fixture
def dirs(tmp_path):
    home, state = tmp_path / "home", tmp_path / "state"
    home.mkdir()
    state.mkdir()
    return home, state


def _auto_agents():
    return [a for a, spec in ag.AGENTS.items() if spec.setup == "auto"]


@pytest.mark.parametrize("agent_id", _auto_agents())
def test_every_automatic_agent_reads_back_what_connect_wrote(dirs, agent_id):
    home, state = dirs
    ag.connect_agent(agent_id, home=home, state_dir=state, base_url=BASE, api_key=KEY)
    ep = at.read_endpoint(agent_id, home=home, state_dir=state)
    assert ep.key == KEY
    assert ep.base_url.startswith(BASE)
    assert ep.protocol == PROTOCOL.get(agent_id, "chat")
    assert ep.model
    assert ep.config_path.exists() and home in ep.config_path.parents


def test_display_path_uses_tilde(dirs):
    home, state = dirs
    ag.connect_agent("claude-code", home=home, state_dir=state, base_url=BASE, api_key=KEY)
    ep = at.read_endpoint("claude-code", home=home, state_dir=state)
    assert at.display_path(ep.config_path, home) == "~/.claude/settings.json"


def test_missing_settings_say_which_file(dirs):
    home, state = dirs
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text("{}")
    with pytest.raises(at.ConfigError) as e:
        at.read_endpoint("claude-code", home=home, state_dir=state)
    assert "~/.claude/settings.json" in str(e.value)


def test_a_key_file_outside_orcas_folder_is_never_read(dirs):
    home, state = dirs
    ag.connect_agent("opencode", home=home, state_dir=state, base_url=BASE, api_key=KEY)
    cfg = home / ".config/opencode/opencode.json"
    data = json.loads(cfg.read_text())
    secret = home / "secret.txt"
    secret.write_text("not-for-sending")
    data["provider"]["orca"]["options"]["apiKey"] = f"{{file:{secret}}}"
    cfg.write_text(json.dumps(data))
    with pytest.raises(at.ConfigError):
        at.read_endpoint("opencode", home=home, state_dir=state)


def test_a_command_other_than_reading_orcas_key_file_is_never_run(dirs, tmp_path):
    home, state = dirs
    ag.connect_agent("command-code", home=home, state_dir=state, base_url=BASE, api_key=KEY)
    cfg = home / ".commandcode/providers.json"
    data = json.loads(cfg.read_text())
    marker = tmp_path / "ran"
    data["provider"]["orca"]["apiKey"] = f"!touch {marker}"
    cfg.write_text(json.dumps(data))
    with pytest.raises(at.ConfigError):
        at.read_endpoint("command-code", home=home, state_dir=state)
    assert not marker.exists()


# ── the request itself ──────────────────────────────────────────────────


def _endpoint(protocol, base="http://127.0.0.1:8765"):
    from pathlib import Path

    return at.Endpoint(protocol=protocol, base_url=base, key=KEY, model="auto", config_path=Path("/x"))


@pytest.mark.parametrize("protocol,path", [
    ("anthropic", "/v1/messages"), ("responses", "/v1/responses"),
    ("gemini", "/v1beta/models/auto:generateContent"), ("chat", "/v1/chat/completions"),
])
async def test_one_tiny_request_in_the_agents_protocol(protocol, path):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json={"model": "gpt-4.1"}, headers={"x-orca-resolved-model": "gpt-4.1-mini"})

    base = "http://127.0.0.1:8765/v1" if protocol in ("responses", "chat") else "http://127.0.0.1:8765"
    result = await at.send(_endpoint(protocol, base), transport=httpx.MockTransport(handler))
    assert result.ok and result.model == "gpt-4.1-mini" and result.seconds is not None
    req = seen[0]
    assert req.url.path == path
    body = json.loads(req.content)
    if protocol == "gemini":
        assert req.headers["x-goog-api-key"] == KEY
        assert body["generationConfig"]["maxOutputTokens"] == 1
    else:
        assert req.headers["authorization"] == f"Bearer {KEY}"
        assert body.get("max_tokens", body.get("max_output_tokens")) == 1


async def test_unreachable_engine():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    result = await at.send(_endpoint("chat"), transport=httpx.MockTransport(handler))
    assert result.ok is False and result.status is None
    assert at.explain(result, agent_name="Aider", base_url="http://127.0.0.1:8765") == (
        "Orca isn't reachable at http://127.0.0.1:8765."
    )


@pytest.mark.parametrize("status,error_type,provider,expected", [
    (500, "upstream_auth_error", "google", "Google Gemini rejected the key (401). Replace it in Setup, then test again."),
    (503, "upstream_error", "openai", "OpenAI isn't answering right now (503). Try again in a minute, or add another provider."),
    (429, "rate_limit_error", "anthropic", "Anthropic is limiting requests right now (429). Try again in a minute, or add another provider."),
])
def test_upstream_errors_in_plain_words(status, error_type, provider, expected):
    result = at.TestResult(ok=False, status=status, detail="Upstream provider error: boom")
    log = at.FailedRow(provider=provider, error_type=error_type, status=status)
    assert at.explain(result, agent_name="Gemini CLI", base_url="x", failed=log) == expected


def test_a_rejected_agent_key():
    result = at.TestResult(ok=False, status=401, detail="Invalid API key")
    assert at.explain(result, agent_name="Codex", base_url="x") == (
        "Orca didn't accept Codex's key. Connect Codex again, then test."
    )


def test_other_engine_messages_pass_through():
    detail = "Today's budget for Codex ($5.00) is used up, so Orca paused it. Raise it in Orca."
    result = at.TestResult(ok=False, status=429, detail=detail)
    assert at.explain(result, agent_name="Codex", base_url="x") == detail
