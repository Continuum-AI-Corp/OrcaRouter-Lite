"""Issue 18: when every model in a fallback chain fails, the error names what
each of them said, not only the first model's error (which LiteLLM raises,
and which was often just "cooling down")."""

from __future__ import annotations

import litellm
import pytest

from packages.litellm_adapter import client as c


@pytest.fixture(autouse=True)
def _fresh():
    c._LAST_FAILURE.clear()
    yield
    c._LAST_FAILURE.clear()


def _bad_request(msg="tool_choice 'required' is incompatible with thinking"):
    return litellm.BadRequestError(message=msg, model="kimi-k2.6", llm_provider="openai")


def _unavailable():
    return litellm.ServiceUnavailableError(message="The upstream provider is temporarily unavailable",
                                           model="gpt-5.5", llm_provider="openai")


class _Cooldown(ValueError):
    def __init__(self, cooldown_list):
        super().__init__("No deployments available for selected model, Try again in 60 seconds.")
        self.cooldown_list = cooldown_list


NAMES = {"hosted::gpt-5.5": "gpt-5.5", "moonshot::kimi": "kimi-k2.6", "own::gpt-5.5": "gpt-5.5"}


def test_every_model_tried_is_named_with_its_own_reason():
    first, second = _unavailable(), _bad_request()
    classify, summary = c._explain_chain(first, [("hosted::gpt-5.5", first), ("moonshot::kimi", second)], NAMES)
    assert classify is first  # the first model's error still decides the type
    assert summary == ("Every model tried failed. gpt-5.5: The upstream provider is temporarily unavailable; "
                       "kimi-k2.6: tool_choice 'required' is incompatible with thinking")


def test_a_single_model_needs_no_summary():
    first = _unavailable()
    assert c._explain_chain(first, [("hosted::gpt-5.5", first)], NAMES) == (first, None)


def test_a_model_that_was_only_cooling_down_is_explained_by_its_last_real_failure():
    earlier = _unavailable()
    c._record_failure("hosted::gpt-5.5", earlier, now=100.0)
    kimi = _bad_request()
    cooldown = _Cooldown(["hosted::gpt-5.5"])
    classify, summary = c._explain_chain(cooldown, [("moonshot::kimi", kimi)], NAMES, now=130.0)
    assert classify is earlier  # not "No deployments available"
    assert "No deployments available" not in summary
    assert "gpt-5.5: The upstream provider is temporarily unavailable" in summary
    assert "kimi-k2.6: tool_choice" in summary


def test_an_old_failure_does_not_explain_a_cooldown():
    c._record_failure("hosted::gpt-5.5", _unavailable(), now=100.0)
    cooldown = _Cooldown(["hosted::gpt-5.5"])
    assert c._explain_chain(cooldown, [], NAMES, now=100.0 + c.LAST_FAILURE_TTL_SECONDS + 1) == (cooldown, None)


def test_two_deployments_of_one_model_are_one_line():
    a, b = _unavailable(), _unavailable()
    kimi = _bad_request()
    _, summary = c._explain_chain(a, [("hosted::gpt-5.5", a), ("own::gpt-5.5", b), ("moonshot::kimi", kimi)], NAMES)
    assert summary.count("gpt-5.5:") == 1


def test_recording_tags_the_exception_with_its_deployment():
    exc = _bad_request()
    c._record_failure("moonshot::kimi", exc)
    assert exc.failed_deployment_id == "moonshot::kimi"
