"""P2 · D1 through the chat engine: with the "local_first" strategy a
request that fits a local model is answered on this computer at $0, and
the cloud takes over for what doesn't fit or when the local model fails."""

from __future__ import annotations

import pytest

from packages.desktop import local_models as lm
from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, local, own

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


# ── Issue 20/28: a model on this computer is never swapped for a cloud one ──

TINY = lm.LocalModel(id="ollama/qwen2.5:1.5b", runtime="ollama", name="qwen2.5:1.5b",
                     api_base="http://127.0.0.1:11434", context=32768, tools=False, vision=False)
GEMMA = lm.LocalModel(id="lmstudio/gemma-3-1b-it", runtime="lmstudio", name="gemma-3-1b-it",
                      api_base="http://127.0.0.1:1234", context=8192, tools=False, vision=False)
CLOUD = [*own("qwen", "qwen3.5-flash"), *own("google", "gemma-4-31b-it")]


def _found(*models, lmstudio_running=True):
    ollama = tuple(m for m in models if m.runtime == "ollama")
    studio = tuple(m for m in models if m.runtime == "lmstudio")
    lm.remember([
        lm.Runtime("ollama", "Ollama", "127.0.0.1:11434", True, ollama),
        lm.Runtime("lmstudio", "LM Studio", "127.0.0.1:1234", lmstudio_running, studio),
    ])


@pytest.mark.parametrize("asked", ["qwen2.5:1.5b", "Qwen2.5:1.5B"])
async def test_a_bare_runtime_name_is_served_by_that_local_model(engine, asked):
    _found(CODER, TINY)
    engine.router = FakeRouter([*local(TINY.id), *CLOUD])
    key = await engine.agent_key("opencode")
    r = await engine.chat(key, {**PING, "model": asked})
    assert r.status_code == 200, r.text
    assert engine.router.calls[-1]["model"] == TINY.id
    assert (await engine.last_log()).provider == "local"


async def test_ollama_latest_tag_is_optional(engine):
    latest = lm.LocalModel(id="ollama/llama3:latest", runtime="ollama", name="llama3:latest",
                           api_base="http://127.0.0.1:11434", context=8192, tools=True, vision=False)
    _found(latest)
    engine.router = FakeRouter([*local(latest.id), *CLOUD])
    r = await engine.chat(await engine.agent_key("opencode"), {**PING, "model": "llama3"})
    assert r.status_code == 200, r.text
    assert engine.router.calls[-1]["model"] == latest.id


@pytest.mark.parametrize("asked", ["qwen2.5:1.5b", "ollama/qwen2.5:1.5b"])
async def test_a_local_model_that_is_turned_off_is_refused_not_replaced(engine, asked):
    _found(CODER, TINY)  # found on this computer, but only CODER is deployed (turned on)
    engine.router = FakeRouter([*local(CODER.id), *CLOUD])
    r = await engine.chat(await engine.agent_key("opencode"), {**PING, "model": asked})
    assert r.status_code == 422, r.text
    assert r.headers["x-orca-error-type"] == "local_model_not_enabled"
    assert "isn't turned on" in r.text
    assert engine.router.calls == []


async def test_an_lmstudio_model_without_tools_is_not_swapped_for_a_cloud_gemma(engine):
    _found(GEMMA)
    engine.router = FakeRouter(CLOUD)
    r = await engine.chat(await engine.agent_key("opencode"), {**PING, "model": GEMMA.id})
    assert r.status_code == 422, r.text
    assert r.headers["x-orca-error-type"] == "local_model_not_enabled"
    assert engine.router.calls == []


async def test_a_prefixed_model_of_a_runtime_that_is_not_running_says_so(engine):
    _found(TINY, lmstudio_running=False)
    engine.router = FakeRouter([*local(TINY.id), *CLOUD])
    r = await engine.chat(await engine.agent_key("opencode"), {**PING, "model": "lmstudio/qwen2.5-1.5b-instruct"})
    assert r.status_code == 503, r.text
    assert r.headers["x-orca-error-type"] == "local_runtime_unavailable"
    assert "LM Studio isn't running at 127.0.0.1:1234" in r.text
    assert engine.router.calls == []


async def test_a_prefixed_model_the_running_runtime_does_not_list_says_so(engine):
    _found(TINY)
    engine.router = FakeRouter([*local(TINY.id), *CLOUD])
    r = await engine.chat(await engine.agent_key("opencode"), {**PING, "model": "ollama/nope:7b"})
    assert r.status_code == 422, r.text
    assert r.headers["x-orca-error-type"] == "model_not_found"
    assert "Ollama doesn't list nope:7b" in r.text


async def test_a_cloud_name_still_falls_back_as_before(engine):
    _found(TINY)
    engine.router = FakeRouter([*local(TINY.id), *CLOUD])
    r = await engine.chat(await engine.agent_key("opencode"), {**PING, "model": "qwen3.6-max"})
    assert r.status_code == 200, r.text
    assert engine.router.calls[-1]["model"] == "qwen3.5-flash"


# ── Issue 30: a local runtime that stopped is reported as not running ──

def _runtime_down():
    return UpstreamProviderError("litellm.Timeout: Request timed out", http_status=503,
                                 error_type="local_runtime_unavailable", deployment_id=f"local::{CODER.id}")


@pytest.mark.parametrize("stream", [False, True])
async def test_a_stopped_runtime_is_reported_as_not_running(engine, stream):
    engine.router = FakeRouter(DEPS, strategy="balanced")
    engine.router.failing["local"] = _runtime_down()
    r = await engine.chat(engine.root_key, {**PING, "model": CODER.id}, stream=stream)
    assert r.status_code == 503, r.text
    assert r.headers["x-orca-error-type"] == "local_runtime_unavailable"
    assert "Ollama isn't running at 127.0.0.1:11434" in r.text
    assert "timed out" not in r.text
    # the panel re-probes instead of showing Ollama as running for another 30 s
    assert lm._cache[0] == 0.0


async def test_a_stopped_runtime_is_a_bad_request_for_claude_code(engine):
    engine.router = FakeRouter(DEPS, strategy="balanced")
    engine.router.failing["local"] = _runtime_down()
    body = {"model": CODER.id, "max_tokens": 16, "messages": [{"role": "user", "content": "ping"}]}
    async with engine.client(engine.root_key) as c:
        r = await c.post("/v1/messages", json=body)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"
    assert "Ollama isn't running" in r.json()["error"]["message"]


# ── Issue 18: the error names what every model in the chain said ──

async def test_the_error_lists_what_each_model_said(engine):
    engine.router = FakeRouter(DEPS, strategy="cheapest")
    err = UpstreamProviderError("No deployments available for selected model", http_status=503,
                                error_type="upstream_error")
    err.attempts_summary = "Every model tried failed. gpt-4o-mini: overloaded; gpt-4o: tool_choice not supported"
    engine.router.failing["openai"] = err
    engine.router.failing["local"] = err
    r = await engine.chat(engine.root_key, PING)
    assert r.status_code == 503
    assert "gpt-4o: tool_choice not supported" in r.text
    assert "No deployments available" not in r.text
