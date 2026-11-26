"""Streaming chat completions — SSE format.

The OpenAI streaming protocol is `text/event-stream` with each chunk
encoded as `data: {json}\\n\\n` and a terminal `data: [DONE]\\n\\n`.
LiteLLM yields chunk objects; the lite chat handler must:
  - return StreamingResponse with the right content-type
  - serialize each chunk as SSE
  - emit the [DONE] sentinel
  - write the RequestLog AFTER the stream finishes (not before)
  - sum the streamed token usage onto the log row
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest


def _chunks_from_sse(text: str) -> list[dict]:
    """Parse `data: {...}\\n\\n` SSE frames into a list of dicts (skipping [DONE])."""
    out = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload.strip() == "[DONE]":
            continue
        out.append(json.loads(payload))
    return out


def _sse_payloads(text: str) -> list[object]:
    """Parse SSE data frames, keeping `[DONE]` as the sentinel string so
    callers can assert usage-before-DONE ordering (issue #127)."""
    out: list[object] = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload.strip() == "[DONE]":
            out.append("[DONE]")
            continue
        out.append(json.loads(payload))
    return out


async def _stream_iter(chunks: list[dict]):
    """Async generator returning a sequence of chunk dicts, mimicking litellm."""
    for c in chunks:
        yield c


@pytest.fixture
async def stream_client(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from app import router_cache
    router_cache.invalidate_router()

    chunks = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": int(time.time()),
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "Hello"},
                "finish_reason": None,
            }],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": int(time.time()),
            "choices": [{
                "index": 0,
                "delta": {"content": " world"},
                "finish_reason": None,
            }],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": int(time.time()),
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            "_orca_meta": {"provider": "openai", "latency_ms": 12},
        },
    ]

    fake_client = AsyncMock()

    async def _acompletion_router(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter(chunks)
        return {
            "id": "chatcmpl-1",
            "model": "gpt-4o-mini",
            "object": "chat.completion",
            "created": int(time.time()),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello world"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            "_orca_meta": {"provider": "openai", "latency_ms": 12},
        }

    fake_client.acompletion = AsyncMock(side_effect=_acompletion_router)

    async def _fake_get_router(_session):
        return fake_client

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from app.main import create_app
    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        yield c, fake_client

    await engine.dispose()
    session_mod._session_factory = None


# ── tests ──

@pytest.mark.parametrize("cost_source", ["frame", "wrapper", "chunk", "usage", "usage-then-counters"])
@pytest.mark.parametrize("surface", ["openai", "anthropic", "gemini"])
async def test_cached_stream_cost_and_authoritative_controls_persist_to_spend(stream_client, monkeypatch, cost_source, surface):
    """Same engine/stream frames, varying only cache reads or explicit cost."""
    from types import SimpleNamespace

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    client, fake = stream_client
    model = "gpt-4o-mini"
    priced = SimpleNamespace(**{**vars(CATALOG_BY_ID[model]),
                               "input_cost_per_token": 2.5e-6, "output_cost_per_token": 1e-5,
                               "cache_read_input_token_cost": 1.25e-6})
    monkeypatch.setitem(CATALOG_BY_ID, model, priced)
    cache_reads = 9000
    explicit_cost = None

    class Stream:
        def __init__(self, usage):
            self.usage = usage
            self._hidden_params = {}

        async def __aiter__(self):
            yield {"model": model, "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}
            terminal = {"model": model, "choices": [], "usage": self.usage}
            if explicit_cost and cost_source == "usage":
                self.usage["cost_usd"] = explicit_cost
                terminal["_orca_meta"] = {"provider": "openai", "cost_usd": 0.003375}
            if explicit_cost and cost_source == "usage-then-counters":
                yield {"model": model, "choices": [], "usage": {**self.usage, "cost_usd": explicit_cost}}
                terminal["_orca_meta"] = {"provider": "openai", "cost_usd": 0.003375}
            if explicit_cost and cost_source == "frame":
                terminal["_orca_meta"] = {"provider": "openai", "cost_usd": explicit_cost}
            if explicit_cost and cost_source == "chunk":
                from litellm.types.utils import ModelResponseStream

                terminal = ModelResponseStream(**terminal)
                terminal._hidden_params["response_cost"] = explicit_cost
            yield terminal
            if explicit_cost and cost_source == "wrapper":
                self._hidden_params["response_cost"] = explicit_cost

    async def upstream(**kwargs):
        usage = {"prompt_tokens": 10000, "completion_tokens": 100, "total_tokens": 10100,
                 "prompt_tokens_details": {"cached_tokens": cache_reads}}
        if kwargs.get("stream"):
            return Stream(usage)
        return {"model": model, "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": usage, "_orca_meta": {"provider": "openai", "cost_usd": 0.01475}}

    fake.acompletion.side_effect = upstream

    async def request(*, stream=False, deterministic=False):
        if surface == "gemini":
            action = "streamGenerateContent?alt=sse" if stream else "generateContent"
            payload = {"contents": "hi"}
            if deterministic:
                payload["generationConfig"] = {"temperature": 0}
            return await client.post(f"/v1beta/models/{model}:{action}", json=payload)
        payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "stream": stream}
        if deterministic:
            payload["temperature"] = 0
        if surface == "anthropic":
            payload["max_tokens"] = 128
        endpoint = "/v1/messages" if surface == "anthropic" else "/v1/chat/completions"
        return await client.post(endpoint, json=payload)

    blocking = await request()
    cached = await request(stream=True)
    cache_reads = 0
    uncached = await request(stream=True)
    cache_reads = 9000
    explicit_cost = 0.123
    authoritative = await request(stream=True)
    assert all(r.status_code == 200 for r in (blocking, cached, uncached, authoritative))
    if surface == "openai":
        assert _chunks_from_sse(cached.text)[-1]["usage"]["prompt_tokens_details"]["cached_tokens"] == 9000
    assert "_orca_meta" not in authoritative.text
    fill = await request(deterministic=True)
    hit = await request(deterministic=True)
    assert fill.status_code == hit.status_code == 200
    assert hit.headers["x-orca-cache"] == "HIT"
    assert fake.acompletion.call_count == 5

    async with session_mod._session_factory() as session:
        rows = (await session.execute(select(RequestLog).order_by(RequestLog.created_at))).scalars().all()
    assert [(row.is_streaming, row.input_tokens, row.output_tokens, row.cost_microcents) for row in rows] == [
        (False, 10000, 100, 14750), (True, 10000, 100, 14750),
        (True, 10000, 100, 26000), (True, 10000, 100, 123000),
        (False, 10000, 100, 14750), (False, 10000, 100, 0),
    ]
    assert rows[-1].provider == "cache"
    spend = await client.get("/v1/analytics/spend")
    assert spend.status_code == 200
    assert spend.json()["total_microcents"] == 193250


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("upstream_cost,expected", [(0.123, 123000), (0, 0)])
async def test_hosted_upstream_cost_overrides_litellm_estimate_in_persisted_log(
    stream_client, monkeypatch, stream, upstream_cost, expected,
):
    """Hosted usage.cost_usd is billing truth; SDK-computed cost is an estimate."""
    from types import SimpleNamespace

    import httpx
    from litellm.llms.openai.openai import OpenAIChatCompletion
    from sqlalchemy import select

    from app import router_cache
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog
    from packages.litellm_adapter.client import OrcaLiteLLMClient

    client, _ = stream_client
    model = "gpt-5"
    adapter_responses = []

    def transport(request):
        assert request.url.host == "provider.invalid"
        assert request.headers["X-OrcaRouter-beta-usd"] == "response"
        payload = json.loads(request.content)
        usage = {"prompt_tokens": 10000, "completion_tokens": 100, "total_tokens": 10100,
                 "prompt_tokens_details": {"cached_tokens": 9000}, "cost_usd": upstream_cost}
        base = {"id": "chatcmpl-hosted-cost", "model": model, "created": 1}
        if payload.get("stream"):
            frames = [
                {**base, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}]},
                {**base, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {**base, "object": "chat.completion.chunk", "choices": [], "usage": usage},
            ]
            data = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)
        return httpx.Response(200, json={**base, "object": "chat.completion", "usage": usage,
                                       "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                                    "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as provider_http:
        monkeypatch.setattr(OpenAIChatCompletion, "_get_async_http_client", staticmethod(lambda **kw: provider_http))
        settings = SimpleNamespace(orcarouter_api_key="sk-test", orcarouter_base_url="https://provider.invalid/v1")
        hosted = next(d for d in router_cache.build_deployments(env_keys={}, db_keys=[], settings=settings)
                      if d.model_name == model)
        adapter = OrcaLiteLLMClient([hosted], cooldown_time=0, allowed_fails=0,
                                   enable_pre_call_checks=False, num_retries=0)
        acompletion = adapter.acompletion

        async def record_response(**kwargs):
            response = await acompletion(**kwargs)
            adapter_responses.append(response)
            return response

        monkeypatch.setattr(adapter, "acompletion", record_response)
        monkeypatch.setattr(router_cache, "get_router", AsyncMock(return_value=adapter))
        response = await client.post("/v1/chat/completions", json={
            "model": model, "messages": [{"role": "user", "content": "hi"}], "stream": stream,
        })
    assert response.status_code == 200
    if stream:
        assert _chunks_from_sse(response.text)[-1]["usage"]["prompt_tokens"] == 10000
        # LiteLLM rebuilds terminal usage and drops this extension there,
        # but its retained provider usage still carries the exact cost.
        assert any(getattr(getattr(chunk, "usage", None), "cost_usd", None) == upstream_cost
                   for chunk in adapter_responses[0].chunks)
    else:
        assert adapter_responses[0]["usage"]["cost_usd"] == upstream_cost
        estimate = adapter_responses[0]["_orca_meta"]["cost_usd"]
        assert estimate > 0 and estimate != upstream_cost
    async with session_mod._session_factory() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    assert [(row.provider, row.is_streaming, row.cost_microcents) for row in rows] == [
        ("orcarouter", stream, expected),
    ]
    spend = await client.get("/v1/analytics/spend")
    assert spend.json()["total_microcents"] == expected


@pytest.mark.parametrize("cost_path", ["observed", "retained"])
@pytest.mark.parametrize("earlier,final,expected", [
    pytest.param({}, {}, 1000, id="matching-counters"),
    pytest.param({}, {"prompt_tokens": 2000}, 500, id="prompt-growth"),
    pytest.param({}, {"prompt_tokens": 500}, 500, id="prompt-shrink"),
    pytest.param({}, {"completion_tokens": 200}, 500, id="completion-growth"),
    pytest.param({}, {"completion_tokens": 50}, 500, id="completion-shrink"),
    pytest.param({"prompt_tokens": None}, {}, 500, id="missing-earlier-prompt"),
    pytest.param({"completion_tokens": None}, {}, 500, id="missing-earlier-completion"),
    pytest.param({}, {"prompt_tokens": None}, 500, id="missing-final-prompt"),
    pytest.param({}, {"completion_tokens": None}, 500, id="missing-final-completion"),
    pytest.param({"prompt_tokens": True}, {"prompt_tokens": 1}, 500, id="bool-counter"),
    pytest.param({"prompt_tokens": 1000.0}, {}, 500, id="float-counter"),
    pytest.param({}, {"cost_usd": 0}, 0, id="final-zero"),
    pytest.param({"cost_usd": 0}, {}, 0, id="recovered-zero"),
    pytest.param({}, {"cost_usd": 0.002}, 2000, id="latest-final-cost"),
    pytest.param({"cost_usd": -1}, {}, 500, id="negative-history"),
    pytest.param({"cost_usd": float("nan")}, {}, 500, id="nan-history"),
    pytest.param({"cost_usd": float("inf")}, {}, 500, id="infinite-history"),
    pytest.param({"cost_usd": True}, {}, 500, id="bool-history"),
    pytest.param({"cost_usd": "0.001"}, {}, 500, id="malformed-history"),
    pytest.param({}, {"cost_usd": -1}, 500, id="invalid-final-does-not-revive-history"),
    pytest.param({}, {"cost_usd": float("nan")}, 500, id="nan-final-does-not-revive-history"),
    pytest.param({}, {"cost_usd": False}, 500, id="bool-final-does-not-revive-history"),
    pytest.param([{}, {"cost_usd": 0.002}], {}, 2000, id="latest-retained-cost"),
    pytest.param([{}, {"cost_usd": 0}], {}, 0, id="latest-retained-zero"),
    pytest.param([{}, {"cost_usd": -1}], {}, 500, id="latest-retained-invalid"),
    pytest.param([{}, {"prompt_tokens": 500, "cost_usd": 0.003}], {}, 500,
                 id="latest-retained-mismatch-does-not-revive-older-match"),
    pytest.param({"cost_usd": None}, {"cost": 0.25}, 500, id="local-cost-is-not-billing"),
    pytest.param({"prompt_tokens_details": {"cached_tokens": 900}},
                 {"prompt_tokens_details": {"cached_tokens": 0}}, 500, id="cache-read-changed"),
    pytest.param({"cache_read_input_tokens": 900},
                 {"prompt_tokens_details": {"cached_tokens": 0}}, 500, id="cache-read-alias-changed"),
    pytest.param({"cache_creation_input_tokens": 100},
                 {"prompt_tokens_details": {"cache_write_tokens": 200}}, 500, id="cache-write-changed"),
    pytest.param({"cache_read_input_tokens": 900},
                 {"prompt_tokens_details": {"cached_tokens": 900}}, 1000, id="matching-cache-alias"),
    pytest.param({"cache_read_input_tokens": 900, "prompt_tokens_details": {"cached_tokens": 800}},
                 {"cache_read_input_tokens": 900}, 500, id="conflicting-cache-aliases"),
])
async def test_recovered_stream_bill_matches_final_usage_in_sql_and_spend(
    stream_client, cost_path, earlier, final, expected,
):
    """Counter-only terminal rebuilds must not borrow another usage frame's bill."""
    from types import SimpleNamespace

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    client, fake = stream_client
    history = [{"prompt_tokens": 1000, "completion_tokens": 100, "cost_usd": 0.001, **item}
               for item in (earlier if isinstance(earlier, list) else [earlier])]
    terminal = {"prompt_tokens": 1000, "completion_tokens": 100, **final}
    history = [{key: value for key, value in item.items() if value is not None} for item in history]
    terminal = {key: value for key, value in terminal.items() if value is not None}

    class Stream:
        # Real SDK history contains typed usage objects. The observed path
        # intentionally has no retained history to rescue broken aggregation.
        chunks = [SimpleNamespace(usage=SimpleNamespace(**item)) for item in history] if cost_path == "retained" else []

        async def __aiter__(self):
            if cost_path == "observed":
                for previous in history:
                    yield {"model": "gpt-4o-mini", "choices": [], "usage": previous}
            yield {"model": "gpt-4o-mini", "choices": [], "usage": terminal,
                   "_orca_meta": {"provider": "openai", "cost_usd": 0.0005}}

    fake.acompletion.side_effect = lambda **kwargs: Stream()
    response = await client.post("/v1/chat/completions", json={
        "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    })
    assert response.status_code == 200
    async with session_mod._session_factory() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    assert [(row.input_tokens, row.output_tokens, row.cost_microcents) for row in rows] == [
        (terminal.get("prompt_tokens", 0), terminal.get("completion_tokens", 0), expected),
    ]
    spend = await client.get("/v1/analytics/spend")
    assert spend.status_code == 200
    assert spend.json()["total_microcents"] == expected


async def test_real_litellm_sdk_cached_stream_matches_blocking_and_uncached_control(stream_client, monkeypatch):
    """Real adapter + Router + OpenAI SDK; only HTTP transport is replaced."""
    import httpx
    from litellm.llms.openai.openai import OpenAIChatCompletion
    from sqlalchemy import select

    from app import router_cache
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog
    from packages.litellm_adapter.catalog import CATALOG_BY_ID
    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import ProviderDeployment

    client, _ = stream_client
    model = "gpt-4o-2024-08-06"
    reads = 9000
    sent = []

    def transport(request):
        assert request.url.host == "provider.invalid"
        payload = json.loads(request.content)
        sent.append(payload)
        usage = {"prompt_tokens": 10000, "completion_tokens": 100, "total_tokens": 10100,
                 "prompt_tokens_details": {"cached_tokens": reads}}
        base = {"id": "chatcmpl-cost", "model": model, "created": 1}
        if payload.get("stream"):
            frames = [
                {**base, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}]},
                {**base, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {**base, "object": "chat.completion.chunk", "choices": [], "usage": usage},
            ]
            data = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=data)
        return httpx.Response(200, json={**base, "object": "chat.completion", "usage": usage,
                                       "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                                    "finish_reason": "stop"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as provider_http:
        monkeypatch.setattr(OpenAIChatCompletion, "_get_async_http_client", staticmethod(lambda **kw: provider_http))
        adapter = OrcaLiteLLMClient([
            ProviderDeployment(model_name=model, litellm_model="openai/" + model,
                               api_key="sk-test", provider="openai", api_base="https://provider.invalid/v1"),
        ], cooldown_time=0, allowed_fails=0, enable_pre_call_checks=False, num_retries=0)
        monkeypatch.setattr(router_cache, "get_router", AsyncMock(return_value=adapter))
        payload = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
        blocking = await client.post("/v1/chat/completions", json=payload)
        cached = await client.post("/v1/chat/completions", json={**payload, "stream": True})
        reads = 0
        uncached = await client.post("/v1/chat/completions", json={**payload, "stream": True})
    assert all(r.status_code == 200 for r in (blocking, cached, uncached))
    assert len(sent) == 3
    assert _chunks_from_sse(cached.text)[-1]["usage"]["prompt_tokens_details"]["cached_tokens"] == 9000

    priced = CATALOG_BY_ID[model]
    cached_cost = int((1000 * priced.input_cost_per_token + 9000 * priced.cache_read_input_token_cost
                       + 100 * priced.output_cost_per_token) * 1_000_000)
    full_cost = int((10000 * priced.input_cost_per_token + 100 * priced.output_cost_per_token) * 1_000_000)
    async with session_mod._session_factory() as session:
        rows = (await session.execute(select(RequestLog).order_by(RequestLog.created_at))).scalars().all()
    assert [row.cost_microcents for row in rows] == [cached_cost, cached_cost, full_cost]
    assert all(row.provider == "openai" for row in rows)
    spend = await client.get("/v1/analytics/spend")
    assert spend.json()["total_microcents"] == 2 * cached_cost + full_cost


async def test_streaming_returns_sse_content_type(stream_client):
    client, _ = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")


async def test_streaming_emits_chunks_and_done_sentinel(stream_client):
    client, _ = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    body = r.text
    assert "data: [DONE]" in body
    chunks = _chunks_from_sse(body)
    # Two content deltas + the finish_reason frame, which already carries
    # usage. Do not append a second, empty-choices usage frame.
    assert len(chunks) == 3
    usage_frames = [c for c in chunks if c.get("usage")]
    assert len(usage_frames) == 1
    assert usage_frames[0]["usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
    }
    assert usage_frames[0]["choices"][0]["finish_reason"] == "stop"
    # Concatenated content matches non-streaming path
    deltas = []
    for c in chunks:
        choices = c.get("choices") or []
        if not choices:
            continue
        deltas.append(choices[0].get("delta", {}).get("content", ""))
    assert "".join(d for d in deltas if d) == "Hello world"
    # Internal _orca_meta must NOT be exposed in the SSE stream
    assert "_orca_meta" not in body


async def test_streaming_emits_usage_chunk_before_done(stream_client):
    """When the upstream stream already ends on a frame that carries
    usage (here, LiteLLM's finish_reason chunk — choices are non-empty),
    that frame is the usage frame. It must sit immediately before [DONE],
    and we must not synthesize a second empty-choices copy."""
    client, _ = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    frames = _sse_payloads(r.text)
    assert frames, "expected SSE frames"
    assert frames[-1] == "[DONE]"
    usage_frames = [
        f for f in frames if isinstance(f, dict) and f.get("usage")
    ]
    assert len(usage_frames) == 1
    usage_frame = usage_frames[0]
    assert usage_frame is frames[-2]
    assert usage_frame.get("usage") == {
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
    }
    assert usage_frame.get("object") == "chat.completion.chunk"
    assert usage_frame.get("id") == "chatcmpl-1"
    assert usage_frame.get("model") == "gpt-4o-mini"
    assert usage_frame.get("choices") != []
    assert not any(
        isinstance(f, dict) and f.get("usage") and not (f.get("choices") or [])
        for f in frames
    )


async def test_streaming_does_not_duplicate_upstream_usage_only_chunk(stream_client):
    """If upstream already ended with OpenAI's usage-only frame, do not
    emit a second copy before [DONE]."""
    client, fake = stream_client
    now = int(time.time())
    chunks = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "Hi"},
                "finish_reason": None,
            }],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        },
    ]

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter(chunks)
        raise AssertionError("test only exercises stream path")

    fake.acompletion = AsyncMock(side_effect=_acompletion)
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    frames = _sse_payloads(r.text)
    assert frames[-1] == "[DONE]"
    usage_only = [
        f
        for f in frames
        if isinstance(f, dict) and f.get("usage") and not (f.get("choices") or [])
    ]
    assert len(usage_only) == 1
    assert usage_only[0]["usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 1,
        "total_tokens": 5,
    }
    assert frames[-2] is usage_only[0]


