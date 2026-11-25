"""Validate the supported Chat Completions cache-control surface."""

import pytest
from pydantic import ValidationError

from app.schemas import ChatCompletionRequest


@pytest.mark.parametrize("controls", [
    {"prompt_cache_options": {"mode": "disabled"}},
    {"prompt_cache_options": {"mode": False}},
    {"prompt_cache_options": {"ttl": "12h"}},
    {"prompt_cache_key": False},
])
def test_invalid_cache_controls_fail_validation(controls):
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate({
            "model": "gpt-5.6", "messages": [{"role": "user", "content": "hi"}],
            **controls,
        })
