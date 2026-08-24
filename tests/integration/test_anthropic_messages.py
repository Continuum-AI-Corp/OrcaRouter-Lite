"""POST /v1/messages — Anthropic Messages API ingress (slices S3-S5).

Real app + mocked LiteLLM router (same pattern as test_streaming.py).
Covers: x-api-key / Bearer auth, native error envelopes (never the OpenAI
one), blocking + streaming translation, tool round-trips, RequestLog
writeback, cross-protocol prompt-cache sharing, and count_tokens.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest


def _openai_response(**kwargs) -> dict:
    return {
        "id": "chatcmpl-1",
        "model": kwargs.get("model", "gpt-4o-mini"),
        "object": "chat.completion",
        "created": int(time.time()),
        "choices": [{
            "index": 0,
            "message": kwargs.get(
                "message", {"role": "assistant", "content": "Hello world"}
            ),
            "finish_reason": kwargs.get("finish_reason", "stop"),
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        "_orca_meta": {"provider": "openai", "latency_ms": 12},
    }


def _stream_chunks() -> list[dict]:
    now = int(time.time())
    return [
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0,
                         "delta": {"role": "assistant", "content": "Hello"},
                         "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {"content": " world"},
                         "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            "_orca_meta": {"provider": "openai", "latency_ms": 12},
        },
    ]


@pytest.fixture
async def native_client(tmp_sqlite_url, monkeypatch):
    """App + mocked router. NO default auth header — credential-location
    variants are part of what these tests exercise. Yields
    (httpx client, fake router mock, seeded api key)."""
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

    async def _stream_iter(chunks):
        for c in chunks:
            yield c

    fake = AsyncMock()

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _stream_iter(_stream_chunks())
        return _openai_response(model=kwargs.get("model", "gpt-4o-mini"))

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from app.main import create_app
    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t",
    ) as c:
        yield c, fake, seed.api_key

    await engine.dispose()
    session_mod._session_factory = None


def _messages_payload(**overrides) -> dict:
    base = {
        "model": "gpt-4o-mini",
        "max_tokens": 128,
        "messages": [{"role": "user", "content": "hi"}],
    }
    base.update(overrides)
    return base


def _parse_anthropic_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        lines = frame.splitlines()
        assert lines[0].startswith("event: "), f"frame missing event line: {frame!r}"
        assert lines[1].startswith("data: ")
        events.append((lines[0][len("event: "):],
                       json.loads(lines[1][len("data: "):])))
    return events


# ── auth ──


async def test_x_api_key_authenticates(native_client):
    client, _, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(),
                          headers={"x-api-key": key})
    assert r.status_code == 200


async def test_bearer_also_authenticates(native_client):
    client, _, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(),
                          headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200


async def test_missing_key_renders_anthropic_envelope(native_client):
    client, _, _ = native_client
    r = await client.post("/v1/messages", json=_messages_payload())
    assert r.status_code == 401
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "authentication_error"


async def test_invalid_key_renders_anthropic_envelope(native_client):
    client, _, _ = native_client
    r = await client.post("/v1/messages", json=_messages_payload(),
                          headers={"x-api-key": "sk-orca-bogus"})
    assert r.status_code == 401
    assert r.json()["type"] == "error"


# ── blocking ──


async def test_blocking_response_shape_and_orca_headers(native_client):
    client, fake, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(),
                          headers={"x-api-key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["content"] == [{"type": "text", "text": "Hello world"}]
    assert body["stop_reason"] == "end_turn"
    assert body["usage"] == {"input_tokens": 4, "output_tokens": 2}
    assert r.headers["x-orca-resolved-model"] == "gpt-4o-mini"
    assert r.headers["x-orca-requested-model"] == "gpt-4o-mini"

    # engine received the translated OpenAI body
    kwargs = fake.acompletion.call_args.kwargs
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["max_tokens"] == 128


async def test_missing_max_tokens_is_400_invalid_request_not_422(native_client):
    client, _, key = native_client
    payload = _messages_payload()
    del payload["max_tokens"]
    r = await client.post("/v1/messages", json=payload, headers={"x-api-key": key})
    assert r.status_code == 400
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "invalid_request_error"
    assert "max_tokens" in body["error"]["message"]


async def test_malformed_json_body_returns_native_400(native_client):
    client, _, key = native_client
    r = await client.post("/v1/messages", content=b"{not json",
                          headers={"x-api-key": key,
                                   "content-type": "application/json"})
    assert r.status_code == 400
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "invalid_request_error"


async def test_non_object_body_returns_native_400(native_client):
    client, _, key = native_client
    r = await client.post("/v1/messages", json=[1, 2],
                          headers={"x-api-key": key})
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"


async def test_upstream_error_renders_native_envelope(native_client):
    client, fake, key = native_client
    fake.acompletion = AsyncMock(side_effect=RuntimeError("provider exploded"))
    r = await client.post("/v1/messages", json=_messages_payload(),
                          headers={"x-api-key": key})
    assert r.status_code == 500  # engine's 503 collapses to Anthropic api_error/500
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "api_error"


async def test_tools_round_trip_through_the_wire(native_client):
    client, fake, key = native_client

    async def _tool_response(**kwargs):
        return _openai_response(
            message={
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "get_weather",
                                 "arguments": '{"city": "SF"}'},
                }],
            },
            finish_reason="tool_calls",
        )

    fake.acompletion = AsyncMock(side_effect=_tool_response)
    r = await client.post("/v1/messages", json=_messages_payload(
        tools=[{"name": "get_weather", "description": "d",
                "input_schema": {"type": "object",
                                 "properties": {"city": {"type": "string"}}}}],
        tool_choice={"type": "auto"},
    ), headers={"x-api-key": key})
    assert r.status_code == 200

    kwargs = fake.acompletion.call_args.kwargs
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["tools"][0]["function"]["name"] == "get_weather"
    assert kwargs["tool_choice"] == "auto"

    body = r.json()
    assert body["stop_reason"] == "tool_use"
    (block,) = body["content"]
    assert block["type"] == "tool_use"
    assert block["input"] == {"city": "SF"}


async def test_tool_result_history_reaches_engine_as_tool_message(native_client):
    client, fake, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(messages=[
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "get_weather",
             "input": {"city": "SF"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "72F"},
        ]},
    ]), headers={"x-api-key": key})
    assert r.status_code == 200
    messages = fake.acompletion.call_args.kwargs["messages"]
    tool_msgs = [m for m in messages if m.get("role") == "tool"]
    assert tool_msgs == [{"role": "tool", "tool_call_id": "toolu_1", "content": "72F"}]


# ── streaming ──


async def test_streaming_event_sequence_and_request_log(native_client):
    client, _, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(stream=True),
                          headers={"x-api-key": key})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _parse_anthropic_sse(r.text)
    names = [n for n, _ in events]
    assert names == [
        "message_start", "content_block_start", "content_block_delta",
        "content_block_delta", "content_block_stop", "message_delta",
        "message_stop",
    ]
    assert "[DONE]" not in r.text

    deltas = [d["delta"]["text"] for n, d in events if n == "content_block_delta"]
    assert "".join(deltas) == "Hello world"
    msg_delta = [d for n, d in events if n == "message_delta"][0]
    assert msg_delta["usage"]["output_tokens"] == 2

    # the engine wrote the RequestLog row with streamed usage
    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].is_streaming is True
    assert rows[0].input_tokens == 4
    assert rows[0].output_tokens == 2
    assert rows[0].status_code == 200


async def test_streaming_client_disconnect_closes_upstream_and_logs_499(native_client):
    """Client bails mid-stream. The cancellation must propagate through the
    adapter's generator chain (transformer → OpenAIFrameStream → engine)
    so the engine's disconnect handling still runs: upstream aclose() gets
    called (stop burning tokens) and the RequestLog row records
    499/client_disconnect. Mirrors test_streaming.py's disconnect test."""
    import asyncio

    client, fake, key = native_client

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
                    "id": "chatcmpl-1", "object": "chat.completion.chunk",
                    "model": "gpt-4o-mini", "created": int(time.time()),
                    "choices": [{"index": 0, "delta": {"content": "Hi"},
                                 "finish_reason": None}],
                }
            raise asyncio.CancelledError()

        async def aclose(self):
            self.closed = True

    slow = _CancellingStream()

    async def _stream_router(**kwargs):
        assert kwargs.get("stream")
        return slow

    fake.acompletion = AsyncMock(side_effect=_stream_router)

    try:
        async with client.stream(
            "POST", "/v1/messages",
            json=_messages_payload(stream=True),
            headers={"x-api-key": key},
        ) as response:
            assert response.status_code == 200
            async for _ in response.aiter_lines():
                pass
    except Exception:
        # The cancel may surface as a transport error to httpx — we only
        # care about server-side state below.
        pass

    await asyncio.sleep(0.2)

    assert slow.closed is True, (
        "upstream aclose() must be called when the client disconnects, even "
        "through the protocol-adapter generator chain"
    )

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status_code == 499
    assert rows[0].error_type == "client_disconnect"
    assert rows[0].is_streaming is True


