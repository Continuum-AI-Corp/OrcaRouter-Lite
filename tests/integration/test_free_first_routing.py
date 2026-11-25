"""H0 through the chat engine (desktop mode): with only an OrcaRouter key in
"free" mode, ordinary requests are served by free models at $0; a request
only a paid model could serve is refused with needs_paid_model (never sent
to a paid model by surprise); "all" restores normal hosted routing."""

from __future__ import annotations

import pytest

from tests.integration.routing_harness import FakeRouter, hosted, own

FREE_DEPS = hosted("z-ai/glm-5.3-flash-free", "deepseek/deepseek-v4-flash-free",
                   "deepseek/deepseek-v4.1-flash-free", "orcarouter/free")
PAID_DEPS = hosted("claude-sonnet-4.6", "gpt-5.5", "qwen3-vl-235b-a22b-instruct")
PING = {"model": "auto", "messages": [{"role": "user", "content": "ping"}]}
IMAGE = {"model": "auto", "messages": [{"role": "user", "content": [
    {"type": "text", "text": "what is this"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}]}
NEEDS_PAID = ("This request needs a paid model (images). Open Orca and choose \"Use paid models\" "
              "to allow OrcaRouter's paid models.")


@pytest.mark.parametrize("stream", [False, True])
async def test_free_models_serve_ordinary_requests_at_no_cost(engine, stream):
    engine.router = FakeRouter(FREE_DEPS)
    r = await engine.chat(engine.root_key, PING, stream=stream)
    assert r.status_code == 200
    call = engine.router.calls[-1]
    assert call["model"] == "z-ai/glm-5.3-flash-free"
    assert set(call["fallbacks"][0][call["model"]]) <= {d.model_name for d in FREE_DEPS}
    log = await engine.last_log()
    assert (log.route_note, log.cost_microcents, log.provider) == ("free", 0, "orcarouter")


@pytest.mark.parametrize("stream", [False, True])
async def test_free_models_rank_first_and_own_keys_follow(engine, stream):
    engine.router = FakeRouter([*FREE_DEPS, *own("openai", "gpt-4o-mini", "gpt-4.1")])
    engine.router.failing["orcarouter"] = RuntimeError("down")
    r = await engine.chat(engine.root_key, PING, stream=stream)
    assert r.status_code == 200
    call = engine.router.calls[-1]
    assert call["model"] == "z-ai/glm-5.3-flash-free"
    assert set(call["fallbacks"][0][call["model"]]) & {"gpt-4o-mini", "gpt-4.1"}
    log = await engine.last_log()
    assert log.provider == "openai" and log.route_note is None and log.cost_microcents > 0


@pytest.mark.parametrize("stream", [False, True])
async def test_an_image_request_needs_a_paid_model(engine, stream):
    engine.router = FakeRouter(FREE_DEPS)
    r = await engine.chat(engine.root_key, IMAGE, stream=stream)
    assert r.status_code == 422, r.text
    assert r.headers.get("x-orca-error-type") == "needs_paid_model", r.text
    assert r.json()["error"]["message"] == NEEDS_PAID
    assert engine.router.calls == []  # nothing was sent anywhere
    log = await engine.last_log()
    assert (log.route_note, log.status_code) == ("needs_paid", 422)


async def test_a_very_long_prompt_needs_a_paid_model(engine):
    engine.router = FakeRouter(FREE_DEPS)
    long = {"model": "auto", "messages": [{"role": "user", "content": "word " * 700_000}]}
    r = await engine.chat(engine.root_key, long)
    assert r.status_code == 422 and "(very long context)" in r.json()["error"]["message"]


async def test_an_own_key_that_can_serve_it_is_used_instead(engine):
    engine.router = FakeRouter([*FREE_DEPS, *own("openai", "gpt-4o")])
    r = await engine.chat(engine.root_key, IMAGE)
    assert r.status_code == 200
    assert engine.router.calls[-1]["model"] == "gpt-4o"


async def test_pinning_a_paid_hosted_model_needs_paid_models(engine):
    engine.router = FakeRouter(FREE_DEPS)
    r = await engine.chat(engine.root_key, {**PING, "model": "claude-sonnet-4.6"})
    assert r.status_code == 422, r.text
    assert r.headers.get("x-orca-error-type") == "needs_paid_model", r.text
    assert "claude-sonnet-4.6" in r.json()["error"]["message"]
    assert engine.router.calls == []


async def test_an_agent_asking_for_a_paid_model_gets_a_free_one(engine):
    engine.router = FakeRouter(FREE_DEPS)
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, {**PING, "model": "claude-sonnet-4-6"})
    assert r.status_code == 200
    assert r.headers["x-orca-requested-model"] == "claude-sonnet-4-6"
    assert r.headers["x-orca-resolved-model"] == "z-ai/glm-5.3-flash-free"
    log = await engine.last_log()
    assert (log.route_note, log.cost_microcents) == ("free", 0)


async def test_claude_code_sees_a_permission_error_it_will_not_retry(engine):
    engine.router = FakeRouter(FREE_DEPS)
    key = await engine.agent_key("claude-code")
    body = {"model": "claude-sonnet-4-6", "max_tokens": 64, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "what is this"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}]}]}
    async with engine.client(key) as c:
        r = await c.post("/v1/messages", json=body, headers={"anthropic-version": "2023-06-01"})
    assert r.status_code == 403, r.text
    assert r.json()["error"] == {"type": "permission_error", "message": NEEDS_PAID}
    assert (await engine.last_log()).route_note == "needs_paid"


async def test_all_mode_routes_images_to_a_paid_hosted_model(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*FREE_DEPS, *PAID_DEPS])
    r = await engine.chat(engine.root_key, IMAGE)
    assert r.status_code == 200
    assert engine.router.calls[-1]["model"] in {"claude-sonnet-4.6", "gpt-5.5", "qwen3-vl-235b-a22b-instruct"}
    assert (await engine.last_log()).route_note is None


async def test_servers_keep_strict_behaviour(engine, monkeypatch):
    # Outside the desktop app there is no "free" mode.
    from app import config

    monkeypatch.delenv("ORCA_DESKTOP_MODE")
    config.get_settings.cache_clear()
    engine.router = FakeRouter([*FREE_DEPS, *PAID_DEPS])
    r = await engine.chat(engine.root_key, IMAGE)
    assert r.status_code == 200
