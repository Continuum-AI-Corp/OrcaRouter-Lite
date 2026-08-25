"""Tool-block id/name validation in both request translators (PR #64
round 11): empty or non-string ids reach the upstream as malformed tool
messages and come back as a retryable 503 — they must fail as a native 400."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.protocols.anthropic import AnthropicMessagesRequest, to_openai_request
from app.protocols.gemini import GeminiGenerateRequest
from app.protocols.gemini import to_openai_request as gemini_to_openai


@pytest.mark.parametrize("messages", [
    [{"role": "user", "content": [{"type": "tool_result", "content": "x"}]}],
    [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": 5, "content": "x"}]}],
    [{"role": "user", "content": "hi"},
     {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "input": {}}]}],
    [{"role": "user", "content": "hi"},
     {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "", "input": {}}]}],
])
def test_anthropic_malformed_tool_block_ids_render_native_400(messages):
    req = AnthropicMessagesRequest.model_validate({
        "model": "m", "max_tokens": 8, "messages": messages,
    })
    with pytest.raises(HTTPException) as exc:
        to_openai_request(req)
    assert exc.value.status_code == 400


def test_anthropic_well_formed_tool_blocks_still_translate():
    req = AnthropicMessagesRequest.model_validate({
        "model": "m", "max_tokens": 8, "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "f", "input": {"a": 1}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        ],
    })
    out = to_openai_request(req)
    assert out["messages"][1]["tool_calls"][0]["function"]["name"] == "f"
    assert out["messages"][2] == {"role": "tool", "tool_call_id": "t1", "content": "ok"}


@pytest.mark.parametrize("contents", [
    [{"role": "user", "parts": [{"functionCall": {"name": "f", "args": {}}}]}],
    [{"role": "model", "parts": [{"functionCall": {"args": {}}}]}],
    [{"role": "model", "parts": [{"functionCall": {"name": 3, "args": {}}}]}],
])
def test_gemini_function_call_in_user_turn_or_without_name_rejected(contents):
    req = GeminiGenerateRequest.model_validate({"contents": contents})
    with pytest.raises(HTTPException) as exc:
        gemini_to_openai(req, model="m", stream=False)
    assert exc.value.status_code == 400
