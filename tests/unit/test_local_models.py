"""P2 · D1: finding the models running on this computer.

Ollama, LM Studio and llama.cpp's server are probed on their default ports
(or where their usual environment variables point), with a short timeout so
an absent runtime costs nothing. What they report (tools, vision, context
size) decides which requests a local model can take.
"""

from __future__ import annotations

import json

import httpx
import pytest

from packages.desktop import local_models as lm


@pytest.fixture(autouse=True)
def _fresh():
    lm.reset()
    yield
    lm.reset()


def _ollama_handler(req: httpx.Request) -> httpx.Response:
    if req.url.port != 11434:
        raise httpx.ConnectError("refused", request=req)
    if req.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen3-coder:30b"}, {"name": "llava:7b"},
                                                    {"name": "tiny:1b"}]})
    if req.url.path == "/api/show":
        name = json.loads(req.content)["model"]
        info = {
            "qwen3-coder:30b": (["completion", "tools"], {"qwen3moe.context_length": 262144}),
            "llava:7b": (["completion", "vision"], {"llama.context_length": 4096}),
            "tiny:1b": (["completion"], {}),
        }[name]
        return httpx.Response(200, json={"capabilities": info[0], "model_info": info[1]})
    return httpx.Response(404)


async def test_ollama_models_with_what_they_can_do():
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ollama_handler)) as c:
        runtimes = await lm.discover(client=c, env={})
    by_id = {r.id: r for r in runtimes}
    assert [r.id for r in runtimes] == ["ollama", "lmstudio", "llamacpp"]
    ollama = by_id["ollama"]
    assert (ollama.name, ollama.url, ollama.running) == ("Ollama", "127.0.0.1:11434", True)
    models = {m.id: m for m in ollama.models}
    coder = models["ollama/qwen3-coder:30b"]
    assert (coder.name, coder.tools, coder.vision, coder.context) == ("qwen3-coder:30b", True, False, 262144)
    assert models["ollama/llava:7b"].vision is True and models["ollama/llava:7b"].tools is False
    assert models["ollama/tiny:1b"].context is None
    assert by_id["lmstudio"].running is False and by_id["lmstudio"].models == ()
    assert by_id["llamacpp"].running is False


