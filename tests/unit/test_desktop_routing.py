"""Small rules behind the desktop app's routing (app/desktop_routing.py)."""

from __future__ import annotations

from app.desktop_routing import is_paid_hosted, needs_paid_reason, twin


def test_twin_matches_dots_and_hyphens_in_a_version():
    assert twin("claude-sonnet-4-6", {"claude-sonnet-4.6", "gpt-4.1"}) == "claude-sonnet-4.6"
    assert twin("claude-sonnet-4.6", {"claude-sonnet-4-6"}) == "claude-sonnet-4-6"


def test_no_twin_when_absent_or_ambiguous():
    assert twin("claude-sonnet-4-6", {"claude-sonnet-4-5"}) is None
    assert twin("a-1-2", {"a.1-2", "a-1.2"}) is None
    assert twin("gpt-4.1", {"gpt-4.1"}) is None  # itself is not its twin


def test_twin_ignores_a_release_date_suffix():
    # Claude Code asks for its background model by dated id; OrcaRouter
    # serves the same model undated (claude-haiku-4.5).
    assert twin("claude-haiku-4-5-20251001", {"claude-haiku-4.5", "claude-sonnet-4.6"}) == "claude-haiku-4.5"
    assert twin("claude-haiku-4-5-20251001", {"claude-haiku-4-5"}) == "claude-haiku-4-5"
    assert twin("claude-haiku-4-5-20251001", {"claude-sonnet-4.6"}) is None
    assert twin("gpt-4o-2024-08-06", {"gpt-4o"}) is None  # only Anthropic-style YYYYMMDD


def test_paid_hosted_names_include_vendor_spellings():
    assert is_paid_hosted("claude-sonnet-4.6")
    assert is_paid_hosted("claude-sonnet-4-6")
    assert not is_paid_hosted("orcarouter/free")
    assert not is_paid_hosted("my-own-model")


def test_needs_paid_reasons():
    assert needs_paid_reason({"vision", "tools"}, 10) == "images"
    assert needs_paid_reason(set(), 500_000) == "very long context"
