"""Anthropic Messages API translation — pure-function unit tests (slice S2).

Request direction: Anthropic wire format → internal OpenAI dict.
Response direction: OpenAI response dict → Anthropic message dict.
No app, no mocks — the translators are pure.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.protocols.anthropic import (
    AnthropicMessagesRequest,
    to_anthropic_response,
    to_openai_request,
)


def _req(**overrides) -> AnthropicMessagesRequest:
    base = {
        "model": "claude-3-5-sonnet-latest",
        "max_tokens": 128,
        "messages": [{"role": "user", "content": "hi"}],
    }
    base.update(overrides)
    return AnthropicMessagesRequest.model_validate(base)


# ── Request translation ──


def test_minimal_request_maps_model_max_tokens_stream():
    out = to_openai_request(_req())
    assert out["model"] == "claude-3-5-sonnet-latest"
    assert out["max_tokens"] == 128
    assert out["stream"] is False
    assert out["messages"] == [{"role": "user", "content": "hi"}]


def test_missing_max_tokens_fails_validation():
    with pytest.raises(ValidationError):
        AnthropicMessagesRequest.model_validate({
            "model": "m", "messages": [{"role": "user", "content": "hi"}],
        })


@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_max_tokens_fails_validation(value):
    """A budget < 1 can never succeed upstream; rejecting it here keeps it
    a 400 invalid_request_error instead of a retryable 500 api_error."""
    with pytest.raises(ValidationError):
        AnthropicMessagesRequest.model_validate({
            "model": "m", "max_tokens": value,
            "messages": [{"role": "user", "content": "hi"}],
        })


def test_system_string_becomes_leading_system_message():
    out = to_openai_request(_req(system="be brief"))
    assert out["messages"][0] == {"role": "system", "content": "be brief"}
    assert out["messages"][1]["role"] == "user"


def test_system_blocks_join_text_and_drop_cache_control():
    out = to_openai_request(_req(system=[
        {"type": "text", "text": "part one", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "part two"},
    ]))
    assert out["messages"][0] == {"role": "system", "content": "part one\n\npart two"}


def test_image_base64_block_becomes_data_uri_part():
    out = to_openai_request(_req(messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "look"},
            {"type": "image", "source": {
                "type": "base64", "media_type": "image/png", "data": "aGk=",
            }},
        ],
    }]))
    parts = out["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "look"}
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aGk="},
    }


def test_image_url_source_passes_url_through():
    out = to_openai_request(_req(messages=[{
        "role": "user",
        "content": [{"type": "image", "source": {"type": "url", "url": "https://x/y.png"}}],
    }]))
    parts = out["messages"][0]["content"]
    assert parts == [{"type": "image_url", "image_url": {"url": "https://x/y.png"}}]


def test_single_text_block_collapses_to_plain_string():
    out = to_openai_request(_req(messages=[
        {"role": "user", "content": [{"type": "text", "text": "just text"}]},
    ]))
    assert out["messages"][0] == {"role": "user", "content": "just text"}


def test_assistant_tool_use_becomes_tool_calls():
    out = to_openai_request(_req(messages=[
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "checking"},
            {"type": "tool_use", "id": "toolu_1", "name": "get_weather",
             "input": {"city": "SF"}},
        ]},
    ]))
    assistant = out["messages"][1]
    assert assistant["content"] == "checking"
    (tc,) = assistant["tool_calls"]
    assert tc["id"] == "toolu_1"
    assert tc["function"]["name"] == "get_weather"
    assert json.loads(tc["function"]["arguments"]) == {"city": "SF"}


@pytest.mark.parametrize("field,value", [
    ("temperature", 1.5),
    ("temperature", -0.1),
    ("top_p", 1.5),
    ("top_k", -1),
])
def test_out_of_range_sampling_params_fail_validation(field, value):
    """Out-of-range values are rejected by the upstream as a BadRequest,
    which the engine reports as a retryable 500 api_error — bound them
    here so the caller gets an honest 400 instead."""
    with pytest.raises(ValidationError):
        _req(**{field: value})


def test_tool_result_image_rides_along_in_the_following_user_message():
    """An OpenAI tool message can only carry text, so an image returned by
    a tool (a screenshot, the common case) is attached to the user message
    that follows the tool results rather than being dropped."""
    out = to_openai_request(_req(messages=[
        {"role": "user", "content": "look"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "call_1", "name": "shot", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": [
                {"type": "text", "text": "captured"},
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": "AAAA",
                }},
            ]},
        ]},
    ]))
    tool_msg, user_msg = out["messages"][-2], out["messages"][-1]
    assert tool_msg == {
        "role": "tool", "tool_call_id": "call_1", "content": "captured",
    }
    assert user_msg["role"] == "user"
    assert user_msg["content"] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]


def test_tool_result_splits_into_tool_message_then_user_message():
    out = to_openai_request(_req(messages=[
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "72F"},
            {"type": "text", "text": "and tomorrow?"},
        ]},
    ]))
    tool_msg = out["messages"][2]
    assert tool_msg == {"role": "tool", "tool_call_id": "toolu_1", "content": "72F"}
    assert out["messages"][3] == {"role": "user", "content": "and tomorrow?"}


def test_multiple_tool_results_emit_in_order():
    out = to_openai_request(_req(messages=[
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [{"type": "text", "text": "A"}]},
            {"type": "tool_result", "tool_use_id": "toolu_2", "content": "B"},
        ]},
    ]))
    assert [m["tool_call_id"] for m in out["messages"]] == ["toolu_1", "toolu_2"]
    assert [m["content"] for m in out["messages"]] == ["A", "B"]


def test_tools_translate_and_server_tool_types_rejected():
    out = to_openai_request(_req(tools=[
        {"name": "f", "description": "d", "input_schema": {"type": "object"}},
        {"type": "custom", "name": "g", "input_schema": {"type": "object"}},
    ]))
    assert out["tools"][0] == {
        "type": "function",
        "function": {"name": "f", "parameters": {"type": "object"}, "description": "d"},
    }
    assert out["tools"][1]["function"]["name"] == "g"

    with pytest.raises(HTTPException) as exc:
        to_openai_request(_req(tools=[{"type": "web_search_20250305", "name": "web_search"}]))
    assert exc.value.status_code == 400


@pytest.mark.parametrize("tc,expected", [
    ({"type": "auto"}, "auto"),
    ({"type": "any"}, "required"),
    ({"type": "none"}, "none"),
    ({"type": "tool", "name": "f"}, {"type": "function", "function": {"name": "f"}}),
])
def test_tool_choice_variants(tc, expected):
    out = to_openai_request(_req(tool_choice=tc))
    assert out["tool_choice"] == expected


def test_sampling_and_metadata_mapping():
    out = to_openai_request(_req(
        temperature=0.5, top_p=0.9, top_k=40,
        stop_sequences=["END"], metadata={"user_id": "u-1"},
    ))
    assert out["temperature"] == 0.5
    assert out["top_p"] == 0.9
    assert out["stop"] == ["END"]
    assert out["user"] == "u-1"
    assert "top_k" not in out  # dropped, documented


def test_thinking_param_and_history_blocks_dropped_not_rejected():
    out = to_openai_request(_req(
        thinking={"type": "enabled", "budget_tokens": 1024},
        messages=[
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "...", "signature": "s"},
                {"type": "text", "text": "answer"},
            ]},
            {"role": "user", "content": "ok"},
        ],
    ))
    assert "thinking" not in out
    assert out["messages"][0] == {"role": "assistant", "content": "answer"}


def test_stop_sequences_truncated_to_openai_cap():
    out = to_openai_request(_req(stop_sequences=["a", "b", "c", "d", "e"]))
    assert out["stop"] == ["a", "b", "c", "d"]


def test_thinking_only_assistant_message_keeps_empty_content():
    """Regression: an assistant turn of ONLY thinking blocks (Claude Code
    sends these on extended-thinking/compacted histories) must not become
    content=None with no tool_calls — the engine's exclude_none dump would
    then send a bare {"role": "assistant"}, which OpenAI-compatible
    upstreams reject with a 400."""
    out = to_openai_request(_req(messages=[
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "...", "signature": "s"},
            {"type": "redacted_thinking", "data": "x"},
        ]},
        {"role": "user", "content": "and?"},
    ]))
    assert out["messages"][1] == {"role": "assistant", "content": ""}


def test_document_block_rejected_with_400():
    with pytest.raises(HTTPException) as exc:
        to_openai_request(_req(messages=[{
            "role": "user",
            "content": [{"type": "document", "source": {"type": "base64", "data": "x"}}],
        }]))
    assert exc.value.status_code == 400


def test_system_role_inside_messages_is_tolerated():
    """Claude Code 2.x sends role:"system" entries inside messages[] on some
    internal requests (spec says top-level `system` only). They must
    translate to OpenAI system messages, not 400 — a 400 breaks Claude Code."""
    out = to_openai_request(_req(messages=[
        {"role": "system", "content": "internal instruction"},
        {"role": "user", "content": "hi"},
    ]))
    assert out["messages"][0] == {"role": "system", "content": "internal instruction"}
    # block-form content flattens to text
    out2 = to_openai_request(_req(messages=[
        {"role": "system", "content": [{"type": "text", "text": "as blocks"}]},
        {"role": "user", "content": "hi"},
    ]))
    assert out2["messages"][0] == {"role": "system", "content": "as blocks"}


def test_invalid_role_rejected_with_400():
    with pytest.raises(HTTPException) as exc:
        to_openai_request(_req(messages=[{"role": "tool", "content": "nope"}]))
    assert exc.value.status_code == 400


# ── Response translation ──


def _openai_response(**overrides) -> dict:
    base = {
        "id": "chatcmpl-1",
        "model": "gpt-4o-mini",
        "object": "chat.completion",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello world"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    base.update(overrides)
    return base


def test_text_response_maps_to_anthropic_shape():
    out = to_anthropic_response(_openai_response())
    assert out["type"] == "message"
    assert out["role"] == "assistant"
    assert out["id"].startswith("msg_")
    assert out["model"] == "gpt-4o-mini"
    assert out["content"] == [{"type": "text", "text": "Hello world"}]
    assert out["stop_reason"] == "end_turn"
    assert out["usage"] == {"input_tokens": 4, "output_tokens": 2}


def test_tool_calls_become_tool_use_blocks_with_parsed_input():
    out = to_anthropic_response(_openai_response(choices=[{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_9",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
            }],
        },
        "finish_reason": "tool_calls",
    }]))
    assert out["stop_reason"] == "tool_use"
    (block,) = out["content"]
    assert block == {
        "type": "tool_use", "id": "call_9",
        "name": "get_weather", "input": {"city": "SF"},
    }


def test_malformed_tool_arguments_fall_back_to_empty_object():
    out = to_anthropic_response(_openai_response(choices=[{
        "index": 0,
        "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "c", "type": "function",
                "function": {"name": "f", "arguments": "{not json"},
            }],
        },
        "finish_reason": "tool_calls",
    }]))
    assert out["content"][0]["input"] == {}


@pytest.mark.parametrize("finish,expected", [
    ("length", "max_tokens"),
    ("content_filter", "refusal"),
    (None, "end_turn"),
])
def test_stop_reason_mapping(finish, expected):
    resp = _openai_response()
    resp["choices"][0]["finish_reason"] = finish
    assert to_anthropic_response(resp)["stop_reason"] == expected


def test_multipart_list_content_flattens_to_a_text_block():
    """The OpenAI wire format allows a response message's content to be a
    list of parts. Emitting it verbatim would produce a text block whose
    `text` is an array, which the Anthropic SDK cannot parse."""
    resp = _openai_response()
    resp["choices"][0]["message"]["content"] = [
        {"type": "text", "text": "Hello "},
        {"type": "text", "text": "world"},
    ]
    out = to_anthropic_response(resp)
    assert out["content"] == [{"type": "text", "text": "Hello world"}]


def test_empty_content_and_no_tools_yields_empty_blocks():
    resp = _openai_response()
    resp["choices"][0]["message"]["content"] = None
    assert to_anthropic_response(resp)["content"] == []


# ── wire-type validation: tools, tool_choice, text values ──


@pytest.mark.parametrize("tool", [
    {"name": 123, "input_schema": {"type": "object"}},
    {"name": "", "input_schema": {"type": "object"}},
    {"name": "f", "input_schema": "oops"},
    {"name": "f", "input_schema": ["not", "a", "schema"]},
    {"name": "f", "input_schema": {"type": "object"}, "description": 42},
])
def test_malformed_tool_definitions_render_native_400(tool):
    """`tools` is list[dict] with no inner validation. A numeric name or a
    string input_schema used to pass every layer and reach the upstream,
    whose BadRequest came back as a retryable 503 the SDK keeps retrying
    for a request that can never succeed."""
    with pytest.raises(HTTPException) as exc:
        to_openai_request(_req(tools=[tool]))
    assert exc.value.status_code == 400


def test_tool_choice_with_non_string_name_rejected():
    with pytest.raises(HTTPException) as exc:
        to_openai_request(_req(tool_choice={"type": "tool", "name": 7}))
    assert exc.value.status_code == 400


def test_tool_without_input_schema_gets_an_empty_object_schema():
    out = to_openai_request(_req(tools=[{"name": "f"}]))
    assert out["tools"][0]["function"]["parameters"] == {"type": "object", "properties": {}}
    assert "description" not in out["tools"][0]["function"]


@pytest.mark.parametrize("payload", [
    {"system": [{"type": "text", "text": 123}]},
    {"messages": [{"role": "user", "content": [{"type": "text", "text": ["x"]}]}]},
    {"messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": 1.5}]},
    ]},
    {"messages": [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1",
         "content": [{"type": "text", "text": 0}]},
    ]}]},
])
def test_non_string_text_values_render_native_400(payload):
    """A non-string `text` used to crash the message join with a TypeError
    (a 500 the SDK retries) or ride through to the upstream as a malformed
    part; either way a 400 is the honest answer."""
    with pytest.raises(HTTPException) as exc:
        to_openai_request(_req(**payload))
    assert exc.value.status_code == 400


def test_null_text_values_are_treated_as_empty():
    out = to_openai_request(_req(
        system=[{"type": "text", "text": None}],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": None}, {"type": "text", "text": "hi"},
        ]}],
    ))
    # an all-empty system yields no system message at all
    assert out["messages"][0]["role"] == "user"
    assert out["messages"][0]["content"] == [
        {"type": "text", "text": ""}, {"type": "text", "text": "hi"},
    ]
