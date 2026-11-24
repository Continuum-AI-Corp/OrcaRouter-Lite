"""Every agent the app lists shows its own logo.

The marks are bundled with the app (desktop/ui/assets/agents/<id>.svg) so
they work offline, and are loaded through <img>, which never runs scripts
or fetches anything an SVG references. They still have to be plain static
drawings: no scripts, event handlers, links, embedded images or HTML.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from packages.desktop import agents as ag

UI = Path(__file__).resolve().parents[2] / "desktop" / "ui"
LOGOS = UI / "assets" / "agents"
SVG = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("agent_id", sorted(ag.AGENTS))
def test_every_agent_has_a_bundled_logo(agent_id):
    path = LOGOS / f"{agent_id}.svg"
    assert path.is_file(), f"{agent_id} has no logo"
    assert path.stat().st_size < 32_000


@pytest.mark.parametrize("path", sorted(LOGOS.glob("*.svg")), ids=lambda p: p.name)
def test_logos_are_static_drawings(path):
    text = path.read_text()
    assert not re.search(r"<script|<foreignObject|<image|\bon[a-z]+\s*=|href\s*=|url\(\s*['\"]?(?!#)", text, re.I), path.name
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", text))
    assert root.tag == f"{SVG}svg"
    assert root.get("viewBox"), f"{path.name} needs a viewBox to scale"


def test_no_logo_is_left_without_an_agent():
    assert {p.stem for p in LOGOS.glob("*.svg")} == set(ag.AGENTS)
    assert (LOGOS / "NOTICE.md").is_file()


def test_the_ui_knows_every_logo():
    lib = (UI / "lib.js").read_text()
    m = re.search(r"export const AGENT_LOGOS = new Set\(\[(.*?)\]\)", lib, re.S)
    assert m, "lib.js should export AGENT_LOGOS"
    listed = set(re.findall(r'"([a-z0-9-]+)"', m.group(1)))
    assert listed == set(ag.AGENTS)
