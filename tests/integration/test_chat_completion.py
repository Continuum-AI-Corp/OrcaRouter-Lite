"""End-to-end test of /v1/chat/completions with the LiteLLM client mocked.

We don't exercise litellm — that's its own library, with its own tests.
Lite's responsibility is the surrounding flow: auth → router lookup →
request log writeback → OpenAI-format response.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
async def chat_client(tmp_sqlite_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")

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

    # Mock the router so we don't touch real LLM providers.
    from app import router_cache
    router_cache.invalidate_router()

    fake_client = AsyncMock()
    fake_client.acompletion = AsyncMock(
        return_value={
            "id": "chatcmpl-test-123",
            "model": "gpt-4o-mini",
            "object": "chat.completion",
            "created": int(time.time()),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            "_orca_meta": {
                "provider": "openai",
                "litellm_model": "openai/gpt-4o-mini",
                "latency_ms": 42,
            },
        }
    )

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


async def test_chat_completion_returns_openai_format(chat_client):
    client, _fake = chat_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "Hello!"
    assert body["usage"]["total_tokens"] == 7


async def test_chat_completion_invokes_router_with_normalized_request(chat_client):
    client, fake = chat_client
    await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.2,
        },
    )
    fake.acompletion.assert_awaited_once()
    call = fake.acompletion.await_args
    assert call.kwargs["model"] == "gpt-4o-mini"
    assert call.kwargs["temperature"] == 0.2
    assert call.kwargs["messages"][0]["content"] == "hi"


async def test_chat_completion_forwards_parallel_tool_calls_false(chat_client):
    """Regression for #124: `parallel_tool_calls=false` must survive the
    schema and `model_dump(exclude_none=True)` into the LiteLLM call.

    The field is falsy, so a missing schema declaration (or an accidental
    truthy filter) silently drops it and the upstream still returns
    parallel tool calls. False is not None, so exclude_none must keep it.
    """
    client, fake = chat_client
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_time",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "weather in Tokyo and the time?"}],
            "tools": tools,
            "parallel_tool_calls": False,
        },
    )
    assert r.status_code == 200, r.text
    fake.acompletion.assert_awaited_once()
    call_kwargs = fake.acompletion.await_args.kwargs
    assert "parallel_tool_calls" in call_kwargs, (
        "parallel_tool_calls=False was stripped before the LiteLLM call"
    )
    assert call_kwargs["parallel_tool_calls"] is False
    assert call_kwargs["tools"] == tools


async def test_chat_completion_omits_parallel_tool_calls_when_unset(chat_client):
    """Absent `parallel_tool_calls` must not be injected as None/False."""
    client, fake = chat_client
    await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    call_kwargs = fake.acompletion.await_args.kwargs
    assert "parallel_tool_calls" not in call_kwargs


async def test_chat_completion_writes_request_log(chat_client):
    client, _fake = chat_client
    await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    log = rows[0]
    assert log.workspace_id == "default"
    assert log.model_requested == "gpt-4o-mini"
    assert log.model_resolved == "gpt-4o-mini"
    assert log.provider == "openai"
    assert log.input_tokens == 5
    assert log.output_tokens == 2
    assert log.status_code == 200
    assert log.fallback_level == 0


async def test_chat_completion_validation_error_for_empty_messages(chat_client):
    client, _ = chat_client
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": []},
    )
    assert r.status_code == 422
    assert r.json()["error"]["type"] == "validation_error"


async def test_chat_completion_blocking_httpexception_logs_real_status(chat_client):
    """The blocking path's `except HTTPException` arm records the raised status
    instead of leaving the handler-local 200, so the finally cannot write a
    success-shaped row for a failed request.

    The exception is injected directly: the adapter translates every upstream
    failure into UpstreamProviderError, so this shape is not reachable from real
    traffic today. The test pins the handler's arm logic, not a live bug.
    """
    from fastapi import HTTPException

    client, fake = chat_client
    fake.acompletion = AsyncMock(
        side_effect=HTTPException(status_code=429, detail="local key rate limited")
    )

    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 429

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        log = (await s.execute(select(RequestLog))).scalars().one()
    assert log.status_code == 429
    assert log.cost_microcents == 0


async def test_chat_completion_logs_active_strategy(chat_client):
    """RequestLog.routing_strategy reflects the configured strategy, not a
    hardcoded value, and the same strategy is echoed in the response header."""
    client, fake = chat_client
    # Bolt the strategy onto the mock so chat.py reads it like a real client.
    fake.strategy = "cheapest"
    fake.preferred_models = []

    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200
    assert r.headers.get("x-orca-routing-strategy") == "cheapest"

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        log = (await s.execute(select(RequestLog))).scalars().one()
    assert log.routing_strategy == "cheapest"


async def test_chat_completion_no_fallback_header_on_local_hit(chat_client):
    """Local BYOK success must not look like a hosted bypass."""
    client, _fake = chat_client
    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200
    assert "x-orca-fallback" not in r.headers


async def test_chat_completion_signals_hosted_fallback_after_local_429(chat_client):
    """Issue #140: hosted serving a model the local key covers must set
    `x-orca-fallback: true` and record orcarouter + fallback_level=1 so
    the dashboard can tell BYOK was bypassed (typically after a 429
    cooldown) instead of looking like a normal local completion.
    """
    client, fake = chat_client
    fake.acompletion.return_value = {
        "id": "chatcmpl-hosted-fb",
        "model": "gpt-4o-mini",
        "object": "chat.completion",
        "created": int(time.time()),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "from hosted"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        "_orca_meta": {
            "provider": "orcarouter",
            "fallback": True,
            "latency_ms": 88,
        },
    }

    r = await client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("x-orca-fallback") == "true"
    assert r.headers.get("x-orca-resolved-model") == "gpt-4o-mini"
    # Internal meta must not leak onto the OpenAI wire body.
    assert "_orca_meta" not in r.json()

    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        log = (await s.execute(select(RequestLog))).scalars().one()
    assert log.provider == "orcarouter"
    assert log.fallback_level == 1
    assert log.model_resolved == "gpt-4o-mini"
