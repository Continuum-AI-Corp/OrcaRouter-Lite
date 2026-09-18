"""ChatCompletionRequest field pass-through.

Unknown OpenAI parameters are ignored by Pydantic unless declared, so a
client sending `parallel_tool_calls=false` used to get a quiet drop
before LiteLLM ever saw the flag (issue #124).
"""

from __future__ import annotations


def test_parallel_tool_calls_false_survives_request_building():
    from app.schemas import ChatCompletionRequest

    body = ChatCompletionRequest.model_validate(
        {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "get_weather", "parameters": {"type": "object"}},
                }
            ],
            "parallel_tool_calls": False,
        }
    )
    assert body.parallel_tool_calls is False
    kwargs = body.model_dump(exclude_none=True)
    assert kwargs["parallel_tool_calls"] is False


def test_parallel_tool_calls_true_is_forwarded():
    from app.schemas import ChatCompletionRequest

    body = ChatCompletionRequest.model_validate(
        {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "parallel_tool_calls": True,
        }
    )
    kwargs = body.model_dump(exclude_none=True)
    assert kwargs["parallel_tool_calls"] is True


def test_parallel_tool_calls_omitted_is_excluded_from_dump():
    from app.schemas import ChatCompletionRequest

    body = ChatCompletionRequest.model_validate(
        {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )
    assert body.parallel_tool_calls is None
    kwargs = body.model_dump(exclude_none=True)
    assert "parallel_tool_calls" not in kwargs
