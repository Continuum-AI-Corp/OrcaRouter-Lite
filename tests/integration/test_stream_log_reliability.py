"""Streaming chat completions log persistence and teardown resilience tests.

Validates that streaming completion request logs are reliably persisted to the database
even after the request-scoped dependency session (`get_db()`) has exited and closed.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import router_cache
from packages.auth.hashing import hash_api_key
from packages.db import session as session_mod
from packages.db.models.api_key import ApiKey
from packages.db.models.base import Base
from packages.db.models.request_log import RequestLog


@pytest.mark.asyncio
async def test_streaming_log_persistence_when_dependency_session_is_closed(monkeypatch):
    """Verify that streaming request logs are written to the database after get_db() dependency session closes.

    Root Cause (Issue #2): get_db() yields `db` and closes it when chat_completions returns
    StreamingResponse. _finalize() runs post-return during SSE stream output. Using a dedicated
    session from session_factory ensures the RequestLog is successfully saved despite `db` being closed.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Seed API key into isolated test database
    raw_key = "sk-orca-test123456789012345678901234"
    key_hash = hash_api_key(raw_key)
    async with factory() as s:
        s.add(
            ApiKey(
                id="key_streaming_test",
                workspace_id="default",
                name="test-key",
                key_hash=key_hash,
                key_prefix="sk-orca-....1234",
                is_active=True,
            )
        )
        await s.commit()

    # Set _session_factory for authentication middleware and _finalize()
    session_mod._session_factory = factory

    chunks = [
        {
            "id": "chatcmpl-stream-test",
            "object": "chat.completion.chunk",
            "model": "gpt-4o-mini",
            "created": int(time.time()),
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Test stream chunk"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            "_orca_meta": {"provider": "openai", "latency_ms": 10},
        }
    ]

    fake_client = AsyncMock()

    async def _stream_iter(chunk_list):
        for c in chunk_list:
            yield c

    fake_client.acompletion = AsyncMock(
        return_value=_stream_iter(chunks)
    )

    async def _fake_get_router(_session):
        return fake_client

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    from app.deps import get_db

    async def _override_get_db_that_closes_on_return():
        async with factory() as session:
            yield session
            # Dependency scope ends here when chat_completions returns StreamingResponse,
            # explicitly closing session before _finalize() runs!
            await session.close()

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db_that_closes_on_return

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {raw_key}"},
    ) as c:
        response = await c.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        )
        assert response.status_code == 200
        body_text = response.text
        assert "data: [DONE]" in body_text

    # Verify that the streaming request log WAS successfully written to DB via session_factory
    async with factory() as check_session:
        rows = (await check_session.execute(select(RequestLog))).scalars().all()

    assert len(rows) == 1, (
        f"Expected 1 RequestLog row for streaming completion, but found {len(rows)}. "
        "Streaming log failed to persist when request-scoped db session was closed."
    )
    log = rows[0]
    assert log.is_streaming is True
    assert log.input_tokens == 5
    assert log.output_tokens == 5
