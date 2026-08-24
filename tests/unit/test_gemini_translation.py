"""Gemini API translation — pure-function unit tests (slice S6).

Request direction: Gemini wire format → internal OpenAI dict (camelCase
AND snake_case accepted, proto type enums normalized).
Response direction: OpenAI response dict → GenerateContentResponse dict.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.protocols.gemini import (
    GeminiGenerateRequest,
    normalize_gemini_schema,
    to_gemini_response,
    to_openai_request,
)


def _translate(payload: dict, model: str = "gemini-1.5-flash", stream: bool = False) -> dict:
    req = GeminiGenerateRequest.model_validate(payload)
    return to_openai_request(req, model=model, stream=stream)


# ── Request translation ──


def test_text_contents_and_roles():
    out = _translate({"contents": [
        {"role": "user", "parts": [{"text": "hi"}]},
        {"role": "model", "parts": [{"text": "hello"}]},
        {"parts": [{"text": "no role defaults to user"}]},
    ]})
    assert out["model"] == "gemini-1.5-flash"
    assert out["stream"] is False
    assert out["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "no role defaults to user"},
    ]


def test_inline_data_camel_and_snake_become_data_uri():
    for key, mime_key in (("inlineData", "mimeType"), ("inline_data", "mime_type")):
        out = _translate({"contents": [{
            "role": "user",
            "parts": [{"text": "look"}, {key: {mime_key: "image/png", "data": "aGk="}}],
        }]})
        parts = out["messages"][0]["content"]
        assert parts[1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,aGk="},
        }


def test_system_instruction_camel_and_snake():
    camel = _translate({
        "systemInstruction": {"parts": [{"text": "be brief"}]},
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    })
    snake = _translate({
        "system_instruction": {"parts": [{"text": "be brief"}]},
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
    })
    for out in (camel, snake):
        assert out["messages"][0] == {"role": "system", "content": "be brief"}


def test_function_declarations_normalize_uppercase_type_enums():
    out = _translate({
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "tools": [{"functionDeclarations": [{
            "name": "get_weather",
            "description": "d",
            "parameters": {
                "type": "OBJECT",
                "properties": {"city": {"type": "STRING"},
                               "days": {"type": "INTEGER"}},
                "required": ["city"],
            },
        }]}],
    })
    (tool,) = out["tools"]
    params = tool["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"]["city"]["type"] == "string"
    assert params["properties"]["days"]["type"] == "integer"
    assert params["required"] == ["city"]


def test_schema_normalization_recurses_and_spares_property_named_type():
    schema = {
        "type": "OBJECT",
        "properties": {
            "type": {"type": "STRING", "enum": ["A", "B"]},
            "items": {"type": "ARRAY", "items": {"type": "NUMBER"}},
        },
    }
    norm = normalize_gemini_schema(schema)
    assert norm["type"] == "object"
    assert norm["properties"]["type"]["type"] == "string"
    assert norm["properties"]["type"]["enum"] == ["A", "B"]  # enum values untouched
    assert norm["properties"]["items"]["items"]["type"] == "number"


def test_server_side_tools_rejected():
    with pytest.raises(HTTPException) as exc:
        _translate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "tools": [{"googleSearch": {}}],
        })
    assert exc.value.status_code == 400


@pytest.mark.parametrize("mode,expected", [
    ("AUTO", "auto"),
    ("NONE", "none"),
    ("ANY", "required"),
])
def test_tool_config_modes(mode, expected):
    out = _translate({
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "toolConfig": {"functionCallingConfig": {"mode": mode}},
    })
    assert out["tool_choice"] == expected


def test_tool_config_any_with_single_allowed_name_pins_function():
    out = _translate({
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "tool_config": {"function_calling_config": {
            "mode": "ANY", "allowed_function_names": ["f"],
        }},
    })
    assert out["tool_choice"] == {"type": "function", "function": {"name": "f"}}


def test_tool_config_any_with_multiple_names_constrains_tools_to_subset():
    """Google's ANY + allowedFunctionNames means "must call one of THESE";
    OpenAI "required" alone means "must call some tool", so the declared
    tools must be restricted to the allowed subset (undeclared allowed
    names are ignored, lenient)."""
    out = _translate({
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "tools": [{"functionDeclarations": [
            {"name": "a"}, {"name": "b"}, {"name": "c"},
        ]}],
        "toolConfig": {"functionCallingConfig": {
            "mode": "ANY", "allowedFunctionNames": ["c", "a", "ghost"],
        }},
    })
    assert out["tool_choice"] == "required"
    assert [t["function"]["name"] for t in out["tools"]] == ["a", "c"]


def test_tool_config_any_with_no_matching_names_rejected():
    with pytest.raises(HTTPException) as exc:
        _translate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "tools": [{"functionDeclarations": [{"name": "a"}]}],
            "toolConfig": {"functionCallingConfig": {
                "mode": "ANY", "allowedFunctionNames": ["x", "y"],
            }},
        })
    assert exc.value.status_code == 400


@pytest.mark.parametrize("fcc", [
    {"mode": {"x": 1}},                                     # mode not a string
    {"mode": "ANY", "allowedFunctionNames": {"f": {}}},     # names not a list
    {"mode": "ANY", "allowedFunctionNames": [{"name": "f"}]},  # entry not a string
])
def test_tool_config_wrong_field_types_render_native_400(fcc):
    """toolConfig is free-form in the wire schema; wrong field types must
    raise the native 400, not an AttributeError/KeyError that the route's
    blanket except turns into a 500."""
    with pytest.raises(HTTPException) as exc:
        _translate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "toolConfig": {"functionCallingConfig": fcc},
        })
    assert exc.value.status_code == 400


def test_generation_config_full_mapping():
    out = _translate({
        "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
        "generationConfig": {
            "temperature": 0.3, "topP": 0.8, "topK": 40,
            "maxOutputTokens": 256, "stopSequences": ["END"], "seed": 7,
            "responseMimeType": "application/json",
        },
    })
    assert out["temperature"] == 0.3
    assert out["top_p"] == 0.8
    assert out["max_tokens"] == 256
    assert out["stop"] == ["END"]
    assert out["seed"] == 7
    assert out["response_format"] == {"type": "json_object"}
    assert "top_k" not in out and "topK" not in out


def test_candidate_count_above_one_rejected():
    with pytest.raises(HTTPException) as exc:
        _translate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "generationConfig": {"candidateCount": 2},
        })
    assert exc.value.status_code == 400


def test_function_call_history_gets_synthetic_ids_paired_with_responses():
    out = _translate({"contents": [
        {"role": "user", "parts": [{"text": "weather in SF and NY"}]},
        {"role": "model", "parts": [
            {"functionCall": {"name": "get_weather", "args": {"city": "SF"}}},
            {"functionCall": {"name": "get_weather", "args": {"city": "NY"}}},
        ]},
        {"role": "user", "parts": [
            {"functionResponse": {"name": "get_weather", "response": {"temp": 72}}},
            {"functionResponse": {"name": "get_weather", "response": {"temp": 55}}},
        ]},
    ]})
    assistant = out["messages"][1]
    ids = [tc["id"] for tc in assistant["tool_calls"]]
    assert len(set(ids)) == 2
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"city": "SF"}

    tool_msgs = out["messages"][2:4]
    # earliest unmatched call pairs first (positional semantics)
    assert [m["tool_call_id"] for m in tool_msgs] == ids
    assert json.loads(tool_msgs[0]["content"]) == {"temp": 72}


def test_file_data_and_cached_content_rejected():
    with pytest.raises(HTTPException):
        _translate({"contents": [{
            "role": "user",
            "parts": [{"fileData": {"fileUri": "gs://x"}}],
        }]})
    with pytest.raises(HTTPException):
        _translate({
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "cachedContent": "cachedContents/123",
        })


def test_invalid_role_rejected():
    with pytest.raises(HTTPException) as exc:
        _translate({"contents": [{"role": "function", "parts": [{"text": "x"}]}]})
    assert exc.value.status_code == 400


def test_bare_string_contents_wraps_to_user_message():
    out = _translate({"contents": "just a prompt"})
    assert out["messages"] == [{"role": "user", "content": "just a prompt"}]


# ── Response translation ──


def _openai_response(**overrides) -> dict:
    base = {
        "id": "chatcmpl-1",
        "model": "gemini-1.5-flash",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello world"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    base.update(overrides)
    return base


def test_text_response_maps_to_gemini_shape():
    out = to_gemini_response(_openai_response())
    (cand,) = out["candidates"]
    assert cand["content"] == {"role": "model", "parts": [{"text": "Hello world"}]}
    assert cand["finishReason"] == "STOP"
    assert out["usageMetadata"] == {
        "promptTokenCount": 4, "candidatesTokenCount": 2, "totalTokenCount": 6,
    }
    assert out["modelVersion"] == "gemini-1.5-flash"
    assert out["responseId"] == "chatcmpl-1"


def test_tool_calls_become_function_call_parts():
    out = to_gemini_response(_openai_response(choices=[{
        "index": 0,
        "message": {
            "role": "assistant", "content": None,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
            }],
        },
        "finish_reason": "tool_calls",
    }]))
    (cand,) = out["candidates"]
    assert cand["content"]["parts"] == [
        {"functionCall": {"name": "get_weather", "args": {"city": "SF"}}},
    ]
    assert cand["finishReason"] == "STOP"


@pytest.mark.parametrize("finish,expected", [
    ("length", "MAX_TOKENS"),
    ("content_filter", "SAFETY"),
    (None, "STOP"),
])
def test_finish_reason_mapping(finish, expected):
    resp = _openai_response()
    resp["choices"][0]["finish_reason"] = finish
    assert to_gemini_response(resp)["candidates"][0]["finishReason"] == expected
