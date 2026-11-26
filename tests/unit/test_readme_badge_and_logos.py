"""The README carries the "budgeted with" badge and a "Works with" logo strip.

The badge is a static shields.io image (no endpoint) linking to the landing
page with `ref=lite-badge`. The strip uses the logos bundled with the app, so
it shows every agent the app connects, and the logos' NOTICE covers the README
and the landing page as well as the app.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from packages.desktop import agents as ag

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
NOTICE = (ROOT / "desktop" / "ui" / "assets" / "agents" / "NOTICE.md").read_text(encoding="utf-8")

BADGE = (
    "[![budgeted with OrcaRouter Lite]"
    "(https://img.shields.io/badge/budgeted%20with-OrcaRouter%20Lite-2D7FF9)]"
    "(https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-badge)"
)


def _section(title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", README, re.M | re.S)
    assert m, f"README has no '## {title}' section"
    return m.group(1)


def test_badge_section_shows_the_badge_and_a_copy_paste_snippet():
    body = _section("Badge")
    assert body.count(BADGE) >= 2, "show the badge and the snippet to copy"
    assert re.search(r"```(?:md|markdown)\n" + re.escape(BADGE) + r"\n```", body)


def test_the_badge_link_carries_only_the_source_tag():
    for url in re.findall(r"https://continuum-ai-corp\.github\.io/OrcaRouter-Lite/[^\s)\"']*", README):
        assert url.endswith("?ref=lite-badge") or url.endswith("/"), url


@pytest.mark.parametrize("agent_id", sorted(ag.AGENTS))
def test_works_with_strip_shows_every_agent(agent_id):
    body = _section("Works with")
    name = ag.AGENTS[agent_id].name
    img = re.search(
        rf'<img src="desktop/ui/assets/agents/{re.escape(agent_id)}\.svg"[^>]*alt="{re.escape(name)}"', body
    )
    assert img, f"{agent_id} missing from the Works with strip"


def test_works_with_strip_links_the_trademark_notice():
    body = _section("Works with")
    assert "desktop/ui/assets/agents/NOTICE.md" in body


def test_notice_covers_the_readme_and_the_landing_page():
    assert "README" in NOTICE
    assert "landing page" in NOTICE
