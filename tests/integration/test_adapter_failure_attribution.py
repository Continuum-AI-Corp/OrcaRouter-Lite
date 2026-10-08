# ruff: noqa: F811  (fixtures imported from sibling modules are re-bound as parameters)
"""An adapter fault mid-stream is OUR failure, not a client disconnect.

The adapter generator IS the response body, so when it raises, its cleanup
closes the engine's SSE generator — indistinguishable at the engine's
suspended yield from Starlette closing it because the client went away. The
row then said 499/client_disconnect while the client was told "Internal
server error", hiding every adapter regression in the analytics. The
transformers now ABORT the frame source (AdapterError) when they unwind on
their own exception, and the engine records that as 500/adapter_error.

The fault is induced the way it would really happen: a chunk the
transformer cannot handle (`choices` is a string, so `choices[0].get(...)`
raises inside it), not a wrapper around it.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

from sqlalchemy import select

from tests.integration.test_anthropic_messages import (  # noqa: F401 (fixture)
    _messages_payload,
    native_client,
)
from tests.integration.test_budget_enforcement import (  # noqa: F401
    _get_spent,
    _make_budgeted_key,
)

_GEMINI_PAYLOAD = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}


async def _log_rows() -> list[tuple[int, str | None, bool]]:
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    return [(r.status_code, r.error_type, r.is_streaming) for r in rows]


def _malformed_chunk_router(fake) -> None:
    """Engine emits a chunk whose `choices` is a string — well-formed SSE,
    but the transformers index into it and raise."""
    async def _stream():
        yield {"id": "chatcmpl-1", "model": "gpt-4o-mini", "choices": "boom"}

    async def _acompletion(**kwargs):
        assert kwargs.get("stream")
        return _stream()

    fake.acompletion = AsyncMock(side_effect=_acompletion)


async def test_anthropic_adapter_fault_is_logged_as_adapter_error(native_client):
    client, fake, key = native_client
    _malformed_chunk_router(fake)

    r = await client.post("/v1/messages", json=_messages_payload(stream=True),
                          headers={"x-api-key": key})
    assert r.status_code == 200
    # the client still gets a parseable native error event
    assert '"type":"api_error"' in r.text.replace(" ", "")
    await asyncio.sleep(0.1)
    # ...and the row blames us, not the caller
    assert await _log_rows() == [(500, "adapter_error", True)]


async def test_gemini_adapter_fault_is_logged_as_adapter_error(native_client):
    client, fake, key = native_client
    _malformed_chunk_router(fake)

    r = await client.post(
        "/v1beta/models/gpt-4o-mini:streamGenerateContent?alt=sse",
        json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key},
    )
    assert r.status_code == 200
    frames = [json.loads(line[len("data: "):]) for line in r.text.splitlines()
              if line.startswith("data: ")]
    assert frames[-1]["error"]["status"] == "INTERNAL"
    await asyncio.sleep(0.1)
    assert await _log_rows() == [(500, "adapter_error", True)]


async def test_a_real_client_disconnect_is_still_499(native_client):
    """The new abort path must not swallow the genuine disconnect case."""
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
        async with client.stream("POST", "/v1/messages",
                                 json=_messages_payload(stream=True),
                                 headers={"x-api-key": key}) as response:
            async for _ in response.aiter_lines():
                pass
    except Exception:
        pass
    await asyncio.sleep(0.2)

    assert slow.closed is True
    assert await _log_rows() == [(499, "client_disconnect", True)]


# ── Budget settlement on an adapter fault ──────────────────────────────
# The adapter IS the response body, so its failure unwinds through the
# engine's SSE generator. The engine must settle that request on what it
# delivered — leaving the settlement "unknown" would charge a budgeted key
# its entire remaining lifetime budget for a bug of ours.

_BAD_CHUNK = {
    "id": "chatcmpl-2", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
    "created": int(time.time()), "choices": "boom",
}


def _content_chunk(text: str) -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
        "created": int(time.time()),
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }


def _budget_stream_router(fake, chunks) -> None:
    async def _acompletion(**kwargs):
        assert kwargs.get("stream")

        async def _gen():
            for c in chunks:
                yield c

        return _gen()

    fake.acompletion = AsyncMock(side_effect=_acompletion)


async def _log_row_for(api_key_id: str):
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        return (
            await s.execute(select(RequestLog).where(RequestLog.api_key_id == api_key_id))
        ).scalars().one()


async def test_budgeted_adapter_fault_after_content_charges_delivery_not_remaining(
    native_client,
):
    client, fake, _root = native_client
    from packages.db import session as session_mod

    factory = session_mod._session_factory
    # 100 cents = 1_000_000 microcents of lifetime budget.
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)
    delivered = "the quick brown fox jumps over the lazy dog. " * 200
    _budget_stream_router(fake, [_content_chunk(delivered), _BAD_CHUNK])

    r = await client.post(
        "/v1/messages", json=_messages_payload(stream=True), headers={"x-api-key": key},
    )
    assert r.status_code == 200
    await asyncio.sleep(0.1)

    assert await _log_rows() == [(500, "adapter_error", True)]
    row = await _log_row_for(key_id)
    spent = await _get_spent(factory, key_id)
    assert spent == row.cost_microcents  # charged == accounted
    assert 0 < spent < 1_000_000  # priced, not the whole remaining budget


async def test_budgeted_adapter_fault_before_content_charges_nothing(native_client):
    """A fault with nothing delivered cost nothing, so it must bill nothing."""
    client, fake, _root = native_client
    from packages.db import session as session_mod

    factory = session_mod._session_factory
    key, key_id = await _make_budgeted_key(factory, budget_limit_cents=100)
    _budget_stream_router(fake, [_BAD_CHUNK])

    r = await client.post(
        "/v1/messages", json=_messages_payload(stream=True), headers={"x-api-key": key},
    )
    assert r.status_code == 200
    await asyncio.sleep(0.1)

    assert await _log_rows() == [(500, "adapter_error", True)]
    assert await _get_spent(factory, key_id) == 0