async def test_streaming_does_not_duplicate_litellm_placeholder_usage_frame(stream_client):
    """LiteLLM's include_usage frame is not `choices: []`. It is a trailing
    chunk shaped `choices: [{"index": 0, "delta": {}}]` that already carries
    usage. That frame is the usage frame — do not emit a second copy."""
    client, fake = stream_client
    now = int(time.time())
    usage = {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5}
    chunks = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "Hi"},
                "finish_reason": None,
            }],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{"index": 0, "delta": {}}],
            "usage": usage,
        },
    ]

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter(chunks)
        raise AssertionError("test only exercises stream path")

    fake.acompletion = AsyncMock(side_effect=_acompletion)
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    frames = _sse_payloads(r.text)
    assert frames[-1] == "[DONE]"
    usage_frames = [
        f for f in frames if isinstance(f, dict) and f.get("usage")
    ]
    assert usage_frames == [frames[-2]]
    assert frames[-2]["usage"] == usage
    assert frames[-2]["choices"] == [{"index": 0, "delta": {}}]


async def test_streaming_synthesizes_usage_when_last_frame_omits_it(stream_client):
    """Usage aggregated from an earlier chunk, but the stream ends on a
    frame that has none. Append one empty-choices usage frame before
    [DONE]. This is the only case that still synthesizes."""
    client, fake = stream_client
    now = int(time.time())
    usage = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
    chunks = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{
                "index": 0,
                "delta": {"content": "Hi"},
                "finish_reason": None,
            }],
            "usage": usage,
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter(chunks)
        raise AssertionError("test only exercises stream path")

    fake.acompletion = AsyncMock(side_effect=_acompletion)
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    frames = _sse_payloads(r.text)
    assert frames[-1] == "[DONE]"
    synthesized = frames[-2]
    assert isinstance(synthesized, dict)
    assert synthesized.get("choices") == []
    assert synthesized.get("usage") == usage
    assert synthesized.get("object") == "chat.completion.chunk"
    assert synthesized.get("id") == "chatcmpl-1"
    assert synthesized.get("model") == "gpt-4o-mini"
    # The earlier upstream frame is still forwarded; the synthesized frame
    # is the only empty-choices usage chunk, and it follows finish_reason.
    upstream_usage = [
        f for f in frames[:-2] if isinstance(f, dict) and f.get("usage")
    ]
    assert len(upstream_usage) == 1
    assert upstream_usage[0]["choices"][0]["delta"]["content"] == "Hi"
    finish_idxs = [
        i
        for i, f in enumerate(frames)
        if isinstance(f, dict)
        and any((c or {}).get("finish_reason") for c in (f.get("choices") or []))
    ]
    assert finish_idxs == [1]
    assert finish_idxs[-1] < len(frames) - 2


