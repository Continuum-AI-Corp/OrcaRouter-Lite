"""Regression: OpenAI `logit_bias` must reach LiteLLM.

`ChatCompletionRequest` used to omit the field, so Pydantic stripped it
and `body.model_dump(exclude_none=True)` in chat.py never forwarded the
token-bias map (issue #126). Same class of silent-drop as
`max_completion_tokens`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext

# Token ids from the issue: "hello" / "Hello" on the GPT tokenizer.
_LOGIT_BIAS = {15339: -100.0, 31763: -100.0}
# Clients send JSON object keys as strings; Pydantic must coerce them.
_LOGIT_BIAS_JSON = {"15339": -100, "31763": -100}


def _body(**overrides) -> ChatCompletionRequest:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Say hello"}],
    }
    payload.update(overrides)
    return ChatCompletionRequest.model_validate(payload)


async def _execute_and_capture_kwargs(monkeypatch, body: ChatCompletionRequest) -> dict:
    from app import router_cache
    from app.routes.chat import execute_chat

    fake_client = AsyncMock()
    fake_client.acompletion = AsyncMock(
        return_value={
            "id": "chatcmpl-test",
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_orca_meta": {"provider": "openai", "latency_ms": 1},
        }
    )
    fake_client.strategy = "balanced"
    fake_client.preferred_models = []

    async def _fake_get_router(_session):
        return fake_client

    monkeypatch.setattr(router_cache, "get_router", _fake_get_router)

    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    kc = KeyContext(key_id="k", workspace_id="default", name="t", key_type="standard")
    await execute_chat(body, kc, db)

    fake_client.acompletion.assert_awaited_once()
    return fake_client.acompletion.await_args.kwargs


def test_logit_bias_survives_validation_and_dump():
    """JSON-style string keys coerce to int ids and survive exclude_none dump."""
    body = _body(logit_bias=_LOGIT_BIAS_JSON)
    assert body.logit_bias == _LOGIT_BIAS
    dumped = body.model_dump(exclude_none=True)
    assert dumped["logit_bias"] == _LOGIT_BIAS


def test_logit_bias_omitted_is_excluded_from_dump():
    dumped = _body().model_dump(exclude_none=True)
    assert "logit_bias" not in dumped


@pytest.mark.asyncio
async def test_execute_chat_forwards_logit_bias_to_litellm(monkeypatch):
    """The object sent to acompletion must carry logit_bias so the upstream
    token bias is applied (same dump path as max_completion_tokens)."""
    kwargs = await _execute_and_capture_kwargs(monkeypatch, _body(logit_bias=_LOGIT_BIAS_JSON))
    assert kwargs["logit_bias"] == _LOGIT_BIAS
    assert kwargs["model"] == "gpt-4o-mini"