# ── pipeline reuse ──


async def test_prompt_cache_is_shared_across_protocols(native_client):
    """The cache key is computed on the TRANSLATED body, so the same
    semantic request via /v1/chat/completions then /v1/messages must hit
    the same cache entry."""
    client, fake, key = native_client
    # temperature 0 on both sides: only a deterministic request is cached
    # at all (an omitted temperature means the upstream default of 1.0).
    openai_payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 128,
        "temperature": 0,
    }
    r1 = await client.post("/v1/chat/completions", json=openai_payload,
                           headers={"Authorization": f"Bearer {key}"})
    assert r1.status_code == 200
    assert r1.headers["x-orca-cache"] == "MISS"

    r2 = await client.post("/v1/messages", json=_messages_payload(temperature=0),
                           headers={"x-api-key": key})
    assert r2.status_code == 200
    assert r2.headers["x-orca-cache"] == "HIT"
    assert r2.json()["content"] == [{"type": "text", "text": "Hello world"}]
    # only the first request reached the (mock) upstream
    assert fake.acompletion.call_count == 1


async def test_model_auto_resolves_through_anthropic_ingress(native_client):
    client, fake, key = native_client

    from packages.litellm_adapter.catalog import models_for_provider
    from packages.litellm_adapter.types import ProviderDeployment

    fake._deployments = [
        ProviderDeployment(
            model_name=m.id, litellm_model=f"{m.litellm_prefix}{m.id}",
            api_key="sk-test", provider="openai",
        )
        for m in models_for_provider("openai")
    ]
    r = await client.post("/v1/messages", json=_messages_payload(model="auto"),
                          headers={"x-api-key": key})
    assert r.status_code == 200
    assert r.headers["x-orca-requested-model"] == "auto"
    resolved = r.headers["x-orca-resolved-model"]
    assert resolved != "auto"
    assert fake.acompletion.call_args.kwargs["model"] == resolved


