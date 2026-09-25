"""OpenAI-compatible request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.response_format import normalize_response_format


class ChatMessage(BaseModel):
    role: str
    content: str | list[dict] | None = None
    name: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    n: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    # Pass-through for OpenAI's `logit_bias` map (token id → bias).
    # Without this field declared, Pydantic silently drops it and
    # LiteLLM never sees the token suppression / boost.
    logit_bias: dict[int, float] | None = None
    user: str | None = None
    seed: int | None = None
    response_format: dict | None = None
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    # Pass-through for OpenAI's `parallel_tool_calls`. Without this field
    # declared, Pydantic silently drops it and `false` never reaches the
    # upstream — the model keeps returning multiple tool calls in one turn.
    # `False` is falsy but not None, so `model_dump(exclude_none=True)`
    # still forwards it through `completion_kwargs` to LiteLLM.
    parallel_tool_calls: bool | None = None
    # Pass-through for OpenAI's `stream_options` block (e.g.
    # `{"include_usage": true}`). Without this field declared, Pydantic
    # silently drops it from the request and our own auto-inject in
    # chat.py can't see what the client actually asked for, so an
    # explicit `include_usage=false` from the client gets clobbered.
    stream_options: dict | None = None

    @field_validator("response_format")
    @classmethod
    def _normalize_response_format(cls, value: Any) -> Any:
        # LangChain json_schema / OpenAI structured outputs. The field is
        # already declared (so it is not silently dropped) but several
        # on-the-wire shapes are rejected upstream as
        # "Invalid schema for response_format". Normalize before dump.
        if isinstance(value, dict):
            return normalize_response_format(value)
        return value
