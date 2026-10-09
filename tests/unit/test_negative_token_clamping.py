"""Regression: _build_log_row must clamp negative token counts to zero.

Some upstream providers return negative token counts in malformed usage
data. Without clamping, the RequestLog row persists negative values which
corrupts analytics dashboards (negative total tokens, negative spend
aggregates). The cost calculation already clamps via _compute_cost_microcents,
but the raw token count columns were unprotected."""

from unittest.mock import MagicMock, patch

import pytest

from app.routes.chat import _build_log_row
from app.schemas import ChatCompletionRequest, ChatMessage
from packages.auth.types import KeyContext


def _make_body(**overrides):
    defaults = {
        "model": "gpt-4o",
        "messages": [ChatMessage(role="user", content="hello")],
    }
    defaults.update(overrides)
    return ChatCompletionRequest(**defaults)


def _make_kc():
    kc = MagicMock(spec=KeyContext)
    kc.workspace_id = "ws-1"
    kc.key_id = "key-1"
    return kc


@pytest.mark.asyncio
async def test_build_log_row_clamps_negative_input_tokens():
    body = _make_body()
    kc = _make_kc()
    response = {
        "model": "gpt-4o",
        "usage": {"prompt_tokens": -5, "completion_tokens": 10},
        "_orca_meta": {"provider": "openai", "latency_ms": 100},
    }
    log = await _build_log_row(
        body=body, kc=kc, response=response,
        status_code=200, error_type=None,
        started_perf=0, strategy="balanced",
        requested_model="gpt-4o",
    )
    assert log.input_tokens == 0
    assert log.output_tokens == 10


@pytest.mark.asyncio
async def test_build_log_row_clamps_negative_output_tokens():
    body = _make_body()
    kc = _make_kc()
    response = {
        "model": "gpt-4o",
        "usage": {"prompt_tokens": 10, "completion_tokens": -3},
        "_orca_meta": {"provider": "openai", "latency_ms": 100},
    }
    log = await _build_log_row(
        body=body, kc=kc, response=response,
        status_code=200, error_type=None,
        started_perf=0, strategy="balanced",
        requested_model="gpt-4o",
    )
    assert log.input_tokens == 10
    assert log.output_tokens == 0


@pytest.mark.asyncio
async def test_build_log_row_clamps_both_negative():
    body = _make_body()
    kc = _make_kc()
    response = {
        "model": "gpt-4o",
        "usage": {"prompt_tokens": -1, "completion_tokens": -1},
        "_orca_meta": {"provider": "openai", "latency_ms": 100},
    }
    log = await _build_log_row(
        body=body, kc=kc, response=response,
        status_code=200, error_type=None,
        started_perf=0, strategy="balanced",
        requested_model="gpt-4o",
    )
    assert log.input_tokens == 0
    assert log.output_tokens == 0
