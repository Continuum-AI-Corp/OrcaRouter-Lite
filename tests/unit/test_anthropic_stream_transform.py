"""Anthropic streaming transformer — pure-transformer unit tests (slice S4).

Feeds synthetic OpenAI chunk dicts (what `iter_openai_frames` yields after
parsing the engine's SSE) and asserts the exact Anthropic event sequence.
Also covers `iter_openai_frames` itself.
"""

from __future__ import annotations

import json

from app.protocols.anthropic import stream_events
from app.protocols.sse import iter_openai_frames


async def _agen(items):
    for item in items:
        yield item


def _parse_events(raw_frames: list[str]) -> list[tuple[str, dict]]:
    """Each transformer output frame is `event: <name>\\ndata: {json}\\n\\n`."""
    out = []
    for frame in raw_frames:
        assert frame.endswith("\n\n")
        lines = frame.strip().splitlines()
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        out.append((lines[0][len("event: "):], json.loads(lines[1][len("data: "):])))
    return out


async def _collect(frames_dicts: list[dict]) -> list[tuple[str, dict]]:
    raw = [f async for f in stream_events(_agen(frames_dicts))]
    return _parse_events(raw)


def _text_chunk(text: str, model="gpt-4o-mini") -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion.chunk", "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }


_FINISH_CHUNK = {
    "id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
}

_USAGE_CHUNK = {
    "id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
    "choices": [],
    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
}


# ── stream_events ──


async def test_text_stream_event_sequence():
    events = await _collect([
        _text_chunk("Hello"), _text_chunk(" world"), _FINISH_CHUNK, _USAGE_CHUNK,
    ])
    names = [n for n, _ in events]
    assert names == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    # every event's data carries its own type field matching the event name
    for name, data in events:
        assert data["type"] == name

    start = events[0][1]["message"]
    assert start["id"].startswith("msg_")
    assert start["model"] == "gpt-4o-mini"

    deltas = [d["delta"]["text"] for n, d in events if n == "content_block_delta"]
    assert "".join(deltas) == "Hello world"

    msg_delta = events[-2][1]
    assert msg_delta["delta"]["stop_reason"] == "end_turn"
    assert msg_delta["usage"]["output_tokens"] == 2
    assert msg_delta["usage"]["input_tokens"] == 4


async def test_usage_frame_missing_still_terminates_with_zero_usage():
    events = await _collect([_text_chunk("hi"), _FINISH_CHUNK])
    names = [n for n, _ in events]
    assert names[-2:] == ["message_delta", "message_stop"]
    assert events[-2][1]["usage"]["output_tokens"] == 0


async def test_length_finish_maps_to_max_tokens():
    finish = {
        "id": "chatcmpl-1", "model": "gpt-4o-mini",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}],
    }
    events = await _collect([_text_chunk("hi"), finish])
    assert events[-2][1]["delta"]["stop_reason"] == "max_tokens"


async def test_tool_call_stream_buffers_into_one_complete_tool_use_block():
    """Fragments are buffered per index and flushed as ONE complete block
    at end-of-stream (start → single full input_json_delta → stop)."""
    frames = [
        {
            "id": "chatcmpl-1", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "id": "call_1", "type": "function",
                "function": {"name": "get_weather", "arguments": ""},
            }]}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": '{"city": '},
            }]}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": '"SF"}'},
            }]}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-1", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        },
        _USAGE_CHUNK,
    ]
    events = await _collect(frames)
    names = [n for n, _ in events]
    assert names == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    start = [d for n, d in events if n == "content_block_start"][0]
    assert start["content_block"]["type"] == "tool_use"
    assert start["content_block"]["id"] == "call_1"
    assert start["content_block"]["name"] == "get_weather"

    partials = [d["delta"]["partial_json"] for n, d in events if n == "content_block_delta"]
    assert json.loads("".join(partials)) == {"city": "SF"}
    assert events[-2][1]["delta"]["stop_reason"] == "tool_use"


def _tool_fragment(index: int, args: str, call_id: str | None = None,
                   name: str | None = None) -> dict:
    tcd: dict = {"index": index, "function": {"arguments": args}}
    if call_id:
        tcd["id"] = call_id
    if name:
        tcd["function"]["name"] = name
    return {
        "id": "chatcmpl-1", "model": "gpt-4o-mini",
        "choices": [{"index": 0, "delta": {"tool_calls": [tcd]}, "finish_reason": None}],
    }


