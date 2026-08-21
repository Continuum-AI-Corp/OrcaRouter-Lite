"""Gemini streaming transformer — pure-transformer unit tests (slice S8).

Feeds synthetic OpenAI chunk dicts and asserts the GenerateContentResponse
chunk stream: text deltas pass through one-to-one, tool-call fragments are
buffered into a single complete functionCall part, and the final chunk
carries finishReason + usageMetadata.
"""

from __future__ import annotations

from app.protocols.gemini import stream_chunks


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
        "error": {"code": 500, "message": "boom", "status": "INTERNAL"},
    }
    # no final finishReason chunk after an error
    assert all("usageMetadata" not in c for c in chunks)
