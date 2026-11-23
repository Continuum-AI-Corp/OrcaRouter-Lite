"""OpenAI Responses API translator — pure unit tests.

Request translation (Responses → internal OpenAI chat format), blocking
response translation (chat.completion → Response object) and the streaming
transformer (engine chunk dicts → Responses SSE events), fed with bare
async generators of frame dicts exactly like the Anthropic/Gemini
transformer tests. The request shapes mirror what OpenAI's Codex CLI sends
with `wire_api = "responses"`.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.protocols import responses as proto
from app.schemas import ChatCompletionRequest


def _req(**overrides) -> proto.ResponsesRequest:
    base: dict = {"model": "gpt-4o-mini", "input": "hi"}
    base.update(overrides)
    return proto.ResponsesRequest.model_validate(base)


def _translate(**overrides) -> dict:
    out = proto.to_openai_request(_req(**overrides))
    # Whatever we produce must be a valid engine request.
    ChatCompletionRequest.model_validate(out)
    return out


def _msg(role: str, *parts: dict | str) -> dict:
    content = parts[0] if len(parts) == 1 and isinstance(parts[0], str) else list(parts)
    return {"type": "message", "role": role, "content": content}


def _in_text(text: str) -> dict:
    return {"type": "input_text", "text": text}


def _out_text(text: str) -> dict:
    return {"type": "output_text", "text": text}


def _fc(call_id: str, name: str, arguments: str = "{}") -> dict:
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}


def _fco(call_id: str, output) -> dict:
    return {"type": "function_call_output", "call_id": call_id, "output": output}


# ── request translation ────────────────────────────────────────────────


def test_string_input_becomes_one_user_message_with_instructions_as_system():
    out = _translate(input="hello", instructions="You are Codex.")
    assert out["messages"] == [
        {"role": "system", "content": "You are Codex."},
        {"role": "user", "content": "hello"},
    ]
    assert out["model"] == "gpt-4o-mini"
    assert out["stream"] is False


def test_message_items_map_roles_and_flatten_text_parts():
    out = _translate(input=[
        _msg("developer", _in_text("sandbox: workspace-write")),
        _msg("user", _in_text("fix the bug")),
        _msg("assistant", _out_text("Looking"), _out_text(" now.")),
        _msg("system", "be terse"),
    ])
    assert out["messages"] == [
        {"role": "system", "content": "sandbox: workspace-write"},
        {"role": "user", "content": "fix the bug"},
        {"role": "assistant", "content": "Looking now."},
        {"role": "system", "content": "be terse"},
    ]


def test_user_message_with_several_parts_and_an_image_keeps_the_part_list():
    out = _translate(input=[_msg(
        "user",
        _in_text("<environment_context/>"),
        _in_text("what is in this picture?"),
        {"type": "input_image", "image_url": "data:image/png;base64,AAAA", "detail": "high"},
    )])
    assert out["messages"] == [{"role": "user", "content": [
        {"type": "text", "text": "<environment_context/>"},
        {"type": "text", "text": "what is in this picture?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA", "detail": "high"}},
    ]}]


def test_items_without_type_but_with_role_are_messages():
    out = _translate(input=[
        {"role": "user", "content": "plain"},
        {"role": "assistant", "content": [_out_text("ok")]},
    ])
    assert out["messages"] == [
        {"role": "user", "content": "plain"},
        {"role": "assistant", "content": "ok"},
    ]


def test_consecutive_function_calls_merge_into_one_assistant_message_after_its_text():
    out = _translate(input=[
        _msg("user", _in_text("list and read")),
        {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "xxx"},
        _msg("assistant", _out_text("Running two commands.")),
        _fc("call_1", "shell", '{"command": ["ls"]}'),
        _fc("call_2", "shell", '{"command": ["cat", "a"]}'),
        _fco("call_1", "a\nb"),
        _fco("call_2", "contents"),
        _fc("call_3", "shell", '{"command": ["pwd"]}'),
        _fco("call_3", "/repo"),
    ])
    assert out["messages"] == [
        {"role": "user", "content": "list and read"},
        {"role": "assistant", "content": "Running two commands.", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "shell", "arguments": '{"command": ["ls"]}'}},
            {"id": "call_2", "type": "function",
             "function": {"name": "shell", "arguments": '{"command": ["cat", "a"]}'}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "a\nb"},
        {"role": "tool", "tool_call_id": "call_2", "content": "contents"},
        # Not adjacent to an assistant message (tool outputs in between):
        # a new assistant turn with null content.
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_3", "type": "function",
             "function": {"name": "shell", "arguments": '{"command": ["pwd"]}'}},
        ]},
        {"role": "tool", "tool_call_id": "call_3", "content": "/repo"},
    ]


def test_function_call_output_content_list_is_flattened_and_images_follow_the_tool_run():
    out = _translate(input=[
        _fc("call_1", "view_image", '{"path": "a.png"}'),
        _fc("call_2", "shell", "{}"),
        _fco("call_1", [
            {"type": "input_text", "text": "image attached"},
            {"type": "input_image", "image_url": "data:image/png;base64,BBBB"},
        ]),
        _fco("call_2", [{"type": "output_text", "text": "line1"}, {"type": "input_text", "text": "line2"}]),
        _msg("user", _in_text("thanks")),
    ])
    msgs = out["messages"]
    assert msgs[1] == {"role": "tool", "tool_call_id": "call_1", "content": "image attached"}
    assert msgs[2] == {"role": "tool", "tool_call_id": "call_2", "content": "line1\nline2"}
    # The image cannot live in a tool message; it rides in a user message
    # placed AFTER the whole run of tool results (tool results must stay
    # directly behind the assistant tool_calls turn).
    assert msgs[3]["role"] == "user"
    assert {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}} in msgs[3]["content"]
    assert msgs[4] == {"role": "user", "content": "thanks"}


def test_reasoning_and_unknown_items_are_dropped_not_rejected():
    out = _translate(input=[
        {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "hm"}]},
        {"type": "web_search_call", "id": "ws_1", "status": "completed"},
        {"type": "item_reference", "id": "msg_9"},
        _msg("user", _in_text("go")),
    ])
    assert out["messages"] == [{"role": "user", "content": "go"}]


def test_tool_output_for_a_dropped_call_is_dropped_too():
    """A local_shell_call (dropped: unsupported item) followed by its output
    would reach the upstream as an orphan tool message, which providers
    reject — a retryable 5xx for a request that can never succeed."""
    out = _translate(input=[
        _msg("user", _in_text("go")),
        {"type": "local_shell_call", "call_id": "ls_1", "status": "completed",
         "action": {"type": "exec", "command": ["ls"]}},
        _fco("ls_1", "a b"),
        _msg("user", _in_text("and?")),
    ])
    assert out["messages"] == [
        {"role": "user", "content": "go"},
        {"role": "user", "content": "and?"},
    ]


_SHELL_TOOL = {
    "type": "function", "name": "shell", "description": "Runs a command",
    "strict": False,
    "parameters": {"type": "object", "properties": {"command": {"type": "array"}},
                   "required": ["command"], "additionalProperties": False},
}

_APPLY_PATCH_TOOL = {
    "type": "custom", "name": "apply_patch",
    "description": "Use the `apply_patch` tool to edit files.",
    "format": {"type": "grammar", "syntax": "lark",
               "definition": 'start: begin_patch hunk+ end_patch\nbegin_patch: "*** Begin Patch" LF'},
}


def test_function_tools_translate_and_hosted_tools_are_dropped():
    out = _translate(
        tools=[_SHELL_TOOL, {"type": "web_search"}, {"type": "local_shell"},
               {"type": "file_search", "vector_store_ids": ["vs_1"]}],
        tool_choice="auto", parallel_tool_calls=False,
    )
    assert out["tools"] == [{"type": "function", "function": {
        "name": "shell", "description": "Runs a command",
        "parameters": _SHELL_TOOL["parameters"],
    }}]
    assert out["tool_choice"] == "auto"
    assert out["parallel_tool_calls"] is False


def test_custom_freeform_tool_becomes_a_function_with_one_string_input():
    out = _translate(tools=[_APPLY_PATCH_TOOL])
    (tool,) = out["tools"]
    fn = tool["function"]
    assert tool["type"] == "function"
    assert fn["name"] == "apply_patch"
    assert fn["parameters"]["type"] == "object"
    assert fn["parameters"]["properties"]["input"]["type"] == "string"
    assert fn["parameters"]["required"] == ["input"]
    # The grammar is the only spec the model gets for the freeform input.
    assert "Use the `apply_patch` tool" in fn["description"]
    assert "*** Begin Patch" in fn["description"]


def test_custom_tool_call_history_round_trips_as_input_arguments():
    out = _translate(tools=[_APPLY_PATCH_TOOL], input=[
        _msg("user", _in_text("edit")),
        {"type": "custom_tool_call", "call_id": "call_p", "name": "apply_patch",
         "input": "*** Begin Patch\n*** End Patch"},
        {"type": "custom_tool_call_output", "call_id": "call_p", "output": "Done!"},
    ])
    assert out["messages"][1] == {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_p", "type": "function",
        "function": {"name": "apply_patch",
                     "arguments": json.dumps({"input": "*** Begin Patch\n*** End Patch"})},
    }]}
    assert out["messages"][2] == {"role": "tool", "tool_call_id": "call_p", "content": "Done!"}


@pytest.mark.parametrize(("choice", "expected"), [
    ("auto", "auto"),
    ("none", "none"),
    ("required", "required"),
    ({"type": "function", "name": "shell"}, {"type": "function", "function": {"name": "shell"}}),
    ({"type": "custom", "name": "apply_patch"}, {"type": "function", "function": {"name": "apply_patch"}}),
])
def test_tool_choice_mapping(choice, expected):
    out = _translate(tools=[_SHELL_TOOL, _APPLY_PATCH_TOOL], tool_choice=choice)
    assert out["tool_choice"] == expected


def test_tool_settings_are_omitted_when_every_tool_was_dropped():
    """Upstreams reject tool_choice / parallel_tool_calls without tools."""
    out = _translate(tools=[{"type": "web_search"}], tool_choice="auto", parallel_tool_calls=False)
    assert "tools" not in out
    assert "tool_choice" not in out
    assert "parallel_tool_calls" not in out


def test_sampling_and_output_settings_map_and_codex_only_fields_are_ignored():
    out = _translate(
        stream=True, max_output_tokens=256, temperature=0.2, top_p=0.9,
        store=False, include=["reasoning.encrypted_content"], prompt_cache_key="abc",
        reasoning={"effort": "high", "summary": "auto"},
        text={"verbosity": "low"},
        service_tier="auto",
    )
    assert out["stream"] is True
    assert out["max_tokens"] == 256
    assert out["temperature"] == 0.2
    assert out["top_p"] == 0.9
    for absent in ("store", "include", "prompt_cache_key", "reasoning", "text",
                   "response_format", "reasoning_effort", "service_tier"):
        assert absent not in out


def test_text_format_json_schema_maps_to_response_format():
    schema = {"type": "object", "properties": {"a": {"type": "string"}},
              "required": ["a"], "additionalProperties": False}
    out = _translate(text={"format": {"type": "json_schema", "name": "out", "schema": schema,
                                      "strict": True}})
    rf = out["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "out"
    assert rf["json_schema"]["schema"] == schema
    assert rf["json_schema"]["strict"] is True
    assert _translate(text={"format": {"type": "json_object"}})["response_format"] == {"type": "json_object"}
    assert "response_format" not in _translate(text={"format": {"type": "text"}})


@pytest.mark.parametrize("overrides", [
    {"input": [{"type": "message", "content": "no role"}]},
    {"input": [_msg("tool", "bad role")]},
    {"input": [_msg("user", {"type": "input_file", "file_id": "file_1"})]},
    {"input": [_fc("", "shell")]},
    {"input": [{"type": "function_call", "call_id": "c", "arguments": "{}"}]},
    {"input": [_msg("user", {"type": "input_text", "text": 5})]},
    {"input": [{"type": "reasoning", "id": "rs_1"}]},  # nothing left to send
    {"input": "hi", "previous_response_id": "resp_123"},
    {"tools": [{"type": "function", "description": "nameless"}]},
])
def test_invalid_requests_raise_400(overrides):
    with pytest.raises(HTTPException) as ei:
        proto.to_openai_request(_req(**overrides))
    assert ei.value.status_code == 400


def test_request_schema_rejects_bad_types():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        proto.ResponsesRequest.model_validate({"model": "m", "input": 5})
    with pytest.raises(ValidationError):
        proto.ResponsesRequest.model_validate({"model": "m", "input": "x", "max_output_tokens": 0})


# ── blocking response translation ──────────────────────────────────────


def _completion(message: dict, finish_reason: str = "stop", usage: dict | None = None) -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": "gpt-4o-mini-2024",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def _ctx(**overrides) -> proto.ResponseContext:
    return proto.ResponseContext.for_request(_req(**overrides))


def test_text_response_becomes_a_completed_response_with_one_message_item():
    resp = proto.to_responses_response(
        _completion({"role": "assistant", "content": "Hello"}), _ctx(),
    )
    assert resp["id"].startswith("resp_")
    assert resp["object"] == "response"
    assert isinstance(resp["created_at"], int)
    assert resp["status"] == "completed"
    assert resp["model"] == "gpt-4o-mini-2024"
    (item,) = resp["output"]
    assert item["type"] == "message"
    assert item["id"].startswith("msg_")
    assert item["status"] == "completed"
    assert item["role"] == "assistant"
    assert item["content"] == [{"type": "output_text", "text": "Hello", "annotations": []}]
    assert resp["usage"] == {
        "input_tokens": 10, "output_tokens": 3, "total_tokens": 13,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    }
    assert resp["parallel_tool_calls"] is True
    assert resp["tool_choice"] == "auto"
    assert resp["tools"] == []
    assert resp["error"] is None
    assert resp["incomplete_details"] is None


def test_tool_calls_become_function_call_items_and_custom_tools_custom_tool_call_items():
    ctx = _ctx(tools=[_SHELL_TOOL, _APPLY_PATCH_TOOL], parallel_tool_calls=False, tool_choice="required")
    resp = proto.to_responses_response(_completion({
        "role": "assistant", "content": "Patching.",
        "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "shell", "arguments": '{"command": ["ls"]}'}},
            {"id": "call_2", "type": "function",
             "function": {"name": "apply_patch",
                          "arguments": json.dumps({"input": "*** Begin Patch\n*** End Patch\n"})}},
        ],
    }, finish_reason="tool_calls"), ctx)
    msg, fc, ctc = resp["output"]
    assert msg["type"] == "message"
    assert fc == {
        "id": fc["id"], "type": "function_call", "status": "completed",
        "call_id": "call_1", "name": "shell", "arguments": '{"command": ["ls"]}',
    }
    assert fc["id"].startswith("fc_")
    assert ctc == {
        "id": ctc["id"], "type": "custom_tool_call", "status": "completed",
        "call_id": "call_2", "name": "apply_patch", "input": "*** Begin Patch\n*** End Patch\n",
    }
    assert resp["status"] == "completed"
    assert resp["parallel_tool_calls"] is False
    assert resp["tool_choice"] == "required"
    assert resp["tools"] == [_SHELL_TOOL, _APPLY_PATCH_TOOL]


def test_length_finish_is_incomplete_max_output_tokens():
    resp = proto.to_responses_response(
        _completion({"role": "assistant", "content": "trunc"}, finish_reason="length"), _ctx(),
    )
    assert resp["status"] == "incomplete"
    assert resp["incomplete_details"] == {"reason": "max_output_tokens"}


def test_usage_details_carry_cached_and_reasoning_tokens():
    resp = proto.to_responses_response(_completion(
        {"role": "assistant", "content": "x"},
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
               "prompt_tokens_details": {"cached_tokens": 80},
               "completion_tokens_details": {"reasoning_tokens": 20}},
    ), _ctx())
    assert resp["usage"]["input_tokens_details"] == {"cached_tokens": 80}
    assert resp["usage"]["output_tokens_details"] == {"reasoning_tokens": 20}


def test_empty_assistant_message_yields_empty_output():
    resp = proto.to_responses_response(_completion({"role": "assistant", "content": None}), _ctx())
    assert resp["output"] == []
    assert resp["status"] == "completed"


# ── streaming ──────────────────────────────────────────────────────────


async def _agen(items):
    for item in items:
        yield item


def _parse_events(raw_frames: list[str]) -> list[tuple[str, dict]]:
    out = []
    for frame in raw_frames:
        assert frame.endswith("\n\n")
        lines = frame.strip().splitlines()
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        out.append((lines[0][len("event: "):], json.loads(lines[1][len("data: "):])))
    return out


async def _collect(frames: list[dict], ctx: proto.ResponseContext | None = None) -> list[tuple[str, dict]]:
    raw = [f async for f in proto.stream_events(_agen(frames), ctx or _ctx(stream=True))]
    events = _parse_events(raw)
    seqs = [d["sequence_number"] for _, d in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), "sequence_number must increase"
    for name, data in events:
        assert data["type"] == name
    return events


def _text(text: str) -> dict:
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}


def _finish(reason: str = "stop") -> dict:
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {}, "finish_reason": reason}]}


_USAGE = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
          "choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}}


def _tool(index: int, args: str, call_id: str | None = None, name: str | None = None) -> dict:
    tcd: dict = {"index": index, "function": {"arguments": args}}
    if call_id:
        tcd["id"] = call_id
        tcd["type"] = "function"
    if name:
        tcd["function"]["name"] = name
    return {"id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "gpt-4o-mini",
            "choices": [{"index": 0, "delta": {"tool_calls": [tcd]}, "finish_reason": None}]}


_TEXT_ITEM_EVENTS = [
    "response.output_item.added",
    "response.content_part.added",
]
_TEXT_CLOSE_EVENTS = [
    "response.output_text.done",
    "response.content_part.done",
    "response.output_item.done",
]


async def test_text_only_stream_event_sequence():
    events = await _collect([_text("Hello"), _text(" world"), _finish(), _USAGE])
    assert [n for n, _ in events] == [
        "response.created",
        "response.in_progress",
        *_TEXT_ITEM_EVENTS,
        "response.output_text.delta",
        "response.output_text.delta",
        *_TEXT_CLOSE_EVENTS,
        "response.completed",
    ]
    created = events[0][1]["response"]
    assert created["status"] == "in_progress"
    assert created["output"] == []
    assert created["id"].startswith("resp_")

    added = events[2][1]
    assert added["output_index"] == 0
    assert added["item"]["type"] == "message"
    assert added["item"]["status"] == "in_progress"
    assert added["item"]["content"] == []
    item_id = added["item"]["id"]
    assert item_id.startswith("msg_")

    deltas = [d for n, d in events if n == "response.output_text.delta"]
    assert "".join(d["delta"] for d in deltas) == "Hello world"
    assert all(d["item_id"] == item_id and d["output_index"] == 0 and d["content_index"] == 0
               for d in deltas)
    assert [d for n, d in events if n == "response.output_text.done"][0]["text"] == "Hello world"

    done = [d for n, d in events if n == "response.output_item.done"][0]["item"]
    assert done["status"] == "completed"
    assert done["content"] == [{"type": "output_text", "text": "Hello world", "annotations": []}]

    completed = events[-1][1]["response"]
    assert completed["id"] == created["id"]
    assert completed["status"] == "completed"
    assert completed["output"] == [done]
    assert completed["usage"]["input_tokens"] == 4
    assert completed["usage"]["output_tokens"] == 2
    assert completed["usage"]["total_tokens"] == 6


async def test_text_then_two_tool_calls_event_sequence():
    events = await _collect([
        _text("Let me look."),
        _tool(0, "", call_id="call_a", name="shell"),
        _tool(0, '{"command": '),
        _tool(0, '["ls"]}'),
        _tool(1, "", call_id="call_b", name="shell"),
        _tool(1, '{"command": ["pwd"]}'),
        _finish("tool_calls"),
        _USAGE,
    ])
    assert [n for n, _ in events] == [
        "response.created",
        "response.in_progress",
        *_TEXT_ITEM_EVENTS,
        "response.output_text.delta",
        *_TEXT_CLOSE_EVENTS,
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    added = [d for n, d in events if n == "response.output_item.added"]
    assert [a["output_index"] for a in added] == [0, 1, 2]
    fc_added = added[1]["item"]
    assert fc_added["type"] == "function_call"
    assert fc_added["arguments"] == ""
    assert fc_added["call_id"] == "call_a"
    assert fc_added["name"] == "shell"
    assert fc_added["status"] == "in_progress"

    arg_done = [d for n, d in events if n == "response.function_call_arguments.done"]
    assert [json.loads(d["arguments"]) for d in arg_done] == [{"command": ["ls"]}, {"command": ["pwd"]}]
    assert arg_done[0]["item_id"] == fc_added["id"]

    output = events[-1][1]["response"]["output"]
    assert [o["type"] for o in output] == ["message", "function_call", "function_call"]
    assert output[1] == {"id": fc_added["id"], "type": "function_call", "status": "completed",
                         "call_id": "call_a", "name": "shell", "arguments": '{"command": ["ls"]}'}
    assert output[2]["call_id"] == "call_b"


async def test_interleaved_parallel_tool_call_deltas_stay_with_their_own_items():
    events = await _collect([
        _tool(0, '{"ci', call_id="call_a", name="get_weather"),
        _tool(1, '{"tz', call_id="call_b", name="get_time"),
        _tool(0, 'ty": "SF"}'),
        _tool(1, '": "UTC"}'),
        _finish("tool_calls"),
        _USAGE,
    ])
    output = events[-1][1]["response"]["output"]
    assert [(o["call_id"], o["name"], json.loads(o["arguments"])) for o in output] == [
        ("call_a", "get_weather", {"city": "SF"}),
        ("call_b", "get_time", {"tz": "UTC"}),
    ]
    by_item = {}
    for n, d in events:
        if n == "response.function_call_arguments.delta":
            by_item.setdefault(d["item_id"], "")
            by_item[d["item_id"]] += d["delta"]
    assert sorted(json.loads(v)["city" if "city" in v else "tz"] for v in by_item.values()) == ["SF", "UTC"]
    done_items = [d["item"] for n, d in events if n == "response.output_item.done"]
    assert {i["id"] for i in done_items} == set(by_item)


async def test_tool_call_id_and_name_only_in_first_delta():
    events = await _collect([
        _tool(0, "", call_id="call_x", name="shell"),
        _tool(0, '{"command"'),
        _tool(0, ': ["ls"]}'),
        _finish("tool_calls"),
    ])
    (item,) = events[-1][1]["response"]["output"]
    assert item["call_id"] == "call_x"
    assert item["name"] == "shell"
    assert item["arguments"] == '{"command": ["ls"]}'


async def test_text_after_a_tool_call_comes_after_it():
    events = await _collect([
        _tool(0, '{"a": 1}', call_id="call_1", name="f"),
        _text("Done."),
        _finish(),
    ])
    names = [n for n, _ in events]
    assert names.index("response.function_call_arguments.done") < names.index("response.output_text.delta")
    output = events[-1][1]["response"]["output"]
    assert [o["type"] for o in output] == ["function_call", "message"]


async def test_text_landing_inside_an_incomplete_tool_call_is_held_until_it_completes():
    events = await _collect([
        _tool(0, '{"a": ', call_id="call_1", name="f"),
        _text("odd"),
        _tool(0, "1}"),
        _finish(),
    ])
    output = events[-1][1]["response"]["output"]
    assert [o["type"] for o in output] == ["function_call", "message"]
    assert output[0]["arguments"] == '{"a": 1}'
    assert output[1]["content"][0]["text"] == "odd"


async def test_custom_tool_call_streams_back_as_custom_tool_call_item():
    ctx = _ctx(stream=True, tools=[_SHELL_TOOL, _APPLY_PATCH_TOOL])
    patch = "*** Begin Patch\n*** Add File: a.txt\n+hi\n*** End Patch\n"
    encoded = json.dumps({"input": patch})
    events = await _collect([
        _tool(0, "", call_id="call_p", name="apply_patch"),
        _tool(0, encoded[:10]),
        _tool(0, encoded[10:]),
        _finish("tool_calls"),
        _USAGE,
    ], ctx)
    names = [n for n, _ in events]
    assert names == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.custom_tool_call_input.delta",
        "response.custom_tool_call_input.done",
        "response.output_item.done",
        "response.completed",
    ]
    added = events[2][1]["item"]
    assert added["type"] == "custom_tool_call"
    assert added["input"] == ""
    assert events[4][1]["input"] == patch
    done = events[5][1]["item"]
    assert done == {"id": added["id"], "type": "custom_tool_call", "status": "completed",
                    "call_id": "call_p", "name": "apply_patch", "input": patch}
    assert events[-1][1]["response"]["output"] == [done]


async def test_engine_error_frame_ends_with_response_failed_after_draining():
    drained = []

    async def frames():
        yield _text("partial")
        yield {"error": {"message": "Upstream provider error: boom", "type": "rate_limit_error"}}
        drained.append(True)

    raw = [f async for f in proto.stream_events(frames(), _ctx(stream=True))]
    events = _parse_events(raw)
    names = [n for n, _ in events]
    assert names[-1] == "response.failed"
    assert "response.completed" not in names
    failed = events[-1][1]["response"]
    assert failed["status"] == "failed"
    assert failed["error"] == {"code": "rate_limit_exceeded", "message": "Upstream provider error: boom"}
    assert drained == [True]


async def test_empty_stream_still_terminates_with_response_completed():
    events = await _collect([])
    assert [n for n, _ in events] == ["response.created", "response.in_progress", "response.completed"]
    completed = events[-1][1]["response"]
    assert completed["output"] == []
    assert completed["usage"]["total_tokens"] == 0


async def test_length_finish_streams_completed_with_incomplete_status():
    events = await _collect([_text("trunc"), _finish("length"), _USAGE])
    assert events[-1][0] == "response.completed"
    resp = events[-1][1]["response"]
    assert resp["status"] == "incomplete"
    assert resp["incomplete_details"] == {"reason": "max_output_tokens"}


async def test_finish_is_called_after_the_terminal_event():
    """The post-[DONE] handoff contract: the engine's RequestLog commit runs
    in finish(), so the client must already have response.completed."""
    order: list[str] = []

    class Source:
        def __init__(self):
            self._it = _agen([_text("hi"), _finish(), _USAGE])

        def __aiter__(self):
            return self._it

        async def finish(self):
            order.append("finish")

        async def abort(self):
            order.append("abort")

    async for frame in proto.stream_events(Source(), _ctx(stream=True)):
        order.append(frame.split("\n", 1)[0])
    assert order[-2:] == ["event: response.completed", "finish"]


async def test_transformer_fault_aborts_the_source_instead_of_closing_it():
    """Our own bug must reach the engine as an adapter fault (abort), not a
    plain close the engine would log as a client disconnect."""
    order: list[str] = []
    bad = {"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {"tool_calls": [5]}}]}

    class Source:
        def __aiter__(self):
            return _agen([bad])

        async def finish(self):
            order.append("finish")

        async def abort(self):
            order.append("abort")

    with pytest.raises(AttributeError):
        async for _ in proto.stream_events(Source(), _ctx(stream=True)):
            pass
    assert order == ["abort"]


def test_stream_error_event_is_a_parseable_response_failed():
    ctx = _ctx(stream=True)
    ((name, data),) = _parse_events([proto.stream_error_event(ctx, "Internal server error")])
    assert name == "response.failed"
    assert data["response"]["status"] == "failed"
    assert data["response"]["error"] == {"code": "server_error", "message": "Internal server error"}
    assert data["response"]["id"] == ctx.response_id


# ── error envelope ─────────────────────────────────────────────────────


def test_error_response_uses_the_openai_envelope():
    r = proto.error_response(400, "bad input")
    assert r.status_code == 400
    body = json.loads(r.body)
    assert body == {"error": {"message": "bad input", "type": "invalid_request_error",
                              "param": None, "code": None}}


def test_native_status_maps_engine_types_onto_openai_statuses():
    assert proto.native_status(422, "model_not_found") == 404
    assert proto.native_status(422, "context_length_exceeded") == 400
    assert proto.native_status(503, "upstream_error") == 503
    assert proto.native_status(503, "upstream_timeout") == 503
    assert proto.native_status(422, None) == 422
    # Operator-side and permanent (our provider key, no provider, no capable
    # provider): non-retryable 403 like the other native surfaces, so Codex
    # does not back off and retry a request that cannot succeed.
    assert proto.native_status(503, "upstream_auth_error") == 403
    assert proto.native_status(422, "no_providers_configured") == 403
    assert proto.native_status(422, "no_capable_provider") == 403
