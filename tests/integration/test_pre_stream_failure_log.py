# ruff: noqa: F811  (fixtures imported from sibling modules are re-bound as parameters)
"""A streaming request that fails BEFORE its first chunk must still be
logged (PR #64 round 4).

The blocking path logs from its `finally` and a mid-stream failure logs
from `_finalize`, but a failure at `client.acompletion(stream=True)` sat
between the two: the client was rendered a real 404/429/403 and the
RequestLog had no entry at all — the same upstream failure accounted for
when stream=false and vanishing when stream=true.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from tests.integration.test_anthropic_messages import (  # noqa: F401 (fixture)
    _messages_payload,
    native_client,
)

_GEMINI_PAYLOAD = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}


async def _log_rows() -> list[tuple[int, str | None, bool]]:
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    return [(r.status_code, r.error_type, r.is_streaming) for r in rows]


def _failing_router(fake, *, error_type: str, http_status: int = 422) -> None:
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "boom", http_status=http_status, error_type=error_type,
    ))


@pytest.mark.parametrize("error_type,expected_status", [
    ("model_not_found", 404),
    ("rate_limit_error", 429),
    ("no_providers_configured", 403),
])
async def test_anthropic_pre_stream_failure_is_logged(
    native_client, error_type, expected_status,
):
    client, fake, key = native_client
    _failing_router(fake, error_type=error_type)

    r = await client.post("/v1/messages", json=_messages_payload(stream=True),
                          headers={"x-api-key": key})
    assert r.status_code == expected_status, r.text
    # the row records the status the client actually received
    assert await _log_rows() == [(expected_status, error_type, True)]


async def test_gemini_pre_stream_failure_is_logged(native_client):
    client, fake, key = native_client
    _failing_router(fake, error_type="model_not_found")

    r = await client.post(
        "/v1beta/models/nope-1:streamGenerateContent?alt=sse",
        json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key},
    )
    assert r.status_code == 404, r.text
    assert await _log_rows() == [(404, "model_not_found", True)]


async def test_openai_pre_stream_failure_is_logged_with_the_engine_status(native_client):
    """No log_status on that surface, so the row keeps the engine's own
    status — but a row must exist there too."""
    client, fake, key = native_client
    _failing_router(fake, error_type="model_not_found")

    r = await client.post("/v1/chat/completions", json={
        "model": "nope-1", "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 422
    assert await _log_rows() == [(422, "model_not_found", True)]


async def test_successful_stream_still_logs_exactly_one_row(native_client):
    """The new pre-stream row must not duplicate the end-of-stream one."""
    client, _fake, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(stream=True),
                          headers={"x-api-key": key})
    assert r.status_code == 200
    rows = await _log_rows()
    assert len(rows) == 1
    assert rows[0][:2] == (200, None)
