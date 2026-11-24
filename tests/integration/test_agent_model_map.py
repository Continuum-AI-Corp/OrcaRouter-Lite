"""D2: a per-agent model map, applied by the engine to that agent's key.

Claude Code's main requests can go to one model and its background ones
(titles, summaries: the small haiku-style names) to a cheap one, without
touching its config file. The response headers say what was asked for and
what answered; the request log says the map chose it.
"""

from __future__ import annotations

import pytest

from tests.integration.routing_harness import FakeRouter, own

DEPS = [*own("anthropic", "claude-sonnet-4-6", "claude-haiku-4-5"), *own("openai", "gpt-4.1", "gpt-4o-mini")]
MAIN = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "ping"}]}
BACKGROUND = {**MAIN, "model": "claude-haiku-4-5-20251001"}


async def _map(engine, agent="claude-code", **m):
    await engine.settings(agent_models={agent: {"fallback_to_auto": True, **m}})


@pytest.mark.parametrize("stream", [False, True])
async def test_main_requests_use_the_main_model(engine, stream):
    engine.router = FakeRouter(DEPS)
    await _map(engine, main="gpt-4.1")
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, MAIN, stream=stream)
    assert r.status_code == 200
    assert engine.router.calls[-1]["model"] == "gpt-4.1"
    assert (r.headers["x-orca-requested-model"], r.headers["x-orca-resolved-model"]) == ("claude-sonnet-4-6", "gpt-4.1")
    log = await engine.last_log()
    assert (log.route_note, log.model_requested, log.model_resolved) == ("mapped", "claude-sonnet-4-6", "gpt-4.1")
    assert log.cost_microcents > 0


@pytest.mark.parametrize("asked", ["claude-haiku-4-5-20251001", "gpt-5-mini", "gpt-5.4-nano", "gemini-2.5-flash-lite"])
async def test_background_requests_use_the_background_model(engine, asked):
    engine.router = FakeRouter(DEPS)
    await _map(engine, main="claude-sonnet-4-6", background="gpt-4.1")
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, {**MAIN, "model": asked})
    assert r.status_code == 200
    assert engine.router.calls[-1]["model"] == "gpt-4.1"


async def test_without_a_background_model_background_requests_keep_theirs(engine):
    engine.router = FakeRouter(DEPS)
    await _map(engine, main="gpt-4.1")
    key = await engine.agent_key("claude-code")
    await engine.chat(key, {**MAIN, "model": "claude-haiku-4-5"})
    assert engine.router.calls[-1]["model"] == "claude-haiku-4-5"
    assert (await engine.last_log()).route_note is None


async def test_an_unavailable_mapped_model_routes_as_auto_when_allowed(engine):
    engine.router = FakeRouter(DEPS)
    await _map(engine, main="kimi-k2.6", fallback_to_auto=True)
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, MAIN)
    assert r.status_code == 200
    assert engine.router.calls[-1]["model"] in {"claude-sonnet-4-6", "claude-haiku-4-5", "gpt-4.1", "gpt-4o-mini"}
    assert (await engine.last_log()).route_note == "mapped"


async def test_an_unavailable_mapped_model_is_refused_otherwise(engine):
    engine.router = FakeRouter(DEPS)
    await _map(engine, main="kimi-k2.6", fallback_to_auto=False)
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, MAIN)
    assert r.status_code == 422
    assert r.headers["x-orca-error-type"] == "mapped_model_unavailable"
    assert "kimi-k2.6" in r.json()["error"]["message"]
    assert engine.router.calls == []


async def test_a_map_to_auto_routes_as_auto(engine):
    engine.router = FakeRouter(DEPS, strategy="cheapest")
    await _map(engine, main="auto")
    key = await engine.agent_key("claude-code")
    await engine.chat(key, MAIN)
    assert engine.router.calls[-1]["model"] == "gpt-4o-mini"  # cheapest


async def test_other_agents_and_keys_are_not_mapped(engine):
    engine.router = FakeRouter(DEPS)
    await _map(engine, main="gpt-4.1")
    codex = await engine.agent_key("codex")
    await engine.chat(codex, MAIN)
    assert engine.router.calls[-1]["model"] == "claude-sonnet-4-6"
    await engine.chat(engine.root_key, MAIN)
    assert engine.router.calls[-1]["model"] == "claude-sonnet-4-6"


async def test_claude_code_protocol_with_a_map(engine):
    engine.router = FakeRouter(DEPS)
    await _map(engine, main="gpt-4.1")
    key = await engine.agent_key("claude-code")
    async with engine.client(key) as c:
        r = await c.post("/v1/messages", headers={"anthropic-version": "2023-06-01"},
                         json={"model": "claude-sonnet-4-6", "max_tokens": 8,
                               "messages": [{"role": "user", "content": "ping"}]})
    assert r.status_code == 200, r.text
    assert r.headers["x-orca-resolved-model"] == "gpt-4.1"
    assert r.headers["x-orca-requested-model"] == "claude-sonnet-4-6"


async def test_codex_protocol_with_a_map(engine):
    engine.router = FakeRouter(DEPS)
    await _map(engine, agent="codex", main="claude-sonnet-4-6")
    key = await engine.agent_key("codex")
    async with engine.client(key) as c:
        r = await c.post("/v1/responses", json={"model": "gpt-5.1-codex", "input": "ping"})
    assert r.status_code == 200, r.text
    assert engine.router.calls[-1]["model"] == "claude-sonnet-4-6"
    assert (await engine.last_log()).route_note == "mapped"


async def test_gemini_cli_protocol_with_a_map(engine):
    engine.router = FakeRouter(DEPS)
    await _map(engine, agent="gemini-cli", main="gpt-4.1")
    key = await engine.agent_key("gemini-cli")
    async with engine.client(key) as c:
        r = await c.post("/v1beta/models/gemini-2.5-pro:generateContent",
                         json={"contents": [{"role": "user", "parts": [{"text": "ping"}]}]})
    assert r.status_code == 200, r.text
    assert engine.router.calls[-1]["model"] == "gpt-4.1"
