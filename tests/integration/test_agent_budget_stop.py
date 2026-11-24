"""D3: a daily budget per agent. Once an agent's spend today reaches its cap
the engine refuses that agent's generation requests with 429, and only
that agent's: other agents and keys keep working. Independent of the
workspace-wide budget mode."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.integration.test_desktop_api import _auth, _client, _key_id, _log, seeded  # noqa: F401
from tests.integration.test_desktop_budget_stop import (  # noqa: F401  (fixtures)
    _agent_key,
    app_with_models,
    desktop_app,
    desktop_dirs,
)


async def _other_agent_key(db_session, agent_id):
    from packages.auth.hashing import generate_api_key
    from packages.db.models.api_key import ApiKey

    full, h, prefix = generate_api_key()
    db_session.add(ApiKey(workspace_id="default", name=f"agent:{agent_id}", key_hash=h, key_prefix=prefix))
    await db_session.commit()
    return full


async def _agent_spend(db_session, agent_id, microcents, *, ago=timedelta(minutes=1)):
    key_id = await _key_id(db_session, f"agent:{agent_id}")
    db_session.add(_log(key_id, microcents, datetime.now(timezone.utc) - ago))
    await db_session.commit()


async def test_an_agent_at_its_cap_is_paused(app_with_models, seeded, desktop_dirs, db_session):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        claude = await _agent_key(c, root, home)
        codex = await _other_agent_key(db_session, "codex")
        r = await c.put("/v1/app/settings", headers=_auth(root), json={"agent_budgets": {"claude-code": 500}})
        assert r.status_code == 200
        await _agent_spend(db_session, "claude-code", 5_000_000)  # $5.00 == the cap
        stopped = await c.post("/v1/chat/completions", headers=_auth(claude), json={})
        stopped_messages = await c.post("/v1/messages", headers=_auth(claude), json={})
        other = await c.post("/v1/chat/completions", headers=_auth(codex), json={})
        script = await c.post("/v1/chat/completions", headers=_auth(root), json={})
        models = await c.get("/v1/models", headers=_auth(claude))
    assert stopped.status_code == 429
    assert ("Today's budget for Claude Code ($5.00) is used up, so Orca paused it. Raise it in Orca."
            in stopped.text)
    assert stopped_messages.status_code == 429
    assert other.status_code == 200 and script.status_code == 200 and models.status_code == 200


async def test_under_the_cap_or_spent_yesterday_is_fine(app_with_models, seeded, desktop_dirs, db_session):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        claude = await _agent_key(c, root, home)
        await c.put("/v1/app/settings", headers=_auth(root), json={"agent_budgets": {"claude-code": 500}})
        await _agent_spend(db_session, "claude-code", 4_990_000)
        await _agent_spend(db_session, "claude-code", 9_000_000, ago=timedelta(days=2))
        r = await c.post("/v1/chat/completions", headers=_auth(claude), json={})
    assert r.status_code == 200


async def test_other_agents_spend_does_not_count(app_with_models, seeded, desktop_dirs, db_session):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        claude = await _agent_key(c, root, home)
        await _other_agent_key(db_session, "codex")
        await c.put("/v1/app/settings", headers=_auth(root), json={"agent_budgets": {"claude-code": 100}})
        await _agent_spend(db_session, "codex", 50_000_000)
        r = await c.post("/v1/chat/completions", headers=_auth(claude), json={})
    assert r.status_code == 200


async def test_spend_through_an_earlier_key_of_the_same_agent_counts(app_with_models, seeded, desktop_dirs,
                                                                     db_session):
    # Reconnecting mints a new key; today's spend through the old one is
    # still that agent's.
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        await _agent_key(c, root, home)
        await _agent_spend(db_session, "claude-code", 3_000_000)
        claude = await _agent_key(c, root, home)  # reconnect: old key revoked
        await c.put("/v1/app/settings", headers=_auth(root), json={"agent_budgets": {"claude-code": 300}})
        r = await c.post("/v1/chat/completions", headers=_auth(claude), json={})
    assert r.status_code == 429


async def test_raising_the_cap_applies_at_once(app_with_models, seeded, desktop_dirs, db_session):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(app_with_models) as c:
        claude = await _agent_key(c, root, home)
        await c.put("/v1/app/settings", headers=_auth(root), json={"agent_budgets": {"claude-code": 100}})
        await _agent_spend(db_session, "claude-code", 2_000_000)
        assert (await c.post("/v1/chat/completions", headers=_auth(claude), json={})).status_code == 429
        await c.put("/v1/app/settings", headers=_auth(root), json={"agent_budgets": {"claude-code": 1000}})
        assert (await c.post("/v1/chat/completions", headers=_auth(claude), json={})).status_code == 200
