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
    assert len(chunks) == 3
    # Concatenated content matches non-streaming path
    deltas = [c["choices"][0].get("delta", {}).get("content", "") for c in chunks]
    assert "".join(d for d in deltas if d) == "Hello world"
    # Internal _orca_meta must NOT be exposed in the SSE stream
    assert "_orca_meta" not in body


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
