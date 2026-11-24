"""P2 · D1 through the chat engine: with the "local_first" strategy a
request that fits a local model is answered on this computer at $0, and
the cloud takes over for what doesn't fit or when the local model fails."""

from __future__ import annotations

import pytest

from packages.desktop import local_models as lm
from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, engine, local, own  # noqa: F401

CODER = lm.LocalModel(id="ollama/qwen3-coder:30b", runtime="ollama", name="qwen3-coder:30b",
                      api_base="http://127.0.0.1:11434", context=32768, tools=True, vision=False)
DEPS = [*local(CODER.id), *own("openai", "gpt-4o-mini", "gpt-4o")]
PING = {"model": "auto", "messages": [{"role": "user", "content": "ping"}]}


@pytest.fixture(autouse=True)
def _ollama_found():
    lm.remember([lm.Runtime("ollama", "Ollama", "127.0.0.1:11434", True, (CODER,))])
    yield
    lm.reset()


@pytest.mark.parametrize("stream", [False, True])
async def test_a_short_request_runs_locally_for_free(engine, stream):
    engine.router = FakeRouter(DEPS, strategy="local_first")
    r = await engine.chat(engine.root_key, PING, stream=stream)
    assert r.status_code == 200
    call = engine.router.calls[-1]
    assert call["model"] == CODER.id
    assert "gpt-4o-mini" in call["fallbacks"][0][CODER.id]
    log = await engine.last_log()
    assert (log.provider, log.route_note, log.cost_microcents) == ("local", "local", 0)
    assert log.input_tokens > 0  # so "saved" can be priced at the baseline model


async def test_images_go_to_the_cloud(engine):
    engine.router = FakeRouter(DEPS, strategy="local_first")
    body = {"model": "auto", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]}
    await engine.chat(engine.root_key, body)
    assert engine.router.calls[-1]["model"] in {"gpt-4o", "gpt-4o-mini"}


async def test_a_long_prompt_goes_to_the_cloud(engine):
    engine.router = FakeRouter(DEPS, strategy="local_first")
    body = {"model": "auto", "messages": [{"role": "user", "content": "x" * 4 * 30_000}]}
    await engine.chat(engine.root_key, body)
    assert engine.router.calls[-1]["model"] == "gpt-4o-mini"


@pytest.mark.parametrize("stream", [False, True])
async def test_the_cloud_answers_when_the_local_model_fails(engine, stream):
    engine.router = FakeRouter(DEPS, strategy="local_first")
    engine.router.failing["local"] = UpstreamProviderError("refused", http_status=503, error_type="upstream_error")
    r = await engine.chat(engine.root_key, PING, stream=stream)
    assert r.status_code == 200
    log = await engine.last_log()
    assert (log.provider, log.route_note, log.fallback_level) == ("openai", None, 1)


async def test_other_strategies_leave_local_models_alone(engine):
    engine.router = FakeRouter(DEPS, strategy="cheapest")
    await engine.chat(engine.root_key, PING)
    assert engine.router.calls[-1]["model"] == "gpt-4o-mini"


async def test_a_pinned_local_model_is_used_under_any_strategy(engine):
    engine.router = FakeRouter(DEPS, strategy="balanced")
    r = await engine.chat(engine.root_key, {**PING, "model": CODER.id})
    assert r.status_code == 200
    assert (await engine.last_log()).route_note == "local"


async def test_local_first_is_a_routing_strategy(engine):
    async with engine.client(engine.root_key) as c:
        r = await c.put("/v1/routing", json={"strategy": "local_first"})
        assert r.status_code == 200, r.text
        assert (await c.get("/v1/routing")).json()["strategy"] == "local_first"