async def test_streaming_omits_usage_chunk_when_upstream_has_none(stream_client):
    """No synthetic empty usage frame when the upstream stream carried none."""
    client, fake = stream_client
    now = int(time.time())
    chunks = [
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{
                "index": 0,
                "delta": {"content": "Hi"},
                "finish_reason": None,
            }],
        },
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter(chunks)
        raise AssertionError("test only exercises stream path")

    fake.acompletion = AsyncMock(side_effect=_acompletion)
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    frames = _sse_payloads(r.text)
    assert frames[-1] == "[DONE]"
    assert all(not (isinstance(f, dict) and f.get("usage")) for f in frames)


async def test_streaming_writes_request_log_with_usage(stream_client):
    client, _ = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    # Drain the body so the streaming finally-block runs.
    _ = r.text

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    log = rows[0]
    assert log.is_streaming is True
    assert log.input_tokens == 4
    assert log.output_tokens == 2
    assert log.provider == "openai"
    assert log.status_code == 200


async def test_non_streaming_still_works_unchanged(stream_client):
    """Don't regress slice 7."""
    client, _ = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["choices"][0]["message"]["content"] == "Hello world"


async def test_streaming_auto_injects_include_usage_when_client_omits_it(stream_client):
    """OpenAI streaming omits the `usage` field unless the caller opts in
    via `stream_options.include_usage=true`. Almost no client knows to set
    this — and without it our cost calculation falls back to 0. The server
    auto-injects it so spend tracking works regardless of caller."""
    client, fake = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 200
    # Inspect what got passed down to the LiteLLM wrapper.
    call_kwargs = fake.acompletion.call_args.kwargs
    assert call_kwargs.get("stream_options") == {"include_usage": True}, (
        f"server should auto-inject include_usage=True; got "
        f"{call_kwargs.get('stream_options')}"
    )


