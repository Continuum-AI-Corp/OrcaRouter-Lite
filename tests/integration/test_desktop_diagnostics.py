"""GET /v1/app/diagnostics (D8): a report safe to paste into a GitHub issue."""

from __future__ import annotations

import json

from tests.integration.test_desktop_agent_test import _call, app_engine  # noqa: F401

PROMPT = "please refactor the pelican tracking module"


async def test_report_after_real_requests_has_no_key_prompt_or_home_path(app_engine, monkeypatch):
    from app import config

    provider_key = "sk-proj-UpstreamProviderKey0123456789abc"
    monkeypatch.setenv("OPENAI_API_KEY", provider_key)
    config.get_settings.cache_clear()
    await _call(app_engine, "POST", "/v1/app/agents/claude-code/connect")
    agent_key = json.loads((app_engine.home / ".claude/settings.json").read_text())["env"]["ANTHROPIC_AUTH_TOKEN"]
    for _ in range(2):
        r = await app_engine.chat(agent_key, {"model": "auto", "messages": [{"role": "user", "content": PROMPT}]})
        assert r.status_code == 200, r.text
    await _call(app_engine, "POST", "/v1/app/agents/claude-code/test")

    # What an engine log can hold: keys in errors, paths, a request body.
    home = str(app_engine.home)
    log = app_engine.home.parent / "engine.log"  # the Orca folder (state dir's parent)
    log.write_text("\n".join([
        "INFO:     Uvicorn running on http://127.0.0.1:8765",
        f"warning upstream_error error='Incorrect API key provided: {provider_key}'",
        f"auth failed for Bearer {agent_key}",
        f"reading {home}/.claude/settings.json",
        f'debug body={{"messages": [{{"role": "user", "content": "{PROMPT}"}}]}}',
        f"{app_engine.app_key} used by desktop app",
    ]) + "\n")

    text = (await _call(app_engine, "GET", "/v1/app/diagnostics"))["text"]
    config.get_settings.cache_clear()
    for secret in (provider_key, agent_key, app_engine.app_key, "pelican", home):
        assert secret not in text, secret
    assert "claude-code" in text and "test ok" in text
    assert "openai" in text
    assert "~/.claude/settings.json" in text
    assert "sk-…" in text
    assert "Uvicorn running" in text
