"""Gemini streaming transformer — pure-transformer unit tests (slice S8).

Feeds synthetic OpenAI chunk dicts and asserts the GenerateContentResponse
chunk stream: text deltas pass through one-to-one, tool-call fragments are
buffered into a single complete functionCall part, and the final chunk
carries finishReason + usageMetadata.
"""

from __future__ import annotations

import pytest

from app.protocols.gemini import stream_chunks
from app.protocols.sse import OpenAIFrameStream


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

    chunks = [c async for c in stream_chunks(OpenAIFrameStream(engine_sse()))]
    assert chunks[-1]["error"]["status"] == "RESOURCE_EXHAUSTED"
    assert state["exit"] == "completed"


async def test_final_chunk_reaches_the_client_before_the_engine_writeback():
    """Ordering regression: resuming the engine past [DONE] runs its
    RequestLog commit, which must not sit between the last content chunk
    and the terminal finishReason chunk."""
    order: list[str] = []

    async def engine_sse():
        yield 'data: {"id":"c1","model":"m","choices":[{"index":0,' \
              '"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n'
        yield "data: [DONE]\n\n"
        order.append("engine_writeback")

    async for chunk in stream_chunks(OpenAIFrameStream(engine_sse())):
        order.append(
            "final" if "usageMetadata" in chunk else "content"
        )

    assert order == ["content", "final", "engine_writeback"]


# ── part ordering: text ↔ function calls ──


def _tool_fragment(index: int, args: str, name: str | None = None) -> dict:
    tcd: dict = {"index": index, "function": {"arguments": args}}
    if name:
        tcd["function"]["name"] = name
    return {
        "id": "chatcmpl-1", "model": "gemini-1.5-flash",
        "choices": [{"index": 0, "delta": {"tool_calls": [tcd]}, "finish_reason": None}],
    }


def _part_kinds(chunks: list[dict]) -> list[str]:
    kinds = []
    for c in chunks:
        for cand in c.get("candidates") or []:
            for p in cand["content"]["parts"]:
                kinds.append("functionCall" if "functionCall" in p else "text")
    return kinds


async def test_text_after_a_function_call_is_delivered_after_the_call_part():
    """Regression: buffered functionCall parts were flushed only at
    end-of-stream while text passed through immediately, so text the model
    produced AFTER the call reached the client BEFORE it."""
    chunks = await _collect([
        _tool_fragment(0, '{"ci', name="get_weather"),
        _tool_fragment(0, 'ty": "SF"}'),
        _text_chunk("Checking."),
        _FINISH_CHUNK,
        _USAGE_CHUNK,
    ])
    assert _part_kinds(chunks) == ["functionCall", "text"]
    fc = chunks[0]["candidates"][0]["content"]["parts"][0]["functionCall"]
    assert fc == {"name": "get_weather", "args": {"city": "SF"}}
    assert chunks[-1]["candidates"][0]["finishReason"] == "STOP"


async def test_function_call_between_two_text_runs_keeps_the_model_order():
    chunks = await _collect([
        _text_chunk("A"),
        _tool_fragment(0, '{"x": 1}', name="f"),
        _text_chunk("B"),
        _FINISH_CHUNK,
    ])
    assert _part_kinds(chunks) == ["text", "functionCall", "text"]
    texts = [p["text"] for c in chunks for cand in c.get("candidates") or []
             for p in cand["content"]["parts"] if "text" in p]
    assert texts == ["A", "B"]


async def test_text_between_argument_fragments_of_one_call_does_not_split_it():
    """A text delta between two argument fragments of the same call must not
    flush the half-built call — that would emit functionCall{args: {}} (the
    parse failure is swallowed) plus a nameless second call. It waits for
    end-of-stream and comes out whole."""
    chunks = await _collect([
        _tool_fragment(0, '{"ci', name="get_weather"),
        _text_chunk("thinking..."),
        _tool_fragment(0, 'ty": "SF"}'),
        _FINISH_CHUNK,
    ])
    assert _part_kinds(chunks) == ["text", "functionCall"]
    calls = [p["functionCall"] for c in chunks for cand in c.get("candidates") or []
             for p in cand["content"]["parts"] if "functionCall" in p]
    assert calls == [{"name": "get_weather", "args": {"city": "SF"}}]


async def test_close_at_the_error_chunk_still_drains_the_engine_source():
    """Mirror of the Anthropic test: a client gone while the error chunk is
    in flight must not turn into a close forwarded into the engine — the
    [DONE] is consumed before the chunk is yielded, so the finally drains."""
    state = {"exit": None}

    async def engine_sse():
        try:
            yield 'data: {"error": {"message": "boom", "type": "rate_limit_error"}}\n\n'
            yield "data: [DONE]\n\n"
            state["exit"] = "completed"
        except GeneratorExit:
            state["exit"] = "generator_exit"
            raise

    gen = stream_chunks(OpenAIFrameStream(engine_sse()))
    first = await gen.__anext__()
    assert first["error"]["status"] == "RESOURCE_EXHAUSTED"
    await gen.aclose()  # client gone while the error chunk was in flight
    assert state["exit"] == "completed"
