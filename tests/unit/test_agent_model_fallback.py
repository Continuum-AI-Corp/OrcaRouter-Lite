"""A coding agent asking for a model the user has no key for still works.

Claude Code sends claude-* names, Gemini CLI gemini-* names and Codex can be
switched to named models. In the desktop app an agent's own key should never
fail just because the user added a different vendor's key: the request is
routed like `model="auto"`, preferring the same vendor when one of its models
is available. Server keys keep strict pinned-model behaviour.
"""

from __future__ import annotations

from app.agent_model_fallback import fallback_preferences
from app.routes.chat import CATALOG

OPENAI_ONLY = {"gpt-4o-mini", "gpt-4.1"}
WITH_ANTHROPIC = OPENAI_ONLY | {"claude-sonnet-4-6", "claude-haiku-4-5"}


def _prefs(model, deployable, *, agent=True, desktop=True):
    return fallback_preferences(model, deployable, catalog=CATALOG, is_agent_key=agent, desktop_mode=desktop)


def test_a_model_that_can_be_served_is_left_alone():
    assert _prefs("gpt-4o-mini", OPENAI_ONLY) is None


def test_auto_is_left_alone():
    assert _prefs("auto", OPENAI_ONLY) is None


def test_an_unavailable_vendor_falls_back_to_any_model():
    assert _prefs("claude-sonnet-4-6", OPENAI_ONLY) == []


def test_an_unknown_name_prefers_the_same_vendor():
    # A newer dated name the catalog doesn't know yet, with an Anthropic key.
    prefs = _prefs("claude-sonnet-4-6-20991231", WITH_ANTHROPIC)
    assert prefs and set(prefs) <= {"claude-sonnet-4-6", "claude-haiku-4-5"}


def test_vendor_is_recognised_from_the_name_alone():
    assert _prefs("gemini-9-ultra", OPENAI_ONLY) == []
    assert set(_prefs("gpt-9-turbo", WITH_ANTHROPIC)) <= OPENAI_ONLY


def test_server_keys_and_non_desktop_engines_stay_strict():
    assert _prefs("claude-sonnet-4-6", OPENAI_ONLY, agent=False) is None
    assert _prefs("claude-sonnet-4-6", OPENAI_ONLY, desktop=False) is None


def test_nothing_deployable_is_left_to_the_normal_error():
    assert _prefs("claude-sonnet-4-6", set()) is None
