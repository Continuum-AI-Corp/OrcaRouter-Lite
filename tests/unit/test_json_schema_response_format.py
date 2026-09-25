"""Regression: LangChain `with_structured_output(method="json_schema")`.

LangChain 0.3 + OpenAI SDK `parse()` send a `response_format` block with
`type=json_schema` and `strict: true`. The field was already declared on
`ChatCompletionRequest`, so it was not dropped — but several on-the-wire
shapes (misplaced `strict`, function-calling `parameters`, missing
`additionalProperties`) are rejected upstream as
`Invalid schema for response_format`. These tests pin the normalized
shape that `execute_chat` forwards to LiteLLM.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.response_format import normalize_response_format
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext

LANGCHAIN_MOVIE_REVIEW = {
    "type": "json_schema",
    "json_schema": {
        "name": "MovieReview",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "rating": {"type": "number"},
                "summary": {"type": "string"},
            },
            "required": ["title", "rating", "summary"],
            "additionalProperties": False,
        },
    },
}


def _body(**overrides) -> ChatCompletionRequest:
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Review the movie Dune 2"}],
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
                    "message": {
                        "role": "assistant",
                        "content": '{"title":"Dune 2","rating":9.0,"summary":"ok"}',
                    },
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


def test_langchain_json_schema_survives_validation():
    body = _body(response_format=LANGCHAIN_MOVIE_REVIEW)
    dumped = body.model_dump(exclude_none=True)
    rf = dumped["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "MovieReview"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert rf["json_schema"]["schema"]["required"] == ["title", "rating", "summary"]


def test_json_object_is_left_untouched():
    dumped = _body(response_format={"type": "json_object"}).model_dump(exclude_none=True)
    assert dumped["response_format"] == {"type": "json_object"}


def test_misplaced_top_level_strict_is_nested():
    """LiteLLM / OpenAI docs put `strict` next to `type`; OpenAI rejects that."""
    rf = normalize_response_format(
        {
            "type": "json_schema",
            "strict": True,
            "json_schema": {
                "name": "MovieReview",
                "schema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
            },
        }
    )
    assert "strict" not in rf or rf.get("strict") is None
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert rf["json_schema"]["schema"]["required"] == ["title"]


def test_parameters_alias_is_mapped_to_schema():
    """LangChain's function-calling helper names the schema `parameters`."""
    rf = normalize_response_format(
        {
            "type": "json_schema",
            "json_schema": {
                "name": "MovieReview",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
            },
        }
    )
    assert "parameters" not in rf["json_schema"]
    assert rf["json_schema"]["schema"]["properties"]["title"]["type"] == "string"
    assert rf["json_schema"]["schema"]["additionalProperties"] is False


def test_strict_schema_gets_additional_properties_false():
    rf = normalize_response_format(
        {
            "type": "json_schema",
            "json_schema": {
                "name": "MovieReview",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "info": {
                            "type": "object",
                            "properties": {"year": {"type": "integer"}},
                        },
                    },
                },
            },
        }
    )
    schema = rf["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["title", "info"]
    assert schema["properties"]["info"]["additionalProperties"] is False
    assert schema["properties"]["info"]["required"] == ["year"]


def test_non_strict_schema_is_not_rewritten():
    raw = {
        "type": "json_schema",
        "json_schema": {
            "name": "Loose",
            "strict": False,
            "schema": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
            },
        },
    }
    assert normalize_response_format(raw)["json_schema"]["schema"] == raw["json_schema"]["schema"]


@pytest.mark.asyncio
async def test_execute_chat_forwards_langchain_json_schema(monkeypatch):
    kwargs = await _execute_and_capture_kwargs(
        monkeypatch, _body(response_format=LANGCHAIN_MOVIE_REVIEW)
    )
    rf = kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "MovieReview"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["properties"]["rating"]["type"] == "number"
    assert rf["json_schema"]["schema"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_execute_chat_forwards_normalized_misplaced_strict(monkeypatch):
    kwargs = await _execute_and_capture_kwargs(
        monkeypatch,
        _body(
            response_format={
                "type": "json_schema",
                "strict": True,
                "json_schema": {
                    "name": "MovieReview",
                    "schema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                    },
                },
            }
        ),
    )
    rf = kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert "strict" not in rf
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