# ── count_tokens ──


async def test_count_tokens_returns_positive_estimate(native_client):
    client, _, key = native_client
    r = await client.post("/v1/messages/count_tokens", json={
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hello there, how are you?"}],
    }, headers={"x-api-key": key})
    assert r.status_code == 200
    tokens = r.json()["input_tokens"]
    assert isinstance(tokens, int)
    assert tokens > 0


async def test_count_tokens_requires_auth(native_client):
    client, _, _ = native_client
    r = await client.post("/v1/messages/count_tokens", json={
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert r.status_code == 401
    assert r.json()["type"] == "error"


async def test_blocking_model_not_found_renders_404_not_found(native_client):
    """The engine reports model_not_found as HTTP 422; on this surface it
    must render 404 not_found_error (Anthropic's contract), matching the
    streaming error map — not collapse to 400 invalid_request_error."""
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "model does not exist", http_status=422, error_type="model_not_found",
    ))
    r = await client.post("/v1/messages", json={
        "model": "gpt-4o-mini", "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers={"x-api-key": key})
    assert r.status_code == 404
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "not_found_error"


async def test_blocking_upstream_auth_error_is_non_retryable(native_client):
    """OUR provider credential failing is permanent until the operator
    fixes it. The engine reports it as a retryable 503; this surface must
    render a non-retryable 403 permission_error (matching the Gemini
    surface), NOT 500 api_error which SDKs retry with backoff — and not
    401, since the caller's own key is fine."""
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "provider rejected the key", http_status=503,
        error_type="upstream_auth_error",
    ))
    r = await client.post("/v1/messages", json={
        "model": "gpt-4o-mini", "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers={"x-api-key": key})
    assert r.status_code == 403
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "permission_error"


async def test_no_providers_configured_is_non_retryable(native_client):
    """A fresh install with no provider key is permanent until the
    operator adds one — it must not render as a retryable 500 api_error
    the SDK keeps backing off against."""
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "No provider keys configured.", http_status=503,
        error_type="no_providers_configured",
    ))
    r = await client.post("/v1/messages", json={
        "model": "gpt-4o-mini", "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers={"x-api-key": key})
    assert r.status_code == 403
    assert r.json()["error"]["type"] == "permission_error"


async def test_auto_without_providers_matches_the_pinned_403(native_client):
    """The same permanent operator-side condition must classify the same
    way whether the model is pinned or auto-resolved: auto used to render
    a client-blaming 400 invalid_request_error while a pinned model gave
    403 permission_error."""
    client, fake, key = native_client
    fake._deployments = []  # no provider key configured anywhere

    r = await client.post("/v1/messages", json={
        "model": "auto", "max_tokens": 16,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers={"x-api-key": key})
    assert r.status_code == 403
    assert r.json()["error"]["type"] == "permission_error"


async def test_cache_is_not_shared_across_different_max_tokens(native_client):
    """Regression: the prompt-cache key omitted max_tokens, so a second
    request differing only in its budget was served the first response
    (x-orca-cache: HIT). The Anthropic surface sends max_tokens on every
    request, so the collision was reachable in normal use."""
    client, fake, key = native_client

    body = {
        "model": "gpt-4o-mini", "max_tokens": 16, "temperature": 0,
        "messages": [{"role": "user", "content": "cache probe"}],
    }
    first = await client.post("/v1/messages", json=body, headers={"x-api-key": key})
    assert first.status_code == 200
    assert first.headers["x-orca-cache"] == "MISS"

    # identical request → served from cache
    again = await client.post("/v1/messages", json=body, headers={"x-api-key": key})
    assert again.headers["x-orca-cache"] == "HIT"

    # same prompt, different budget → must NOT reuse the entry
    other = await client.post(
        "/v1/messages", json={**body, "max_tokens": 4096}, headers={"x-api-key": key},
    )
    assert other.headers["x-orca-cache"] == "MISS"


async def test_request_without_temperature_bypasses_the_cache(native_client):
    """Regression: the native translators only forward a temperature the
    client sent, and Claude Code never sends one — so the upstream samples
    at its 1.0 default. Caching that would replay one arbitrary sample to
    every later identical request (an agent's retries would get the same
    stale answer)."""
    client, fake, key = native_client

    body = {
        "model": "gpt-4o-mini", "max_tokens": 16,
        "messages": [{"role": "user", "content": "no temperature here"}],
    }
    first = await client.post("/v1/messages", json=body, headers={"x-api-key": key})
    second = await client.post("/v1/messages", json=body, headers={"x-api-key": key})
    assert first.headers["x-orca-cache"] == "BYPASS"
    assert second.headers["x-orca-cache"] == "BYPASS"
    assert fake.acompletion.call_count == 2, "both must reach the upstream"


async def test_streaming_message_start_carries_an_input_token_estimate(native_client):
    """The protocol reports the input count in message_start; 0 there made
    every streaming response understate usage to the SDK."""
    client, _, key = native_client
    r = await client.post("/v1/messages", json={
        "model": "gpt-4o-mini", "max_tokens": 16, "stream": True,
        "messages": [{"role": "user", "content": "hello there, how are you?"}],
    }, headers={"x-api-key": key})
    assert r.status_code == 200

    start = None
    for line in r.text.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
            if payload.get("type") == "message_start":
                start = payload
                break
    assert start is not None
    assert start["message"]["usage"]["input_tokens"] > 0


async def test_max_tokens_zero_is_native_400(native_client):
    client, _, key = native_client
    r = await client.post("/v1/messages", json={
        "model": "gpt-4o-mini", "max_tokens": 0,
        "messages": [{"role": "user", "content": "hi"}],
    }, headers={"x-api-key": key})
    assert r.status_code == 400
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "invalid_request_error"
    assert "max_tokens" in body["error"]["message"]


async def test_count_tokens_unexpected_error_stays_in_anthropic_envelope(native_client):
    """Defense-in-depth: a schema-valid but malformed body that explodes
    inside the translator (non-dict image source → AttributeError) must
    render the Anthropic error envelope, not FastAPI's default 500 body."""
    client, _, key = native_client
    r = await client.post("/v1/messages/count_tokens", json={
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": "not-a-dict"},
        ]}],
    }, headers={"x-api-key": key})
    assert r.status_code == 500
    body = r.json()
    assert body["type"] == "error"
    assert body["error"]["type"] == "api_error"
