# ruff: noqa: F811  (fixtures imported from sibling modules are re-bound as parameters)
"""RequestLog status == delivered status on the native surfaces (PR #64
round 12), including the streaming paths, plus the empty-turn rule.

`execute_chat(log_status=...)` corrects the engine's generic status to the
one the surface actually puts on the wire. Round 11 wired it into the
blocking path only, and it used `native_status`, which leaves a generic
upstream 5xx at 503 even though the Anthropic envelope delivers 500.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from tests.integration.test_anthropic_messages import (  # noqa: F401 (fixture)
    _messages_payload,
    native_client,
)

_GEMINI_PAYLOAD = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}


async def _log_rows() -> list[tuple[int, str | None]]:
    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        rows = (await s.execute(select(RequestLog))).scalars().all()
    return [(r.status_code, r.error_type) for r in rows]


def _erroring_stream(error_type: str):
    """A stream that yields one chunk and then raises the LiteLLM exception
    the engine translates into `error_type` — the engine runs the failure
    through `_translate_error`, so a real provider exception is what
    produces the in-band error frame under test."""
    import litellm

    exceptions = {
        "model_not_found": lambda: litellm.NotFoundError(
            message="boom", model="m", llm_provider="openai"),
        "rate_limit_error": lambda: litellm.RateLimitError(
            message="boom", model="m", llm_provider="openai"),
    }

    async def _stream():
        yield {
            "id": "chatcmpl-1", "object": "chat.completion.chunk",
            "model": "gpt-4o-mini", "created": int(time.time()),
            "choices": [{"index": 0, "delta": {"content": "Hi"}, "finish_reason": None}],
        }
        raise exceptions[error_type]()

    return _stream()


# ── streaming: the status the client saw is the status we persist ──


async def test_gemini_aggregate_stream_logs_the_delivered_status(native_client):
    """Without alt=sse nothing has been sent when the stream fails, so the
    route renders a genuine 404 — the row must not say 503."""
    client, fake, key = native_client
    fake.acompletion = AsyncMock(side_effect=lambda **kw: _erroring_stream("model_not_found"))

    r = await client.post(
        "/v1beta/models/nope-1:streamGenerateContent",
        json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["status"] == "NOT_FOUND"
    assert await _log_rows() == [(404, "model_not_found")]


async def test_gemini_sse_stream_logs_the_surface_status(native_client):
    """alt=sse delivers the same failure class as an in-band error chunk;
    the row records that class (429), not the engine's generic 503."""
    client, fake, key = native_client
    fake.acompletion = AsyncMock(side_effect=lambda **kw: _erroring_stream("rate_limit_error"))

    r = await client.post(
        "/v1beta/models/gpt-4o-mini:streamGenerateContent?alt=sse",
        json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key},
    )
    assert r.status_code == 200
    frames = [json.loads(line[len("data: "):]) for line in r.text.splitlines()
              if line.startswith("data: ")]
    assert frames[-1]["error"]["code"] == 429
    assert await _log_rows() == [(429, "rate_limit_error")]


async def test_anthropic_stream_logs_the_surface_status(native_client):
    client, fake, key = native_client
    fake.acompletion = AsyncMock(side_effect=lambda **kw: _erroring_stream("model_not_found"))

    r = await client.post("/v1/messages", json=_messages_payload(stream=True),
                          headers={"x-api-key": key})
    assert r.status_code == 200
    assert "not_found_error" in r.text
    assert await _log_rows() == [(404, "model_not_found")]


async def test_openai_streaming_surface_still_logs_503(native_client):
    """No log_status on that surface — its row keeps the engine status."""
    client, fake, key = native_client
    fake.acompletion = AsyncMock(side_effect=lambda **kw: _erroring_stream("model_not_found"))

    r = await client.post("/v1/chat/completions", json={
        "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    assert await _log_rows() == [(503, "model_not_found")]


# ── blocking: a generic upstream 5xx is delivered as 500, not 503 ──


async def test_anthropic_blocking_generic_upstream_error_logs_500(native_client):
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "provider exploded", http_status=503, error_type="upstream_error",
    ))
    r = await client.post("/v1/messages", json=_messages_payload(),
                          headers={"x-api-key": key})
    assert r.status_code == 500
    assert r.json()["error"]["type"] == "api_error"
    assert await _log_rows() == [(500, "upstream_error")]


async def test_gemini_blocking_generic_upstream_error_logs_503(native_client):
    """Google's envelope carries 503 as-is (UNAVAILABLE), so the row does too."""
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "provider exploded", http_status=503, error_type="upstream_error",
    ))
    r = await client.post("/v1beta/models/gpt-4o-mini:generateContent",
                          json=_GEMINI_PAYLOAD, headers={"x-goog-api-key": key})
    assert r.status_code == 503
    assert r.json()["error"]["status"] == "UNAVAILABLE"
    assert await _log_rows() == [(503, "upstream_error")]


# ── empty user turns are rejected, never silently dropped ──


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": []}],
    [{"role": "user", "content": "hi"},
     {"role": "assistant", "content": "ok"},
     {"role": "user", "content": []}],
    [{"role": "user", "content": [{"type": "thinking", "thinking": "hmm"}]}],
])
async def test_anthropic_empty_user_turn_is_native_400(native_client, messages):
    client, fake, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(messages=messages),
                          headers={"x-api-key": key})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request_error"
    fake.acompletion.assert_not_awaited()


async def test_gemini_empty_user_turn_is_native_400(native_client):
    client, fake, key = native_client
    r = await client.post(
        "/v1beta/models/gpt-4o-mini:generateContent",
        json={"contents": [
            {"role": "user", "parts": [{"text": "hi"}]},
            {"role": "user", "parts": []},
        ]},
        headers={"x-goog-api-key": key},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["status"] == "INVALID_ARGUMENT"
    fake.acompletion.assert_not_awaited()


async def test_well_formed_turns_still_reach_the_engine(native_client):
    """The rejection must not catch a user turn that carries only tool
    results (it translates to role:"tool" messages, not a user message)."""
    client, fake, key = native_client
    r = await client.post("/v1/messages", json=_messages_payload(messages=[
        {"role": "user", "content": "what is the weather"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "get_weather", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "sunny"}]},
    ]), headers={"x-api-key": key})
    assert r.status_code == 200, r.text
    sent = fake.acompletion.call_args.kwargs["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "tool"]
