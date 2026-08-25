"""Disconnect in the window between the engine's mid-stream error frame and
the native adapter's error event/chunk.

The adapter is suspended at that yield while the event is in flight; if the
client goes away right then, the adapter is closed at the yield. Whatever
path that takes into the engine, the RequestLog row must record the real
upstream failure (503 + translated error type) — never a 499
client_disconnect, which would erase the true cause from analytics. Real
engine, real SQLite writeback, mocked upstream stream.

This is an end-to-end INVARIANT check, not a regression test: the engine's
error-path yields live inside its `except Exception` handler, so even a
forwarded close there reaches its `finally` with the 503 state intact. What
the pre-yield drain changes — the engine completing naturally instead of
being closed — is pinned down by the unit tests
`test_close_at_the_error_event_still_drains_the_engine_source` (Anthropic)
and `test_close_at_the_error_chunk_still_drains_the_engine_source` (Gemini),
which fail on the old ordering.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from packages.db.models.request_log import RequestLog


class _UpstreamExploded(Exception):
    pass


async def _failing_stream():
    yield {
        "id": "chatcmpl-1", "model": "gpt-4o-mini",
        "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}],
    }
    raise _UpstreamExploded("upstream exploded mid-stream")


@pytest.fixture
async def engine_with_failing_upstream(tmp_sqlite_url, monkeypatch):
    """(execute_chat args, session factory) with a router whose stream
    raises after one chunk, and a real DB the engine's writeback lands in."""
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(session_mod, "_session_factory", factory)

    from app import router_cache

    fake = AsyncMock()

    async def _acompletion(**kwargs):
        assert kwargs.get("stream")
        return _failing_stream()

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from app.schemas import ChatCompletionRequest
    from packages.auth.types import KeyContext

    body = ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}], stream=True,
    )
    kc = KeyContext(key_id="k", workspace_id="default", name="t", key_type="standard")
    yield (body, kc), factory

    await engine.dispose()


async def _rows(factory) -> list[RequestLog]:
    async with factory() as s:
        return list((await s.execute(select(RequestLog))).scalars().all())


async def test_anthropic_close_at_error_event_logs_the_upstream_error(engine_with_failing_upstream):
    (body, kc), factory = engine_with_failing_upstream
    from app.protocols.anthropic import stream_events
    from app.protocols.sse import OpenAIFrameStream
    from app.routes.chat import execute_chat

    inner = await execute_chat(body, kc, AsyncMock())
    events = stream_events(OpenAIFrameStream(inner.body_iterator))
    names = []
    async for ev in events:
        names.append(ev.splitlines()[0][len("event: "):])
        if names[-1] == "error":
            break
    await events.aclose()  # client gone while the error event was in flight

    assert names[:2] == ["message_start", "content_block_start"]
    rows = await _rows(factory)
    assert len(rows) == 1
    assert (rows[0].status_code, rows[0].error_type) == (503, "upstream_error")
    assert rows[0].is_streaming is True


async def test_gemini_close_at_error_chunk_logs_the_upstream_error(engine_with_failing_upstream):
    (body, kc), factory = engine_with_failing_upstream
    from app.protocols.gemini import stream_chunks
    from app.protocols.sse import OpenAIFrameStream
    from app.routes.chat import execute_chat

    inner = await execute_chat(body, kc, AsyncMock())
    chunks = stream_chunks(OpenAIFrameStream(inner.body_iterator))
    async for chunk in chunks:
        if "error" in chunk:
            assert chunk["error"]["status"] == "UNAVAILABLE"
            break
    await chunks.aclose()  # client gone while the error chunk was in flight

    rows = await _rows(factory)
    assert len(rows) == 1
    assert (rows[0].status_code, rows[0].error_type) == (503, "upstream_error")
