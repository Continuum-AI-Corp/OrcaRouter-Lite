"""OpenAI-compatible request/response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
    user: str | None = None
    seed: int | None = None
    response_format: dict | None = None
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    # Pass-through for OpenAI's `stream_options` block (e.g.
    # `{"include_usage": true}`). Without this field declared, Pydantic
    # silently drops it from the request and our own auto-inject in
    # chat.py can't see what the client actually asked for, so an
    # explicit `include_usage=false` from the client gets clobbered.
    stream_options: dict | None = None