async def test_streaming_respects_explicit_client_include_usage_false(stream_client):
    """Regression: ChatCompletionRequest must declare `stream_options` as a
    field, otherwise Pydantic silently drops it from the request body and
    a client's explicit `include_usage=false` opt-out gets clobbered by
    our auto-inject. (Codex round-2 [P2] — without the schema field the
    auto-inject branch sees no client value and overrides to True.)"""
    client, fake = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"include_usage": False},
        },
    )
    assert r.status_code == 200
    call_kwargs = fake.acompletion.call_args.kwargs
    assert call_kwargs.get("stream_options") == {"include_usage": False}, (
        f"client opt-out must survive end-to-end; got "
        f"{call_kwargs.get('stream_options')}"
    )


async def test_streaming_client_disconnect_writes_log_and_closes_upstream(
    tmp_sqlite_url, monkeypatch,
):
    """Client closes the connection mid-stream (Ctrl+C, tab close, proxy
    timeout). Two things MUST happen:
      1. The request_log row gets written with status_code=499 and
         error_type='client_disconnect' (analytics need this signal to
         tell user-bailed apart from upstream-failed).
      2. The upstream stream wrapper's aclose() gets called so LiteLLM
         stops pulling more chunks from the provider — otherwise we keep
         burning tokens on a response nobody will read.

    We simulate the disconnect by having the consumer break out of the
    SSE iteration after the first chunk, which causes Starlette to
    cancel the generator task.
    """
    import asyncio
    import time
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from app import router_cache
    router_cache.invalidate_router()

    # Stream that yields one chunk then raises CancelledError — mirrors
    # what Starlette's anyio task group does when it sees `http.disconnect`
    # on the receive channel: it cancels the task running our SSE
    # generator, which surfaces as CancelledError at the next `await` in
    # the chunk iteration loop. (We do this instead of relying on
    # httpx.ASGITransport, which doesn't propagate disconnect events to
    # the ASGI app — the real-world signal flow only happens behind a
    # network transport.)
    class _CancellingStream:
        def __init__(self):
            self.closed = False
            self._yielded = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._yielded:
                self._yielded = True
                return {
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "model": "gpt-4o-mini",
                    "created": int(time.time()),
                    "choices": [{"index": 0, "delta": {"content": "Hi"},
                                 "finish_reason": None}],
                }
            # Simulate Starlette cancelling our task mid-stream.
            raise asyncio.CancelledError()

        async def aclose(self):
            self.closed = True

    slow = _CancellingStream()
    fake_client = AsyncMock()

    async def _acompletion_router(**kwargs):
        if kwargs.get("stream"):
            return slow
        raise AssertionError("test only exercises stream path")

    fake_client.acompletion = AsyncMock(side_effect=_acompletion_router)

    async def _fake_get_router(_session):
        return fake_client
    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from app.main import create_app
    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
        timeout=10.0,
    ) as c:
        # The CancelledError raised inside our generator during chunk
        # iteration propagates up. Starlette's StreamingResponse converts
        # it back into a normal stream-end (since the cancel originated
        # inside the generator, not from disconnect). The client just
        # sees the stream end after one chunk + cleanup yields.
        try:
            async with c.stream(
                "POST", "/v1/chat/completions",
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": True,
                },
            ) as response:
                assert response.status_code == 200
                async for _ in response.aiter_lines():
                    pass
        except Exception:
            # CancelledError in the SSE generator may surface as a
            # transport-level error to httpx — we don't care, we're
            # checking server-side state below.
            pass

    # Give the cancel-handling code a moment to finish background tasks.
    await asyncio.sleep(0.2)

    # 1. Upstream got closed (no token-burn after the cancel).
    assert slow.closed is True, (
        "stream_obj.aclose() must be called when the SSE generator is "
        "cancelled, otherwise LiteLLM keeps pulling chunks from the provider"
    )

    # 2. Log row written with the disconnect signal so analytics can
    # distinguish user-bailed from upstream-failed requests.
    from packages.db.models.request_log import RequestLog
    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1, "request_log must be written even on cancel"
    row = rows[0]
    assert row.status_code == 499, f"expected 499, got {row.status_code}"
    assert row.error_type == "client_disconnect", (
        f"expected error_type='client_disconnect', got {row.error_type!r}"
    )
    assert row.is_streaming is True

    await engine.dispose()
    session_mod._session_factory = None


async def test_streaming_preserves_other_stream_options_fields(stream_client):
    """Client may pass additional `stream_options` fields besides
    `include_usage`. Our auto-inject must add `include_usage=True` only
    when missing, leaving other fields intact (don't clobber the dict)."""
    client, fake = stream_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
            "stream_options": {"future_field": "preserve_me"},
        },
    )
    assert r.status_code == 200
    so = fake.acompletion.call_args.kwargs.get("stream_options")
    assert so == {"future_field": "preserve_me", "include_usage": True}, (
        f"must merge auto-inject with existing fields, not replace; got {so}"
    )
