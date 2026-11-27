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


def test_seconds_until_reset_counts_to_the_next_local_midnight():
    from datetime import datetime, timezone

    from packages.desktop.budget import seconds_until_reset

    local_now = datetime.now().astimezone()
    almost_midnight = local_now.replace(hour=23, minute=59, second=30, microsecond=0)
    assert seconds_until_reset(almost_midnight) == 30
    just_after = local_now.replace(hour=0, minute=0, second=10, microsecond=0)
    assert seconds_until_reset(just_after) == 24 * 3600 - 10
    assert seconds_until_reset(almost_midnight.astimezone(timezone.utc)) == 30
    assert 0 < seconds_until_reset() <= 25 * 3600  # never zero, DST-safe bound
