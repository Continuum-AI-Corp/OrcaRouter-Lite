"""Regression: openai-python >=1.51 sends `max_completion_tokens`.

`ChatCompletionRequest` used to declare only `max_tokens`, so Pydantic
stripped the new field and LiteLLM never saw an output cap. These tests
pin that the field survives validation and is present in the kwargs the
chat engine forwards downstream.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext


def _body(**overrides) -> ChatCompletionRequest:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "hi"}],
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
                    "finish_reason": "length",
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


def test_max_completion_tokens_survives_validation():
    body = _body(max_completion_tokens=10)
    assert body.max_completion_tokens == 10
    assert body.max_tokens is None


def test_max_completion_tokens_is_present_in_downstream_dump():
    """chat.py forwards `body.model_dump(exclude_none=True)` to LiteLLM."""
    dumped = _body(max_completion_tokens=10).model_dump(exclude_none=True)
    assert dumped["max_completion_tokens"] == 10
    assert "max_tokens" not in dumped


def test_max_tokens_still_accepted_without_inventing_max_completion_tokens():
    dumped = _body(max_tokens=64).model_dump(exclude_none=True)
    assert dumped["max_tokens"] == 64
    assert "max_completion_tokens" not in dumped


def test_both_output_caps_forwarded_as_is():
    """When both are set, forward both. Collapsing max_completion_tokens
    into max_tokens would break o-series / gpt-5, which reject max_tokens."""
    dumped = _body(max_tokens=64, max_completion_tokens=10).model_dump(exclude_none=True)
    assert dumped["max_tokens"] == 64
    assert dumped["max_completion_tokens"] == 10


def test_unknown_fields_are_still_silently_dropped():
    """Pydantic default is extra='ignore' — the original bug. An undeclared
    sibling of max_completion_tokens would still vanish; the declared field
    must not."""
    body = ChatCompletionRequest.model_validate(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "not_a_real_field": 1,
            "max_completion_tokens": 10,
        }
    )
    dumped = body.model_dump()
    assert dumped["max_completion_tokens"] == 10
    assert "not_a_real_field" not in dumped


@pytest.mark.asyncio
async def test_execute_chat_forwards_max_completion_tokens_to_litellm(monkeypatch):
    """The object sent to acompletion must carry max_completion_tokens so
    the upstream cap is applied (openai-python >=1.51 never sends max_tokens)."""
    kwargs = await _execute_and_capture_kwargs(monkeypatch, _body(max_completion_tokens=10))
    assert kwargs["max_completion_tokens"] == 10
    assert "max_tokens" not in kwargs
    assert kwargs["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_execute_chat_forwards_both_caps_when_set(monkeypatch):
    kwargs = await _execute_and_capture_kwargs(
        monkeypatch,
        _body(max_tokens=64, max_completion_tokens=10),
    )
    assert kwargs["max_tokens"] == 64
    assert kwargs["max_completion_tokens"] == 10
