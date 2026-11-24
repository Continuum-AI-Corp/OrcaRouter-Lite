"""The GitHub Pages landing page in site/.

A static page with no build step: one HTML file, a stylesheet and two small
scripts, all served from the site itself (no third-party scripts, no cookies).
The download button picks the visitor's OS; every other OS stays one click
away. The agent logos are the app's own files, under the same notice.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from packages.desktop import agents as ag

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
APP_LOGOS = ROOT / "desktop" / "ui" / "assets" / "agents"
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
RELEASES = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest"


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []
        self.h1 = ""
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {k: v or "" for k, v in attrs}))
        self._in_h1 = self._in_h1 or tag == "h1"

    def handle_endtag(self, tag):
        if tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        if self._in_h1:
            self.h1 += data


@pytest.fixture(scope="module")
def html() -> str:
    return (SITE / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page(html) -> _Tags:
    p = _Tags()
    p.feed(html)
    return p


def test_headline(page):
    assert " ".join(page.h1.split()) == "Put a budget on every coding agent"


def test_mobile_viewport_and_both_themes(page):
    assert ("meta", {"name": "viewport", "content": "width=device-width, initial-scale=1"}) in page.tags
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert "color-scheme" in css


def test_scripts_and_styles_are_served_by_the_site(page):
    for tag, attrs in page.tags:
        if tag == "script":
            src = attrs.get("src", "")
            assert src and not re.match(r"[a-z]+:|//", src), f"external or inline script: {attrs}"
            assert (SITE / src).is_file()
        if tag == "link" and attrs.get("rel") == "stylesheet":
            href = attrs["href"]
            assert not re.match(r"[a-z]+:|//", href) or href.startswith("https://fonts.googleapis.com/")


def test_content_security_policy_allows_nothing_else(page):
    csp = next(a["content"] for t, a in page.tags if t == "meta" and a.get("http-equiv") == "Content-Security-Policy")
    assert "script-src 'self'" in csp
    assert "default-src 'self'" in csp
    assert "connect-src https://api.github.com" in csp


def test_download_links_work_without_javascript(page):
    links = {a.get("id"): a.get("href", "") for t, a in page.tags if t == "a" and a.get("id")}
    assert links["download-primary"].startswith(RELEASES)
    for target in ("mac-arm", "mac-intel", "windows", "linux-deb", "linux-appimage"):
        assert links[f"dl-{target}"] == f"{RELEASES}#{target}"


def test_install_commands(html):
    assert "brew install --cask continuum-ai-corp/tap/orcarouter-lite" in html
    assert "winget install OrcaRouter.Lite" in html
    assert "brew install continuum-ai-corp/tap/orcarouter-lite" in html


def test_orcarouter_section(html):
    assert "Free models to start, one key for every model" in html
    assert 'href="https://www.orcarouter.ai/register?ref=lite-site"' in html
    assert "failover between providers" in html
    assert "per request" in html


def test_outgoing_links_carry_no_user_identifier(page):
    for tag, attrs in page.tags:
        href = attrs.get("href", "")
        if tag == "a" and "orcarouter.ai" in href:
            assert re.fullmatch(r"https://www\.orcarouter\.ai/[a-z/]*(\?ref=lite-[a-z]+)?", href), href


@pytest.mark.parametrize("agent_id", sorted(ag.AGENTS))
def test_logo_strip_uses_the_apps_own_files(page, agent_id):
    copy = SITE / "assets" / "agents" / f"{agent_id}.svg"
    assert copy.read_bytes() == (APP_LOGOS / f"{agent_id}.svg").read_bytes()
    imgs = [a for t, a in page.tags if t == "img" and a.get("src") == f"assets/agents/{agent_id}.svg"]
    assert imgs and imgs[0].get("alt") == ag.AGENTS[agent_id].name


def test_logo_notice_travels_with_the_logos(html):
    assert (SITE / "assets" / "agents" / "NOTICE.md").read_bytes() == (APP_LOGOS / "NOTICE.md").read_bytes()
    assert {p.stem for p in (SITE / "assets" / "agents").glob("*.svg")} == set(ag.AGENTS)
    assert "trademarks of their owners" in html


def test_every_local_reference_exists(page):
    for _tag, attrs in page.tags:
        for attr in ("src", "href", "srcset"):
            ref = attrs.get(attr, "")
            if ref and not re.match(r"[a-z]+:|//|#", ref):
                path = SITE / ref.split("#")[0].split(" ")[0]
                assert (path / "index.html" if path.is_dir() else path).is_file(), ref


def test_pages_workflow_deploys_site_with_pinned_actions():
    wf = WORKFLOW.read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s*(\S+)", wf)
    assert {u.split("@")[0] for u in uses} >= {
        "actions/checkout", "actions/configure-pages", "actions/upload-pages-artifact", "actions/deploy-pages",
    }
    for u in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u), f"pin {u} to a full commit SHA"
    assert re.search(r"path:\s*site/?\s*$", wf, re.M)
    assert "pages: write" in wf and "id-token: write" in wf
    assert "node --test tests/site/*.test.cjs" in wf


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_download_logic_node_tests_pass():
    tests = sorted(str(p) for p in (ROOT / "tests" / "site").glob("*.test.cjs"))
    assert tests
    r = subprocess.run(["node", "--test", *tests], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
