"""Reject non-positive max_tokens and n at the schema boundary.

ChatCompletionRequest previously accepted max_tokens=0 and n=0 without
complaint — both values are meaningless (zero tokens to generate, zero
choices to return) and most upstream providers reject them with a
confusing 400. Pydantic now fails closed with a clear validation error
before the request reaches the routing layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import ChatCompletionRequest

_BASE = {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}


class TestMaxTokensGuard:
    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="max_tokens"):
            ChatCompletionRequest.model_validate({**_BASE, "max_tokens": 0})

    def test_negative_rejected(self):
        with pytest.raises(ValidationError, match="max_tokens"):
            ChatCompletionRequest.model_validate({**_BASE, "max_tokens": -1})

    def test_positive_accepted(self):
        req = ChatCompletionRequest.model_validate({**_BASE, "max_tokens": 100})
        assert req.max_tokens == 100

    def test_none_accepted(self):
        req = ChatCompletionRequest.model_validate(_BASE)
        assert req.max_tokens is None


class TestNCountGuard:
    def test_zero_rejected(self):
        with pytest.raises(ValidationError, match="n"):
            ChatCompletionRequest.model_validate({**_BASE, "n": 0})

    def test_negative_rejected(self):
        with pytest.raises(ValidationError, match="n"):
            ChatCompletionRequest.model_validate({**_BASE, "n": -5})

    def test_positive_accepted(self):
        req = ChatCompletionRequest.model_validate({**_BASE, "n": 3})
        assert req.n == 3

    def test_none_accepted(self):
        req = ChatCompletionRequest.model_validate(_BASE)
        assert req.n is None


class TestTemperatureRange:
    def test_within_range(self):
        req = ChatCompletionRequest.model_validate({**_BASE, "temperature": 0.7})
        assert req.temperature == 0.7

    def test_negative_two_accepted(self):
        req = ChatCompletionRequest.model_validate({**_BASE, "temperature": -2.0})
        assert req.temperature == -2.0

    def test_above_two_rejected(self):
        with pytest.raises(ValidationError, match="temperature"):
            ChatCompletionRequest.model_validate({**_BASE, "temperature": 2.1})

    def test_below_negative_two_rejected(self):
        with pytest.raises(ValidationError, match="temperature"):
            ChatCompletionRequest.model_validate({**_BASE, "temperature": -2.1})
