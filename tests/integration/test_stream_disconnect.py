"""Test to verify clean teardown of sse() generator without RuntimeError on client disconnect."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import router_cache
from app.routes.chat import chat_completions
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext


@pytest.mark.asyncio
async def test_sse_generator_clean_teardown(monkeypatch):
    """Verify that calling aclose() on the sse generator closes cleanly without RuntimeError."""

    # Mock stream object that mimics a provider stream
    async def mock_stream():
        yield {"choices": [{"delta": {"content": "hello"}}]}
        await asyncio.sleep(10)  # simulate long stream
        yield {"choices": [{"delta": {"content": "world"}}]}

    stream_obj = mock_stream()
    fake_client = AsyncMock()
    fake_client.acompletion = AsyncMock(return_value=stream_obj)

    async def _fake_get_router(_session):
        return fake_client

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    body = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    kc = KeyContext(
        key_id="test_key",
        workspace_id="default",
        name="test",
        key_type="standard",
    )

    db_mock = AsyncMock()
    db_mock.add = MagicMock()  # Synchronous method on AsyncSession

    # Call the chat_completions endpoint handler
    response = await chat_completions(
        body=body,
        request=AsyncMock(),
        kc=kc,
        db=db_mock,
    )

    # Get the underlying async generator from StreamingResponse
    gen = response.body_iterator

    # Read the first chunk
    first_chunk = await gen.__anext__()
    assert "hello" in first_chunk

    # Simulate client disconnect / generator closing mid-stream
    # Must close cleanly without throwing RuntimeError or unhandled exceptions
    await gen.aclose()
