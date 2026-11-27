"""OrcaRouter refusing its free models for the whole account (not eligible,
or the free allowance used up) is an account state, not a rate limit or an
empty wallet: recognised, remembered for a while so auto skips the free
models, and never reported as "out of credit"."""

from __future__ import annotations

import pytest

from packages.desktop import hosted_state


@pytest.fixture(autouse=True)
def _fresh():
    hosted_state.reset()
    yield
    hosted_state.reset()


def _exc(status: int, message: str, deployment: str, code: str | None = None):
    import litellm

    cls = {429: litellm.RateLimitError}.get(status)
    if cls is not None:
        exc = cls(message=message, llm_provider="openai", model="m")
    else:
        exc = litellm.APIError(status_code=status, message=message, llm_provider="openai", model="m")
    exc.failed_deployment_id = deployment
    if code:
        exc.body = {"code": code, "message": message}
    return exc


NOT_ELIGIBLE = "Free models are not available to this account yet. Link an established GitHub account."
USED_UP = "your orcarouter/free allowance is used up - top up your balance"


def test_free_refusal_window():
    hosted_state.mark_free_unavailable("why", now=1000.0)
    assert hosted_state.free_unavailable(now=1599.0)
    assert hosted_state.free_unavailable_reason() == "why"
    assert not hosted_state.free_unavailable(now=1601.0)


@pytest.mark.parametrize(("status", "message", "deployment", "code"), [
    (429, NOT_ELIGIBLE, "hosted::z-ai/glm-5.3-flash-free", "free_rate_limited"),
    (429, NOT_ELIGIBLE, "hosted::z-ai/glm-5.3-flash-free", None),
    (402, USED_UP, "hosted::orcarouter/free", "free_quota_exhausted"),
    (402, "Insufficient credit", "hosted::orcarouter/free", None),
])
def test_an_account_level_free_refusal_is_recognised(status, message, deployment, code):
    from packages.litellm_adapter.client import _translate_error, free_refusal

    exc = _exc(status, message, deployment, code)
    assert free_refusal(exc)
    err = _translate_error(exc)
    assert (err.http_status, err.error_type) == (403, "free_unavailable")


def test_a_real_free_rate_limit_stays_a_rate_limit():
    from packages.litellm_adapter.client import _translate_error, free_refusal

    exc = _exc(429, "Too many requests, slow down", "hosted::z-ai/glm-5.3-flash-free", "free_rate_limited")
    assert not free_refusal(exc)
    assert _translate_error(exc).error_type == "rate_limit_error"


def test_a_402_from_a_paid_orcarouter_model_is_still_out_of_credit():
    from packages.litellm_adapter.client import _translate_error

    err = _translate_error(_exc(402, "Insufficient credit", "hosted::anthropic/claude-sonnet-4.6"))
    assert (err.http_status, err.error_type) == (402, "out_of_credit")


async def test_the_watcher_notes_a_refusal_a_later_model_rescued():
    # The request succeeded through a fallback, so no final error: the
    # per-attempt callback is what notices the free model was refused.
    import litellm

    from packages.litellm_adapter.client import free_refusal_watcher

    seen = []
    watcher = free_refusal_watcher(seen.append)
    exc = litellm.RateLimitError(message=NOT_ELIGIBLE, llm_provider="openai", model="m")
    kwargs = {"exception": exc, "litellm_params": {"model_info": {"id": "hosted::z-ai/glm-5.3-flash-free"}}}
    await watcher.async_log_failure_event(kwargs, None, 0, 0)
    assert seen and NOT_ELIGIBLE in seen[0]
    other = litellm.RateLimitError(message=NOT_ELIGIBLE, llm_provider="openai", model="m")
    await watcher.async_log_failure_event(
        {"exception": other, "litellm_params": {"model_info": {"id": "openai::gpt-4o-mini"}}}, None, 0, 0)
    assert len(seen) == 1  # an own key's 429 isn't OrcaRouter refusing free models


def test_the_desktop_router_registers_the_watcher_once(monkeypatch):
    import litellm

    from app import router_cache

    monkeypatch.setattr(litellm, "callbacks", [])
    monkeypatch.setattr(router_cache, "_free_watcher", None)
    router_cache._watch_free_refusals()
    router_cache._watch_free_refusals()
    assert litellm.callbacks == [router_cache._free_watcher]


def test_the_reason_is_orcarouters_text_without_litellms_prefix():
    import litellm

    from packages.litellm_adapter.client import free_refusal

    exc = litellm.APIError(status_code=402, message=USED_UP, llm_provider="openai", model="m")
    exc.failed_deployment_id = "hosted::orcarouter/free"
    assert free_refusal(exc) == USED_UP
