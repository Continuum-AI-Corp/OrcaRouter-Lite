"""Verify _translate_error maps each LiteLLM exception to a distinct error_type.

Operators debugging routing failures need to distinguish network-level
connection failures (DNS, refused connection) from generic upstream
errors and explicit 503s. Without this distinction every 503 looks the
same in request_log and the dashboard.
"""

from __future__ import annotations

import pytest

litellm = pytest.importorskip("litellm")

from packages.litellm_adapter.client import _translate_error
from packages.litellm_adapter.types import UpstreamProviderError


class TestErrorTranslation:
    def test_context_window_exceeded(self):
        exc = litellm.ContextWindowExceededError(
            message="too long", model="gpt-4o", llm_provider="openai"
        )
        result = _translate_error(exc)
        assert isinstance(result, UpstreamProviderError)
        assert result.http_status == 422
        assert result.error_type == "context_length_exceeded"

    def test_not_found_error(self):
        exc = litellm.NotFoundError(
            message="model not found", model="fake-model", llm_provider="openai"
        )
        result = _translate_error(exc)
        assert result.http_status == 422
        assert result.error_type == "model_not_found"

    def test_rate_limit_error(self):
        exc = litellm.RateLimitError(
            message="rate limited", model="gpt-4o", llm_provider="openai"
        )
        result = _translate_error(exc)
        assert result.http_status == 429
        assert result.error_type == "rate_limit_error"

    def test_authentication_error(self):
        exc = litellm.AuthenticationError(
            message="bad key", model="gpt-4o", llm_provider="openai"
        )
        result = _translate_error(exc)
        assert result.http_status == 503
        assert result.error_type == "upstream_auth_error"

    def test_timeout_error(self):
        exc = litellm.Timeout(
            message="timed out", model="gpt-4o", llm_provider="openai"
        )
        result = _translate_error(exc)
        assert result.http_status == 503
        assert result.error_type == "upstream_timeout"

    def test_api_connection_error(self):
        exc = litellm.APIConnectionError(
            message="connection refused", model="gpt-4o", llm_provider="openai"
        )
        result = _translate_error(exc)
        assert result.http_status == 503
        assert result.error_type == "upstream_connection_error"

    def test_service_unavailable_error(self):
        exc = litellm.ServiceUnavailableError(
            message="service down", model="gpt-4o", llm_provider="openai"
        )
        result = _translate_error(exc)
        assert result.http_status == 503
        assert result.error_type == "upstream_unavailable"

    def test_generic_exception(self):
        result = _translate_error(RuntimeError("something else"))
        assert result.http_status == 503
        assert result.error_type == "upstream_error"