async def test_interleaved_tool_call_fragments_stay_in_their_own_blocks():
    """Regression: OpenAI-format streams interleave argument fragments of
    concurrent tool calls across frames. The old block-reopen logic emitted
    a NEW block (random id, empty name) per index switch, scattering each
    call's JSON across nameless blocks. Buffered per index, the output must
    be exactly one complete block per call, sequential, ids/names intact."""
    frames = [
        _tool_fragment(0, '{"ci', call_id="call_a", name="get_weather"),
        _tool_fragment(1, '{"tz', call_id="call_b", name="get_time"),
        _tool_fragment(0, 'ty": "SF"}'),
        _tool_fragment(1, '": "UTC"}'),
        {
            "id": "chatcmpl-1", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        },
        _USAGE_CHUNK,
    ]
    events = await _collect(frames)
    starts = [d for n, d in events if n == "content_block_start"]
    assert [(s["content_block"]["id"], s["content_block"]["name"]) for s in starts] == [
        ("call_a", "get_weather"), ("call_b", "get_time"),
    ]

    # one complete input_json_delta per block, correctly reassembled
    deltas = [d for n, d in events if n == "content_block_delta"]
    by_index = {d["index"]: json.loads(d["delta"]["partial_json"]) for d in deltas}
    assert by_index == {
        starts[0]["index"]: {"city": "SF"},
        starts[1]["index"]: {"tz": "UTC"},
    }

    # blocks are strictly sequential: start(i) → delta(i) → stop(i)
    block_events = [(n, d["index"]) for n, d in events
                    if n.startswith("content_block_")]
    i0, i1 = starts[0]["index"], starts[1]["index"]
    assert block_events == [
        ("content_block_start", i0), ("content_block_delta", i0),
        ("content_block_stop", i0),
        ("content_block_start", i1), ("content_block_delta", i1),
        ("content_block_stop", i1),
    ]
    assert events[-2][1]["delta"]["stop_reason"] == "tool_use"


async def test_text_then_tool_call_uses_two_block_indexes():
    frames = [
        _text_chunk("thinking..."),
        {
            "id": "chatcmpl-1", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {"tool_calls": [{
                "index": 0, "id": "call_1",
                "function": {"name": "f", "arguments": "{}"},
            }]}, "finish_reason": None}],
        },
        _FINISH_CHUNK,
        _USAGE_CHUNK,
    ]
    events = await _collect(frames)
    starts = [(d["index"], d["content_block"]["type"])
              for n, d in events if n == "content_block_start"]
    stops = [d["index"] for n, d in events if n == "content_block_stop"]
    assert starts == [(0, "text"), (1, "tool_use")]
    assert stops == [0, 1]


async def test_engine_error_frame_becomes_error_event():
    frames = [
        _text_chunk("partial"),
        {"error": {"message": "Upstream provider error: boom", "type": "upstream_error"}},
    ]
    events = await _collect(frames)
    names = [n for n, _ in events]
    assert names[-1] == "error"
    err = events[-1][1]
    assert err["type"] == "error"
    assert err["error"]["type"] == "api_error"
    assert "boom" in err["error"]["message"]
    assert "message_stop" not in names


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

    raw = [f async for f in stream_events(iter_openai_frames(engine_sse()))]
    events = _parse_events(raw)
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["type"] == "rate_limit_error"
    assert state["exit"] == "completed"


async def test_empty_stream_still_emits_valid_skeleton():
    events = await _collect([])
    names = [n for n, _ in events]
    assert names == ["message_start", "message_delta", "message_stop"]


# ── iter_openai_frames ──


async def test_iter_openai_frames_parses_and_stops_at_done():
    async def producer():
        yield 'data: {"a": 1}\n\n'
        yield 'data: {"b": 2}\n\n'
        yield "data: [DONE]\n\n"
        yield 'data: {"never": true}\n\n'

    frames = [f async for f in iter_openai_frames(producer())]
    assert frames == [{"a": 1}, {"b": 2}]


async def test_iter_openai_frames_handles_split_and_bytes_frames():
    async def producer():
        yield b'data: {"a"'
        yield b': 1}\n\ndata: [DONE]\n\n'

    frames = [f async for f in iter_openai_frames(producer())]
    assert frames == [{"a": 1}]


async def test_iter_openai_frames_forwards_close_to_source():
    closed = {"value": False}

    class _Source:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return 'data: {"a": 1}\n\n'

        async def aclose(self):
            closed["value"] = True

    gen = iter_openai_frames(_Source())
    assert (await gen.__anext__()) == {"a": 1}
    await gen.aclose()
    assert closed["value"] is True
