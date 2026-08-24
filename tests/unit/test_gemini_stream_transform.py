"""Gemini streaming transformer — pure-transformer unit tests (slice S8).

Feeds synthetic OpenAI chunk dicts and asserts the GenerateContentResponse
chunk stream: text deltas pass through one-to-one, tool-call fragments are
buffered into a single complete functionCall part, and the final chunk
carries finishReason + usageMetadata.
"""

from __future__ import annotations

import pytest

from app.protocols.gemini import stream_chunks
from app.protocols.sse import iter_openai_frames


async def _agen(items):
    for item in items:
        yield item


async def _collect(frames: list[dict]) -> list[dict]:
    return [c async for c in stream_chunks(_agen(frames))]


def _text_chunk(text: str) -> dict:
    return {
        "id": "chatcmpl-1", "model": "gemini-1.5-flash",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }


_FINISH_CHUNK = {
    "id": "chatcmpl-1", "model": "gemini-1.5-flash",
    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
}

_USAGE_CHUNK = {
    "id": "chatcmpl-1", "model": "gemini-1.5-flash",
    "choices": [],
    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
}


async def test_text_deltas_stream_one_to_one_with_final_usage_chunk():
    chunks = await _collect([
        _text_chunk("Hello"), _text_chunk(" world"), _FINISH_CHUNK, _USAGE_CHUNK,
    ])
    assert len(chunks) == 3
    texts = [c["candidates"][0]["content"]["parts"][0]["text"] for c in chunks[:2]]
    assert texts == ["Hello", " world"]
    for c in chunks[:2]:
        assert "finishReason" not in c["candidates"][0]
        assert c["modelVersion"] == "gemini-1.5-flash"
        assert c["responseId"] == "chatcmpl-1"

    final = chunks[-1]
    assert final["candidates"][0]["finishReason"] == "STOP"
    assert final["usageMetadata"] == {
        "promptTokenCount": 4, "candidatesTokenCount": 2, "totalTokenCount": 6,
    }


async def test_tool_call_fragments_buffer_into_single_complete_part():
    frames = [
        {
            "id": "chatcmpl-1", "model": "gemini-1.5-flash",
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "id": "call_1",
                "function": {"name": "get_weather", "arguments": '{"ci'},
            }]}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "model": "gemini-1.5-flash",
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": 'ty": "SF"}'},
            }]}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "model": "gemini-1.5-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        },
        _USAGE_CHUNK,
    ]
    chunks = await _collect(frames)
    # exactly one functionCall chunk (complete, never partial) + final chunk
    assert len(chunks) == 2
    parts = chunks[0]["candidates"][0]["content"]["parts"]
    assert parts == [{"functionCall": {"name": "get_weather", "args": {"city": "SF"}}}]
    assert chunks[-1]["candidates"][0]["finishReason"] == "STOP"


async def test_length_finish_maps_to_max_tokens():
    finish = {
        "id": "chatcmpl-1", "model": "gemini-1.5-flash",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}],
    }
    chunks = await _collect([_text_chunk("hi"), finish])
    assert chunks[-1]["candidates"][0]["finishReason"] == "MAX_TOKENS"


async def test_engine_error_frame_becomes_google_error_chunk():
    chunks = await _collect([
        _text_chunk("partial"),
        {"error": {"message": "boom", "type": "upstream_error"}},
    ])
    assert chunks[-1] == {
        "error": {"code": 503, "message": "boom", "status": "UNAVAILABLE"},
    }
    # no final finishReason chunk after an error
    assert all("usageMetadata" not in c for c in chunks)


@pytest.mark.parametrize("etype,code,status", [
    ("rate_limit_error", 429, "RESOURCE_EXHAUSTED"),
    ("model_not_found", 404, "NOT_FOUND"),
    ("context_length_exceeded", 400, "INVALID_ARGUMENT"),
    # OUR provider credential — permanent, must not present as retryable.
    ("upstream_auth_error", 403, "PERMISSION_DENIED"),
    ("upstream_timeout", 503, "UNAVAILABLE"),
    ("something_unknown", 500, "INTERNAL"),
    (None, 500, "INTERNAL"),
])
async def test_engine_error_type_maps_to_google_status(etype, code, status):
    """The engine's translated error type must surface as the matching
    Google status — client retry/backoff keys off it (a provider rate
    limit presented as INTERNAL would not be backed off)."""
    err: dict = {"message": "boom"}
    if etype is not None:
        err["type"] = etype
    chunks = await _collect([{"error": err}])
    assert chunks == [{"error": {"code": code, "message": "boom", "status": status}}]


async def test_error_frame_drains_engine_source_instead_of_closing_it():
    """Regression: after a mid-stream upstream error the engine emits an
    error frame + [DONE] and then completes, logging 503 + the real error
    type. The transformer must DRAIN the frame source to that natural
    completion — aclose() raises GeneratorExit at the engine's suspended
    yield, which its disconnect branch mislogs as a 499 client disconnect."""
    state = {"exit": None}

    async def engine_sse():
        try:
            yield 'data: {"error": {"message": "boom", "type": "rate_limit_error"}}\n\n'
            yield "data: [DONE]\n\n"
            state["exit"] = "completed"
        except GeneratorExit:
            state["exit"] = "generator_exit"
            raise

    chunks = [c async for c in stream_chunks(iter_openai_frames(engine_sse()))]
    assert chunks[-1]["error"]["status"] == "RESOURCE_EXHAUSTED"
    assert state["exit"] == "completed"