async def test_lm_studio_and_llama_cpp():
    def handler(req):
        if req.url.port == 1234 and req.url.path == "/api/v0/models":
            return httpx.Response(200, json={"data": [
                {"id": "qwen2.5-7b-instruct", "type": "llm", "max_context_length": 32768, "capabilities": ["tool_use"]},
                {"id": "gemma-3-4b", "type": "vlm", "max_context_length": 8192},
                {"id": "nomic-embed", "type": "embeddings"},
            ]})
        if req.url.port == 8080 and req.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gpt-oss-20b", "meta": {"n_ctx_train": 131072}}]})
        raise httpx.ConnectError("refused", request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        runtimes = {r.id: r for r in await lm.discover(client=c, env={})}
    studio = {m.id: m for m in runtimes["lmstudio"].models}
    assert set(studio) == {"lmstudio/qwen2.5-7b-instruct", "lmstudio/gemma-3-4b"}
    assert studio["lmstudio/qwen2.5-7b-instruct"].tools is True
    assert studio["lmstudio/qwen2.5-7b-instruct"].context == 32768
    assert studio["lmstudio/gemma-3-4b"].vision is True and studio["lmstudio/gemma-3-4b"].tools is False
    llama = runtimes["llamacpp"].models[0]
    assert (llama.id, llama.context, llama.tools, llama.api_base) == (
        "llamacpp/gpt-oss-20b", 131072, True, "http://127.0.0.1:8080")


async def test_lm_studio_without_its_rest_api_falls_back_to_the_openai_list():
    def handler(req):
        if req.url.port == 1234 and req.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "phi-4"}]})
        if req.url.port == 1234:
            return httpx.Response(404)
        raise httpx.ConnectError("refused", request=req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        runtimes = {r.id: r for r in await lm.discover(client=c, env={})}
    assert [m.id for m in runtimes["lmstudio"].models] == ["lmstudio/phi-4"]


async def test_hosts_come_from_the_usual_environment_variables():
    seen = set()

    def handler(req):
        seen.add(f"{req.url.host}:{req.url.port}")
        raise httpx.ConnectError("refused", request=req)

    env = {"OLLAMA_HOST": "0.0.0.0:11500", "LMSTUDIO_BASE_URL": "http://10.0.0.5:4321/v1",
           "LLAMACPP_BASE_URL": "http://localhost:9090"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        runtimes = {r.id: r for r in await lm.discover(client=c, env=env)}
    assert {"127.0.0.1:11500", "10.0.0.5:4321", "localhost:9090"} <= seen
    assert runtimes["ollama"].url == "127.0.0.1:11500"


async def test_results_are_cached_for_thirty_seconds():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return _ollama_handler(req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await lm.discover(client=c, env={})
        n = len(calls)
        await lm.discover(client=c, env={})
        assert len(calls) == n
        await lm.discover(client=c, env={}, force=True)
        assert len(calls) > n
    assert [m.id for m in lm.last_models()][:1] == ["ollama/qwen3-coder:30b"]


def _model(name, *, tools=True, vision=False, context=32768, runtime="ollama"):
    return lm.LocalModel(id=f"{runtime}/{name}", runtime=runtime, name=name,
                         api_base="http://127.0.0.1:11434", context=context, tools=tools, vision=vision)


def test_which_models_auto_may_use():
    models = [_model("a"), _model("b", tools=False), _model("c")]
    assert [m.id for m in lm.enabled(models, None)] == ["ollama/a", "ollama/c"]  # default: those with tools
    assert [m.id for m in lm.enabled(models, ["ollama/b"])] == ["ollama/b"]  # the user's choice


def test_deployments_cost_nothing_and_say_where_they_run():
    ollama = _model("qwen3-coder:30b")
    studio = lm.LocalModel(id="lmstudio/phi-4", runtime="lmstudio", name="phi-4", api_base="http://127.0.0.1:1234",
                           context=None, tools=True, vision=False)
    d1, d2 = lm.deployments([ollama, studio])
    assert (d1.model_name, d1.litellm_model, d1.api_base, d1.provider) == (
        "ollama/qwen3-coder:30b", "ollama_chat/qwen3-coder:30b", "http://127.0.0.1:11434", "local")
    assert d1.deployment_id == "local::ollama/qwen3-coder:30b"
    assert (d2.litellm_model, d2.api_base, d2.provider) == ("openai/phi-4", "http://127.0.0.1:1234/v1", "local")
    assert d2.api_key  # a dummy: OpenAI-compatible clients insist on one
    assert d1.timeout == lm.LOCAL_TIMEOUT_SECONDS


def test_catalog_entries_and_usable_context():
    m = _model("qwen3-coder:30b", context=262144)
    entry = lm.catalog_entry(m)
    assert (entry.id, entry.provider, entry.supports_tools, entry.supports_vision) == (
        "ollama/qwen3-coder:30b", "local", True, False)
    assert entry.input_cost_per_token == 0 and entry.output_cost_per_token == 0
    # 80% of the context the engine runs it with (capped, so a 256K model
    # doesn't eat the computer's memory); unknown context: a small default.
    assert lm.usable_context(m) == int(0.8 * lm.MAX_LOCAL_CONTEXT)
    assert lm.usable_context(_model("x", context=4096)) == int(0.8 * 4096)
    assert lm.usable_context(_model("y", context=None)) == int(0.8 * lm.DEFAULT_LOCAL_CONTEXT)


async def test_a_slow_show_keeps_what_was_known_about_a_model():
    # Ollama busy answering a prompt can miss the one-second /api/show; the
    # model mustn't lose its tools flag (and drop out of routing) for that.
    async with httpx.AsyncClient(transport=httpx.MockTransport(_ollama_handler)) as c:
        await lm.discover(client=c, env={})

    def slow_show(req):
        if req.url.path == "/api/show":
            raise httpx.ReadTimeout("busy", request=req)
        return _ollama_handler(req)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_show)) as c:
        await lm.discover(client=c, env={}, force=True)
    coder = lm.describe("ollama/qwen3-coder:30b")
    assert (coder.tools, coder.context) == (True, 262144)


async def test_current_serves_the_last_result_while_refreshing_in_the_background(monkeypatch):
    # The router asks on every request; a stale result is returned at once
    # and re-probed in the background, so no request waits on a probe.
    import asyncio

    lm.remember([lm.Runtime("ollama", "Ollama", "127.0.0.1:11434", True, (_model("old"),))])
    monkeypatch.setattr(lm, "_cache", (0.0, lm._cache[1]))  # expired
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_discover(**_kw):
        started.set()
        await release.wait()
        lm.remember([lm.Runtime("ollama", "Ollama", "127.0.0.1:11434", True, (_model("new"),))])
        return lm.last()

    monkeypatch.setattr(lm, "discover", slow_discover)
    got = await asyncio.wait_for(lm.current(), timeout=0.5)
    assert [m.id for r in got for m in r.models] == ["ollama/old"]
    await asyncio.wait_for(started.wait(), timeout=0.5)
    again = await asyncio.wait_for(lm.current(), timeout=0.5)  # one refresh at a time
    assert [m.id for r in again for m in r.models] == ["ollama/old"]
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert [m.id for m in lm.last_models()] == ["ollama/new"]


async def test_current_waits_only_for_the_very_first_discovery(monkeypatch):
    calls = []

    async def discover(**_kw):
        calls.append(1)
        lm.remember([])
        return []

    monkeypatch.setattr(lm, "discover", discover)
    assert await lm.current() == []
    assert calls == [1]
