"""H8: every link the engine hands out says where it came from, and nothing else."""

from __future__ import annotations

import pytest

from packages.desktop.links import LANDING_URL, SOURCES, with_ref


def test_adds_the_source_to_a_bare_url():
    assert with_ref("https://www.orcarouter.ai/register", "lite-setup") == (
        "https://www.orcarouter.ai/register?ref=lite-setup"
    )


def test_keeps_existing_query_and_fragment():
    assert with_ref("https://x.test/a?b=1#top", "lite-card") == "https://x.test/a?b=1&ref=lite-card#top"


def test_replaces_an_earlier_ref():
    assert with_ref("https://x.test/?ref=old&b=2", "lite-panel") == "https://x.test/?b=2&ref=lite-panel"


def test_landing_page_link():
    assert with_ref(LANDING_URL, "lite-card") == "https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-card"


def test_only_known_sources():
    assert {"lite-setup", "lite-card", "lite-badge", "lite-panel", "lite-share", "lite-dashboard", "lite-site"} == set(SOURCES)
    with pytest.raises(ValueError):
        with_ref("https://x.test/", "user-42")


@pytest.mark.parametrize("url", ["", None])
def test_no_url_stays_none(url):
    assert with_ref(url, "lite-setup") is None
