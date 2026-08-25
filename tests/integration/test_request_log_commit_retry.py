"""Streaming RequestLog durability — the commit-retry policy in `_finalize`.

The streaming row is the only record of a stream's tokens and cost (the
engine persists them nowhere else), so a commit that fails outright must
be retried on a fresh session rather than dropped; a failure AFTER the
commit returned (session close) must NOT be retried, or the row would be
inserted twice. Real app + mocked router + a real SQLite DB whose session
class is rigged to fail on demand.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models.request_log import RequestLog


class _RiggedSession(AsyncSession):
    """AsyncSession whose commit()/close() fail on demand — but only for a
    session that is persisting a RequestLog, so the auth middleware and
    seeding (which share the factory) are never disturbed."""

    commit_failures_left = 0
    close_failures_left = 0
    lost_acks_left = 0  # COMMIT lands, but the call raises as if the connection dropped
    commits_attempted = 0

    def _adding_request_log(self) -> bool:
        return any(isinstance(o, RequestLog) for o in self.sync_session.new)

    async def commit(self):
        if self._adding_request_log():
            type(self).commits_attempted += 1
            if type(self).commit_failures_left > 0:
                type(self).commit_failures_left -= 1
                raise OperationalError("COMMIT", {}, Exception("database is locked"))
            if type(self).lost_acks_left > 0:
                type(self).lost_acks_left -= 1
                await super().commit()
                raise OperationalError("COMMIT", {}, Exception("connection reset before ack"))
            self._committed_log = True
        return await super().commit()

    async def close(self):
        await super().close()
        if getattr(self, "_committed_log", False) and type(self).close_failures_left > 0:
            type(self).close_failures_left -= 1
            raise RuntimeError("connection reset during session close")


def _chunks() -> list[dict]:
    now = int(time.time())
    return [
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {"content": "Hello"},
                         "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": now,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        },
    ]


async def _stream_iter():
    for c in _chunks():
        yield c


@pytest.fixture
async def rigged_client(tmp_sqlite_url, monkeypatch):
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
    factory = async_sessionmaker(engine, class_=_RiggedSession, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from app import router_cache
    router_cache.invalidate_router()

    fake = AsyncMock()

    async def _acompletion(**kwargs):
        assert kwargs.get("stream")
        return _stream_iter()

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    # No real backoff in tests — the policy, not the wall-clock, is under test.
    from app.routes import chat as chat_mod
    monkeypatch.setattr(chat_mod, "_LOG_COMMIT_BACKOFF_S", (0.0, 0.0))

    _RiggedSession.commit_failures_left = 0
    _RiggedSession.close_failures_left = 0
    _RiggedSession.lost_acks_left = 0
    _RiggedSession.commits_attempted = 0

    from app.main import create_app
    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        yield c, factory

    await engine.dispose()
    session_mod._session_factory = None


async def _rows(factory) -> list[RequestLog]:
    from sqlalchemy import select

    async with factory() as s:
        return list((await s.execute(select(RequestLog))).scalars().all())


async def _stream(client) -> str:
    r = await client.post("/v1/chat/completions", json={
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })
    assert r.status_code == 200
    return r.text


async def test_transient_commit_failure_is_retried_and_the_row_lands_once(rigged_client):
    """A commit that fails outright persisted nothing, so it is retried on a
    fresh session — and the row lands exactly once, with the stream's real
    token counts."""
    client, factory = rigged_client
    _RiggedSession.commit_failures_left = 1

    body = await _stream(client)
    assert "data: [DONE]" in body

    rows = await _rows(factory)
    assert len(rows) == 1
    assert (rows[0].status_code, rows[0].input_tokens, rows[0].output_tokens) == (200, 4, 2)
    assert rows[0].is_streaming is True
    assert _RiggedSession.commits_attempted == 2


async def test_persistent_commit_failure_gives_up_after_bounded_attempts(rigged_client):
    """The retries are bounded (they hold the already-[DONE] stream open)
    and the failure is reported; the client-visible stream is unaffected."""
    from structlog.testing import capture_logs

    client, factory = rigged_client
    _RiggedSession.commit_failures_left = 99

    with capture_logs() as logs:
        body = await _stream(client)
    assert "data: [DONE]" in body

    assert await _rows(factory) == []
    assert _RiggedSession.commits_attempted == 3  # len(_LOG_COMMIT_BACKOFF_S) + 1
    failed = [e for e in logs if e["event"] == "request_log_commit_failed"]
    assert [e["attempts"] for e in failed] == [3]


async def test_failure_after_a_successful_commit_is_not_retried(rigged_client):
    """The session-close failure arrives AFTER the commit returned: the row
    is already persisted, so a retry would insert it twice."""
    client, factory = rigged_client
    _RiggedSession.close_failures_left = 1

    body = await _stream(client)
    assert "data: [DONE]" in body

    assert len(await _rows(factory)) == 1
    assert _RiggedSession.commits_attempted == 1


async def test_lost_commit_ack_does_not_double_insert(rigged_client):
    """PostgreSQL-style lost ack: the COMMIT landed but the call raised. The
    retry must find the row by trace_id and insert nothing — one row, one
    trace_id, not two rows with different ids."""
    client, factory = rigged_client
    _RiggedSession.lost_acks_left = 1

    body = await _stream(client)
    assert "data: [DONE]" in body

    rows = await _rows(factory)
    assert len(rows) == 1
    assert rows[0].status_code == 200


async def test_retry_backoff_does_not_inflate_latency(rigged_client, monkeypatch):
    """latency_ms is measured once, before the first attempt: a failed
    commit plus 0.3 s of backoff must not show up as model latency."""
    from app.routes import chat as chat_mod
    monkeypatch.setattr(chat_mod, "_LOG_COMMIT_BACKOFF_S", (0.3,))
    client, factory = rigged_client
    _RiggedSession.commit_failures_left = 1

    await _stream(client)

    rows = await _rows(factory)
    assert len(rows) == 1
    assert rows[0].latency_ms < 250, rows[0].latency_ms


async def test_fallback_session_is_rolled_back_before_a_retry(monkeypatch):
    """Without a session factory (unit-style callers) the request-scoped
    session is reused: a failed commit leaves it in a failed transaction,
    so the retry must roll it back first — and add a FRESH row object, not
    re-add the one whose flush failed."""
    from app import router_cache
    from app.routes import chat as chat_mod
    from app.schemas import ChatCompletionRequest
    from packages.auth.types import KeyContext
    from packages.db import session as session_mod

    monkeypatch.setattr(session_mod, "_session_factory", None)
    monkeypatch.setattr(chat_mod, "_LOG_COMMIT_BACKOFF_S", (0.0,))

    fake = AsyncMock()

    async def _acompletion(**kwargs):
        return _stream_iter()

    fake.acompletion = AsyncMock(side_effect=_acompletion)

    async def _fake_get_router(_session):
        return fake

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=[RuntimeError("database is locked"), None])
    db.scalar = AsyncMock(return_value=None)  # trace_id lookup on retry: not there

    body = ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}], stream=True,
    )
    kc = KeyContext(key_id="k", workspace_id="default", name="t", key_type="standard")
    response = await chat_mod.execute_chat(body, kc, db)
    frames = [f async for f in response.body_iterator]
    assert frames[-1] == "data: [DONE]\n\n"

    assert db.commit.await_count == 2
    db.rollback.assert_awaited_once()
    assert db.add.call_count == 2
    first, second = (c.args[0] for c in db.add.call_args_list)
    assert first is not second
    assert (first.id, first.trace_id) == (second.id, second.trace_id)
    assert (second.input_tokens, second.output_tokens) == (4, 2)
    db.scalar.assert_awaited_once()
