"""Issue 30: a local runtime that isn't running is recognised as such, not
reported as a slow upstream (LiteLLM raises a timeout or a connection error
depending on the runtime and the platform)."""

from __future__ import annotations

import httpx
import litellm
import pytest

from packages.litellm_adapter.client import _translate_error


def _chain(outer: Exception, inner: BaseException, deployment_id: str) -> Exception:
    outer.__cause__ = inner
    outer.failed_deployment_id = deployment_id
    return outer


def _timeout():
    return litellm.Timeout(message="Request timed out", model="qwen2.5-1.5b-instruct", llm_provider="openai")


def _conn_error():
    return litellm.APIConnectionError(message="Cannot connect to host", llm_provider="ollama", model="qwen2.5:1.5b")


@pytest.mark.parametrize("outer,inner", [
    (_timeout, lambda: httpx.ConnectTimeout("connect timed out")),       # LM Studio on Windows
    (_conn_error, lambda: httpx.ConnectError("connection refused")),     # Ollama
])
def test_a_local_runtime_that_refuses_the_connection_is_not_running(outer, inner):
    err = _translate_error(_chain(outer(), inner(), "local::lmstudio/qwen2.5-1.5b-instruct"))
    assert err.error_type == "local_runtime_unavailable"
    assert err.deployment_id == "local::lmstudio/qwen2.5-1.5b-instruct"


def test_a_cloud_connect_timeout_stays_a_timeout():
    err = _translate_error(_chain(_timeout(), httpx.ConnectTimeout("x"), "openai::gpt-4o"))
    assert err.error_type == "upstream_timeout"


def test_a_slow_local_model_stays_a_timeout():
    err = _translate_error(_chain(_timeout(), httpx.ReadTimeout("x"), "local::ollama/qwen3-coder:30b"))
    assert err.error_type == "upstream_timeout"
