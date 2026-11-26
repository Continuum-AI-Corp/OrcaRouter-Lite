"""Listing drafts for agents' docs (docs/listings/) show the config Orca writes.

Each draft is a short, neutral pull-request description plus the snippet a
reader would add by hand. For agents Orca configures itself, every value in
the snippet must be one Orca really writes (packages/desktop/agents.py), so a
connector change that isn't reflected here fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from packages.desktop import agents as ag

ROOT = Path(__file__).resolve().parents[2]
LISTINGS = ROOT / "docs" / "listings"
BASE = "http://127.0.0.1:8765"
KEY = "sk-orca-…"

DRAFTS = {
    "claude-code": "claude-code.md",
    "opencode": "opencode.md",
    "goose": "goose.md",
    "kilo": "kilo.md",
    "hermes": "hermes.md",
    "pi": "pi.md",
    "omp": "omp.md",
    "openclaw": "openclaw.md",
    "kimi-code": "kimi-code.md",
    "zed": "zed.md",
    "cursor": "cursor.md",
    "cline": "cline.md",
}


def _leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)
    else:
        yield value


def _text(name: str) -> str:
    return (LISTINGS / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("agent_id", sorted(DRAFTS))
def test_each_draft_has_a_pr_title_description_and_snippet(agent_id):
    text = _text(DRAFTS[agent_id])
    assert text.startswith(f"# {ag.AGENTS[agent_id].name}")
    for heading in ("## Where", "## Pull request title", "## Pull request description", "## Proposed addition"):
        assert heading in text, f"{DRAFTS[agent_id]} lacks {heading}"
    assert "```" in text
    assert BASE in text
    assert "github.com/Continuum-AI-Corp/OrcaRouter-Lite" in text


@pytest.mark.parametrize("agent_id", sorted(a for a in DRAFTS if ag.AGENTS[a].setup == "auto"))
def test_snippet_matches_what_orca_writes(agent_id):
    text = _text(DRAFTS[agent_id])
    # Goose runs its key command without a shell, so ~ wouldn't expand there:
    # its draft shows the absolute path Orca writes (for a user "you").
    home = "/Users/you" if agent_id == "goose" else "~"
    key_file = Path(f"{home}/.orcarouter-lite/keys/{agent_id}.key") if agent_id in ag.KEY_FILE_AGENTS else None
    files = ag._desired_values(agent_id, BASE, KEY, key_file=key_file, current={})
    for rel, values in files.items():
        assert rel.split("/")[-1] in text, f"{agent_id}: name the file {rel}"
        for dotted in values:
            assert dotted.split(".")[-1] in text, f"{agent_id}: {dotted} missing"
        for leaf in _leaves(values):
            if isinstance(leaf, bool):
                continue
            assert str(leaf) in text, f"{agent_id}: value {leaf!r} missing from the snippet"


def test_manual_agents_use_the_settings_orca_tells_people_to_paste():
    assert "openai_compatible" in _text("zed.md") and "ORCA_API_KEY" in _text("zed.md")
    assert "OpenAI Compatible" in _text("cline.md")
    assert "Override OpenAI Base URL" in _text("cursor.md")
    for name in ("zed.md", "cline.md", "cursor.md"):
        assert f"{BASE}/v1" in _text(name)
        assert re.search(r"\bauto\b", _text(name))


def test_awesome_list_entries():
    text = _text("awesome-lists.md")
    for target in ("awesome-claude-code", "awesome-selfhosted", "awesome-ai-coding"):
        assert target in text


def test_drafts_stay_neutral_and_free_of_secrets():
    for path in LISTINGS.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sk-orca-[A-Za-z0-9]{8,}", text), path.name
        assert not re.search(r"\b(best|ultimate|revolutionary|blazing)\b", text, re.I), path.name
