"""The engine-side reader of the desktop settings that steer routing.

Chat routing reads these on every request, so they're cached for a couple
of seconds; saving settings forgets the cache (the same hook the budget gate
uses) so a change applies to the very next request.
"""

from __future__ import annotations

import pytest

from packages.desktop import budget, prefs


@pytest.fixture(autouse=True)
def _fresh():
    prefs.note_settings_changed()
    yield
    prefs.note_settings_changed()


async def _seed(db_session, desktop: dict | None):
    from app.seed import seed_initial_state
    from packages.db.models.workspace import Workspace

    await seed_initial_state(db_session)
    ws = await db_session.get(Workspace, "default")
    ws.settings_json = {"desktop": desktop} if desktop is not None else {}
    await db_session.commit()
    return ws


async def test_defaults_when_nothing_is_saved(db_session):
    await _seed(db_session, None)
    p = await prefs.load(db_session, "default")
    assert p.hosted_models == "free"
    assert p.agent_models == {} and p.agent_budgets == {}
    assert p.kept_substitutions == [] and p.dismissed_offers == {}
    assert p.local_models is None
    assert p.router_num_retries is None and p.router_cooldown_seconds is None


async def test_reads_saved_values(db_session):
    await _seed(db_session, {
        "hosted_models": "all",
        "agent_models": {"claude-code": {"main": "gpt-4.1", "background": None, "fallback_to_auto": False}},
        "agent_budgets": {"codex": 500},
        "local_models": ["ollama/qwen3"],
        "router_num_retries": 1,
        "router_cooldown_seconds": 5,
    })
    p = await prefs.load(db_session, "default")
    assert p.hosted_models == "all"
    assert p.agent_models["claude-code"].main == "gpt-4.1"
    assert p.agent_models["claude-code"].fallback_to_auto is False
    assert p.agent_budgets == {"codex": 500}
    assert p.local_models == ["ollama/qwen3"]
    assert (p.router_num_retries, p.router_cooldown_seconds) == (1, 5)


async def test_a_bad_stored_value_never_breaks_routing(db_session):
    await _seed(db_session, {"hosted_models": "everything", "agent_models": "nope", "router_num_retries": "x"})
    p = await prefs.load(db_session, "default")
    assert p.hosted_models == "free" and p.agent_models == {} and p.router_num_retries is None


async def test_cached_until_settings_change(db_session):
    ws = await _seed(db_session, {"hosted_models": "all"})
    assert (await prefs.load(db_session, "default")).hosted_models == "all"
    ws.settings_json = {"desktop": {"hosted_models": "free"}}
    await db_session.commit()
    assert (await prefs.load(db_session, "default")).hosted_models == "all"  # cached
    budget.note_settings_changed()  # what PUT /v1/app/settings calls
    assert (await prefs.load(db_session, "default")).hosted_models == "free"


def test_agent_of_key_names():
    assert prefs.agent_of("agent:claude-code") == "claude-code"
    assert prefs.agent_of("desktop-app") is None
    assert prefs.agent_of(None) is None
