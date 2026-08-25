"""Anthropic streaming transformer — pure-transformer unit tests (slice S4).

Feeds synthetic OpenAI chunk dicts (what `OpenAIFrameStream` yields after
parsing the engine's SSE) and asserts the exact Anthropic event sequence.
Also covers `OpenAIFrameStream` itself.
"""

from __future__ import annotations

import asyncio
import json

import anyio
import pytest

from app.protocols.anthropic import stream_events
from app.protocols.sse import OpenAIFrameStream


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


async def test_message_start_reports_the_supplied_input_token_estimate():
    """The protocol puts the input count in message_start (SDKs read it
    there), but the engine only knows the true value at end-of-stream, so
    the route passes its own estimate in and the exact count follows in
    message_delta."""
    raw = [f async for f in stream_events(
        _agen([_text_chunk("hi"), _FINISH_CHUNK, _USAGE_CHUNK]), input_tokens=37,
    )]
    events = _parse_events(raw)
    assert events[0][1]["message"]["usage"] == {"input_tokens": 37, "output_tokens": 0}
    # exact count from the engine's usage frame still lands in message_delta
    assert events[-2][1]["usage"]["input_tokens"] == 4


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


@pytest.mark.parametrize("engine_type,anthropic_type", [
    ("rate_limit_error", "rate_limit_error"),
    ("overloaded_error", "overloaded_error"),
    ("context_length_exceeded", "invalid_request_error"),
    ("model_not_found", "not_found_error"),
    # OUR provider credential — permanent, must not present as retryable
    # (SDKs back off and retry api_error/500, but never a 4xx type).
    ("upstream_auth_error", "permission_error"),
    # transient by definition — the taxonomy's "busy" status, not a generic
    # api_error the caller cannot tell apart from a fault in this server
    ("upstream_timeout", "overloaded_error"),
    ("something_unknown", "api_error"),
    (None, "api_error"),
])
async def test_engine_error_type_maps_to_anthropic_taxonomy(engine_type, anthropic_type):
    """The engine's translated error types must map into the Anthropic
    taxonomy — a context overflow or missing model presented as a generic
    api_error would be retried by clients even though it can never
    succeed."""
    err: dict = {"message": "boom"}
    if engine_type is not None:
        err["type"] = engine_type
    events = await _collect([{"error": err}])
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["type"] == anthropic_type


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

    raw = [f async for f in stream_events(OpenAIFrameStream(engine_sse()))]
    events = _parse_events(raw)
    assert events[-1][0] == "error"
    assert events[-1][1]["error"]["type"] == "rate_limit_error"
    assert state["exit"] == "completed"


async def test_terminal_events_reach_the_client_before_the_engine_writeback():
    """Ordering regression: resuming the engine past [DONE] runs its
    `finally` — the RequestLog DB commit. That write must not sit between
    the last content the client sees and message_stop, or a slow/wedged DB
    leaves the SDK waiting for a stream that has no terminal event."""
    order: list[str] = []

    async def engine_sse():
        yield 'data: {"id":"c1","model":"m","choices":[{"index":0,' \
              '"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n'
        yield "data: [DONE]\n\n"
        # Whoever resumes the engine past [DONE] awaits this.
        order.append("engine_writeback")

    async for raw in stream_events(OpenAIFrameStream(engine_sse())):
        order.append(raw.splitlines()[0][len("event: "):])

    assert "engine_writeback" in order, "the engine must still be drained"
    assert order.index("message_stop") < order.index("engine_writeback")
    assert order[-1] == "engine_writeback"


async def test_empty_stream_still_emits_valid_skeleton():
    events = await _collect([])
    names = [n for n, _ in events]
    assert names == ["message_start", "message_delta", "message_stop"]


# ── OpenAIFrameStream ──


async def test_frame_stream_parses_stops_at_done_then_drains_on_finish():
    """Iteration stops at [DONE] leaving the engine suspended; finish()
    is what resumes it to natural completion."""
    resumed = {"value": False}

    async def producer():
        yield 'data: {"a": 1}\n\n'
        yield 'data: {"b": 2}\n\n'
        yield "data: [DONE]\n\n"
        resumed["value"] = True

    stream = OpenAIFrameStream(producer())
    frames = [f async for f in stream]
    assert frames == [{"a": 1}, {"b": 2}]
    assert resumed["value"] is False, "the engine must not be resumed by iteration"
    await stream.finish()
    assert resumed["value"] is True


async def test_frame_stream_handles_split_and_bytes_frames():
    async def producer():
        yield b'data: {"a"'
        yield b': 1}\n\ndata: [DONE]\n\n'

    stream = OpenAIFrameStream(producer())
    assert [f async for f in stream] == [{"a": 1}]


