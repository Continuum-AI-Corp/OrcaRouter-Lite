"""Which requests the desktop daily-budget hard stop applies to.

Every route that makes a model generate (and so costs money) must be covered,
whichever protocol the agent speaks, or a coding agent could keep spending
past the budget. Listing models and counting tokens is free and stays open.
"""

from __future__ import annotations

import pytest

from packages.desktop.budget import is_generation


@pytest.mark.parametrize("path", [
    "/v1/chat/completions",
    "/v1/messages",
    "/v1/responses",  # Codex
    "/v1beta/models/gemini-2.5-pro:generateContent",
    "/v1beta/models/gemini-2.5-pro:streamGenerateContent",
])
def test_generation_routes_are_stopped(path):
    assert is_generation(path) is True


@pytest.mark.parametrize("path", [
    "/v1/models",
    "/v1/messages/count_tokens",
    "/v1beta/models",
    "/v1beta/models/gemini-2.5-pro:countTokens",
    "/v1/app/summary",
    "/health",
])
def test_free_routes_are_not(path):
    assert is_generation(path) is False
