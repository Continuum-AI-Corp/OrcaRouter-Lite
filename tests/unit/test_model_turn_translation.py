"""Gemini model-turn parts and the role-less Content form.

A `role:"model"` turn is translated into an OpenAI assistant message, which
carries only text and tool calls — so `inlineData` and `functionResponse`
parts had nowhere to go and were dropped without a word (a functionResponse
even consumed a pending call id, mispairing a later genuine response). Both
are now rejected, mirroring the functionCall-in-a-user-turn rule.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.protocols.gemini import GeminiGenerateRequest
from app.protocols.gemini import to_openai_request as translate


def _translate(payload: dict) -> dict:
    return translate(GeminiGenerateRequest.model_validate(payload), model="m", stream=False)


@pytest.mark.parametrize("part", [
    {"inlineData": {"mimeType": "image/png", "data": "AAAA"}},
    {"inline_data": {"mime_type": "image/png", "data": "AAAA"}},
    {"functionResponse": {"name": "f", "response": {"ok": True}}},
    {"function_response": {"name": "f", "response": {"ok": True}}},
])
def test_unrepresentable_model_turn_parts_are_rejected(part):
    with pytest.raises(HTTPException) as exc:
        _translate({"contents": [
            {"role": "user", "parts": [{"text": "hi"}]},
            {"role": "model", "parts": [part]},
        ]})
    assert exc.value.status_code == 400


def test_model_turn_text_and_function_call_still_translate():
    out = _translate({"contents": [
        {"role": "user", "parts": [{"text": "weather?"}]},
        {"role": "model", "parts": [
            {"text": "checking"},
            {"functionCall": {"name": "get_weather", "args": {"city": "SF"}}},
        ]},
        {"role": "user", "parts": [
            {"functionResponse": {"name": "get_weather", "response": {"c": 20}}}]},
    ]})
    assert [m["role"] for m in out["messages"]] == ["user", "assistant", "tool"]
    call = out["messages"][1]["tool_calls"][0]
    assert call["function"]["name"] == "get_weather"
    # the response pairs to that call's synthesized id
    assert out["messages"][2]["tool_call_id"] == call["id"]


def test_role_less_content_with_a_function_call_is_read_as_a_model_turn():
    """`role` is optional in the REST API; a turn carrying functionCall can
    only be the model's, so it must not be rejected as a user turn."""
    out = _translate({"contents": [
        {"parts": [{"text": "weather?"}]},
        {"parts": [{"functionCall": {"name": "get_weather", "args": {}}}]},
        {"parts": [{"functionResponse": {"name": "get_weather", "response": {"c": 20}}}]},
    ]})
    assert [m["role"] for m in out["messages"]] == ["user", "assistant", "tool"]


def test_role_less_plain_content_is_still_a_user_turn():
    out = _translate({"contents": [{"parts": [{"text": "hi"}]}]})
    assert out["messages"] == [{"role": "user", "content": "hi"}]