async def test_frame_stream_finish_is_idempotent():
    drains = {"count": 0}

    async def producer():
        yield 'data: {"a": 1}\n\ndata: [DONE]\n\n'
        drains["count"] += 1

    stream = OpenAIFrameStream(producer())
    assert [f async for f in stream] == [{"a": 1}]
    await stream.finish()
    await stream.finish()
    assert drains["count"] == 1


async def test_frame_stream_finish_forwards_close_when_done_not_reached():
    """No [DONE] seen (client disconnected mid-stream) → forward the close
    so the engine's own disconnect handling runs."""
    closed = {"value": False}

    class _Source:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return 'data: {"a": 1}\n\n'

        async def aclose(self):
            closed["value"] = True

    stream = OpenAIFrameStream(_Source())
    assert (await stream.__aiter__().__anext__()) == {"a": 1}
    await stream.finish()
    assert closed["value"] is True


async def test_close_during_post_done_drain_still_forwards_close_to_source():
    """Regression: a cancel/close landing DURING the post-[DONE] drain must
    still forward the close to the source — otherwise the engine generator
    stays suspended at its [DONE] yield and its request-log writeback only
    runs at GC finalization (or never, if the process exits first)."""
    closed = {"value": False}
    drain_entered = asyncio.Event()

    class _Source:
        def __init__(self):
            self._sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._sent:
                self._sent = True
                return 'data: {"a": 1}\n\ndata: [DONE]\n\n'
            drain_entered.set()
            await asyncio.Event().wait()  # suspend in the drain until cancelled

        async def aclose(self):
            closed["value"] = True

    stream = OpenAIFrameStream(_Source())
    assert [f async for f in stream] == [{"a": 1}]
    task = asyncio.create_task(stream.finish())
    await drain_entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed["value"] is True


# ── block ordering: text ↔ tool calls ──


def _block_sequence(events) -> list[tuple[str, int, str | None]]:
    """(event, index, block type for starts) for every content_block_* event."""
    out = []
    for name, data in events:
        if name.startswith("content_block_"):
            btype = data["content_block"]["type"] if name == "content_block_start" else None
            out.append((name, data["index"], btype))
    return out


async def test_text_after_a_tool_call_is_delivered_after_the_tool_use_block():
    """Regression: tool fragments were held to end-of-stream while text
    streamed through immediately, so text the model wrote AFTER a tool
    call reached the client BEFORE it. SDKs process blocks strictly in
    order, so an agent misread which text preceded the call."""
    frames = [
        _tool_fragment(0, '{"city": "SF"}', call_id="call_1", name="get_weather"),
        _text_chunk("Checking the weather."),
        _FINISH_CHUNK,
        _USAGE_CHUNK,
    ]
    events = await _collect(frames)
    assert _block_sequence(events) == [
        ("content_block_start", 0, "tool_use"),
        ("content_block_delta", 0, None),
        ("content_block_stop", 0, None),
        ("content_block_start", 1, "text"),
        ("content_block_delta", 1, None),
        ("content_block_stop", 1, None),
    ]
    tool_start = events[1][1]["content_block"]
    assert (tool_start["id"], tool_start["name"]) == ("call_1", "get_weather")
    assert events[-2][1]["delta"]["stop_reason"] == "end_turn"


async def test_tool_call_between_two_text_runs_keeps_the_model_order():
    """text → tool call → text must come out as three blocks in that
    order, never as one merged text block followed by the tool block —
    and the split call's fragments must still reassemble into one block."""
    frames = [
        _text_chunk("A"),
        _tool_fragment(0, '{"ci', call_id="call_1", name="f"),
        _tool_fragment(0, 'ty": "SF"}'),
        _text_chunk("B"),
        _FINISH_CHUNK,
        _USAGE_CHUNK,
    ]
    events = await _collect(frames)
    starts = [(d["index"], d["content_block"]["type"])
              for n, d in events if n == "content_block_start"]
    assert starts == [(0, "text"), (1, "tool_use"), (2, "text")]
    texts = {d["index"]: d["delta"]["text"] for n, d in events
             if n == "content_block_delta" and d["delta"]["type"] == "text_delta"}
    assert texts == {0: "A", 2: "B"}
    partial = [d["delta"]["partial_json"] for n, d in events
               if n == "content_block_delta" and d["delta"]["type"] == "input_json_delta"]
    assert partial == ['{"city": "SF"}']
    # each block is start → delta → stop before the next one opens
    assert [e for e, _, _ in _block_sequence(events)] == [
        "content_block_start", "content_block_delta", "content_block_stop",
    ] * 3


async def test_text_between_argument_fragments_of_one_call_does_not_split_it():
    """A text delta landing BETWEEN two argument fragments of the SAME call
    must not flush the half-built call: it stays buffered (to
    end-of-stream) and comes out as one block with whole JSON — never as a
    tool_use with unparseable partial_json plus a nameless second block."""
    frames = [
        _tool_fragment(0, '{"ci', call_id="call_1", name="get_weather"),
        _text_chunk("thinking..."),
        _tool_fragment(0, 'ty": "SF"}'),
        _FINISH_CHUNK,
        _USAGE_CHUNK,
    ]
    events = await _collect(frames)
    starts = [(d["content_block"]["type"], d["content_block"].get("name"))
              for n, d in events if n == "content_block_start"]
    assert starts == [("text", None), ("tool_use", "get_weather")]
    partial = [d["delta"]["partial_json"] for n, d in events
               if n == "content_block_delta" and d["delta"]["type"] == "input_json_delta"]
    assert partial == ['{"city": "SF"}']


async def test_first_fragment_with_empty_arguments_is_not_flushed_by_following_text():
    """The standard first fragment carries only id + name with
    arguments "" — it must not count as a complete call when text follows,
    or the client gets an empty tool_use plus a nameless second block."""
    frames = [
        _tool_fragment(0, "", call_id="call_1", name="get_weather"),
        _text_chunk("thinking..."),
        _tool_fragment(0, '{"city": "SF"}'),
        _FINISH_CHUNK,
        _USAGE_CHUNK,
    ]
    events = await _collect(frames)
    starts = [(d["content_block"]["type"], d["content_block"].get("name"))
              for n, d in events if n == "content_block_start"]
    assert starts == [("text", None), ("tool_use", "get_weather")]
    partial = [d["delta"]["partial_json"] for n, d in events
               if n == "content_block_delta" and d["delta"]["type"] == "input_json_delta"]
    assert partial == ['{"city": "SF"}']


async def test_client_cancel_during_the_final_drain_still_lets_the_engine_finish():
    """This generator is the response body: a client disconnect lands as
    task cancellation. The forwarding in `finally` must be shielded so the
    engine is still driven to completion (its RequestLog writeback runs)
    instead of being abandoned to GC finalization."""
    drain_started = asyncio.Event()
    order: list[str] = []

    async def engine_sse():
        yield 'data: {"id":"c1","model":"m","choices":[{"index":0,' \
              '"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n'
        yield "data: [DONE]\n\n"
        drain_started.set()
        await asyncio.sleep(0.05)  # the engine's writeback, in progress
        order.append("engine_writeback")

    async def consume():
        async for _ in stream_events(OpenAIFrameStream(engine_sse())):
            pass

    # Starlette cancels the response task through an anyio task group —
    # the cancellation shape the shield is there to absorb.
    async with anyio.create_task_group() as tg:
        tg.start_soon(consume)
        await drain_started.wait()
        tg.cancel_scope.cancel()
    assert order == ["engine_writeback"]


async def test_delta_carrying_both_text_and_a_tool_fragment_emits_text_first():
    """OpenAI semantics put a message's content before its tool_calls, so a
    single delta with both closes the text block, then buffers the call."""
    frame = {
        "id": "chatcmpl-1", "model": "gpt-4o-mini",
        "choices": [{"index": 0, "delta": {
            "content": "Let me check.",
            "tool_calls": [{"index": 0, "id": "call_1",
                            "function": {"name": "f", "arguments": "{}"}}],
        }, "finish_reason": None}],
    }
    events = await _collect([frame, _FINISH_CHUNK, _USAGE_CHUNK])
    starts = [(d["index"], d["content_block"]["type"])
              for n, d in events if n == "content_block_start"]
    assert starts == [(0, "text"), (1, "tool_use")]
    assert [e for e, _, _ in _block_sequence(events)] == [
        "content_block_start", "content_block_delta", "content_block_stop",
        "content_block_start", "content_block_delta", "content_block_stop",
    ]


async def test_close_at_the_error_event_still_drains_the_engine_source():
    """The client may disconnect while the error event is in flight, i.e.
    with the transformer suspended at that yield. Its finally must still
    DRAIN the engine (natural completion → 503 + real error type logged),
    not forward a close into it — so the [DONE] has to be consumed before
    the event is yielded, not after."""
    state = {"exit": None}

    async def engine_sse():
        try:
            yield 'data: {"error": {"message": "boom", "type": "rate_limit_error"}}\n\n'
            yield "data: [DONE]\n\n"
            state["exit"] = "completed"
        except GeneratorExit:
            state["exit"] = "generator_exit"
            raise

    gen = stream_events(OpenAIFrameStream(engine_sse()))
    first = await gen.__anext__()
    assert first.startswith("event: error\n")
    await gen.aclose()  # client gone while the error event was in flight
    assert state["exit"] == "completed"
