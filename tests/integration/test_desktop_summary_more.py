"""GET /v1/app/summary: what the panel shows about free, local and OrcaRouter
requests, offers, and each agent (Package B additions)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.test_desktop_api import _auth, _client, _key_id, desktop_app, desktop_dirs, seeded  # noqa: F401

NOW = datetime.now(timezone.utc)


def _row(api_key_id, *, cost=0, when=None, status=200, provider="anthropic", note=None, fallback=0,
         requested="auto", resolved="claude-sonnet-4-6", tokens=(1000, 500)):
    from packages.db.models.request_log import RequestLog

    return RequestLog(
        workspace_id="default", api_key_id=api_key_id, trace_id="t", model_requested=requested,
        model_resolved=resolved, provider=provider, routing_strategy="balanced", fallback_level=fallback,
        input_tokens=tokens[0], output_tokens=tokens[1], cost_microcents=cost, latency_ms=100,
        status_code=status, route_note=note, created_at=when or NOW - timedelta(minutes=1),
    )


async def _summary(c, root, **params):
    r = await c.get("/v1/app/summary", headers=_auth(root), params={"tz_offset_minutes": 0, **params})
    assert r.status_code == 200, r.text
    return r.json()


# ── today / week ────────────────────────────────────────────────────────


async def test_today_counts_free_requests_and_paid_spend(desktop_app, seeded, db_session):
    root, _ = seeded
    rid = await _key_id(db_session, "default")
    db_session.add_all([
        _row(rid, provider="orcarouter", note="free", resolved="deepseek/deepseek-v4-pro-free"),
        _row(rid, provider="orcarouter", note="free", resolved="qwen/qwen3.8-27b-free"),
        _row(rid, provider="orcarouter", cost=500_000, resolved="claude-sonnet-4.6"),
        _row(rid, provider="anthropic", cost=300_000),
        _row(rid, provider="orcarouter", note="free", when=NOW - timedelta(days=2)),  # not today
    ])
    await db_session.commit()
    async with _client(desktop_app) as c:
        s = await _summary(c, root)
    assert s["today"]["free_requests"] == 2
    assert s["today"]["paid_spend_microcents"] == 500_000
    assert s["today"]["spend_microcents"] == 800_000


async def test_week_splits_local_and_hosted_requests(desktop_app, seeded, db_session):
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    root, _ = seeded
    rid = await _key_id(db_session, "default")
    db_session.add_all([
        _row(rid, provider="local", note="local", resolved="ollama/qwen3-coder:30b", tokens=(2000, 1000)),
        _row(rid, provider="local", note="local", resolved="ollama/qwen3-coder:30b", tokens=(2000, 1000),
             when=NOW - timedelta(days=3)),
        _row(rid, provider="local", status=503, resolved="ollama/qwen3-coder:30b"),  # failed: not counted
        _row(rid, provider="orcarouter", cost=10_000),
        _row(rid, provider="anthropic", cost=10_000),
    ])
    await db_session.commit()
    async with _client(desktop_app) as c:
        s = await _summary(c, root)
    base = CATALOG_BY_ID["gpt-4o"]
    per = int(2000 * base.input_cost_per_token * 1_000_000 + 1000 * base.output_cost_per_token * 1_000_000)
    assert s["week"]["local_requests"] == 2
    assert s["week"]["local_saved_microcents"] == 2 * per
    assert s["week"]["hosted_requests"] == 1


# ── hosted ──────────────────────────────────────────────────────────────


async def test_hosted_block_without_a_key(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        h = (await _summary(c, root))["hosted"]
    assert h["configured"] is False
    assert h["models"] == "free"
    assert h["out_of_credit"] is False
    assert (h["month_spend_microcents"], h["month_requests"], h["month_rescued"], h["needs_paid_today"]) == (0, 0, 0, 0)
    assert h["console_url"] == "https://www.orcarouter.ai/console?ref=lite-panel"
    assert h["billing_url"] == "https://www.orcarouter.ai/console/topup?ref=lite-panel"
    assert h["token_url"] == "https://www.orcarouter.ai/console/token?ref=lite-panel"
    assert h["signup_url"] == "https://www.orcarouter.ai/register?ref=lite-panel"


async def test_hosted_month_spend_rescues_and_refusals(desktop_app, seeded, db_session):
    root, _ = seeded
    rid = await _key_id(db_session, "default")
    local_now = NOW
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    db_session.add_all([
        _row(rid, provider="orcarouter", cost=1_000_000, when=month_start + timedelta(minutes=5)),
        _row(rid, provider="orcarouter", cost=800_000, fallback=1),
        _row(rid, provider="orcarouter", cost=0, note="free"),
        _row(rid, provider="orcarouter", cost=0, status=402, note="out_of_credit"),  # failed: no spend
        _row(rid, provider="orcarouter", cost=5_000_000, when=month_start - timedelta(minutes=5)),  # last month
        _row(rid, provider="anthropic", cost=900_000, fallback=1),  # rescued, but not through OrcaRouter
        _row(rid, provider="orcarouter", status=422, note="needs_paid", resolved="auto"),
        _row(rid, provider="orcarouter", status=422, note="needs_paid", resolved="auto",
             when=NOW - timedelta(days=1, hours=1)),  # not today
    ])
    await db_session.commit()
    async with _client(desktop_app) as c:
        await c.put("/v1/app/settings", headers=_auth(root), json={"hosted_models": "all"})
        h = (await _summary(c, root))["hosted"]
    assert h["models"] == "all"
    assert h["month_spend_microcents"] == 1_800_000
    assert h["month_requests"] == 3
    assert h["month_rescued"] == 1
    assert h["needs_paid_today"] == 1


async def test_hosted_configured_and_out_of_credit(desktop_app, seeded, monkeypatch):
    from app import config
    from packages.desktop import hosted_state

    root, _ = seeded
    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-test-key-1234567890")
    config.get_settings.cache_clear()
    hosted_state.mark_out_of_credit()
    try:
        async with _client(desktop_app) as c:
            r = await c.get("/v1/app/summary", headers=_auth(root))
        h = r.json()["hosted"]
        assert h["configured"] is True and h["out_of_credit"] is True
        assert "sk-orca-test-key" not in r.text
    finally:
        config.get_settings.cache_clear()


# ── offers ──────────────────────────────────────────────────────────────


async def _failures(c, root, db_session):
    await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    cc = await _key_id(db_session, "agent:claude-code")
    rid = await _key_id(db_session, "default")
    db_session.add_all([
        _row(cc, status=503, note="no_fallback", resolved="claude-sonnet-4-6"),
        _row(cc, status=503, note="no_fallback", resolved="claude-sonnet-4-6"),
        _row(rid, status=429, note="no_fallback", resolved="claude-haiku-4-5"),
        _row(rid, status=503, note="no_fallback", provider="openai", resolved="gpt-4.1"),
        _row(cc, status=503, note="no_fallback", when=NOW - timedelta(days=1, hours=1)),  # yesterday
        _row(cc, status=401),  # a bad key isn't something a backup fixes
    ])
    await db_session.commit()


async def test_backup_offer_after_failures_with_no_fallback(desktop_app, seeded, db_session):
    root, _ = seeded
    async with _client(desktop_app) as c:
        assert (await _summary(c, root))["offers"] == []
        await _failures(c, root, db_session)
        offers = (await _summary(c, root))["offers"]
    assert offers == [{"id": "backup", "failed_today": 3, "provider": "anthropic", "agent": "claude-code",
                       "models": ["claude-sonnet-4-6", "claude-haiku-4-5"]}]


async def test_backup_offer_is_hidden_for_the_day_it_was_dismissed(desktop_app, seeded, db_session):
    root, _ = seeded
    today = NOW.date().isoformat()
    yesterday = (NOW - timedelta(days=1)).date().isoformat()
    async with _client(desktop_app) as c:
        await _failures(c, root, db_session)
        await c.put("/v1/app/settings", headers=_auth(root), json={"dismissed_offers": {"backup": today}})
        assert (await _summary(c, root))["offers"] == []
        await c.put("/v1/app/settings", headers=_auth(root), json={"dismissed_offers": {"backup": yesterday}})
        assert [o["id"] for o in (await _summary(c, root))["offers"]] == ["backup"]


async def test_no_backup_offer_once_orcarouter_is_configured(desktop_app, seeded, db_session, monkeypatch):
    from app import config

    root, _ = seeded
    async with _client(desktop_app) as c:
        await _failures(c, root, db_session)
        monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-test-key-1234567890")
        config.get_settings.cache_clear()
        try:
            assert (await _summary(c, root))["offers"] == []
        finally:
            config.get_settings.cache_clear()


# ── agents ──────────────────────────────────────────────────────────────


async def test_every_connected_agent_is_listed_with_its_state(desktop_app, seeded, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    (home / ".codex").mkdir()
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        await c.post("/v1/app/agents/codex/connect", headers=_auth(root))
        settings = home / ".claude" / "settings.json"
        settings.write_text(json.dumps({"theme": "dark"}))  # an update replaced Orca's settings
        agents = {a["id"]: a for a in (await _summary(c, root))["agents"]}
    assert agents["codex"]["state"] == "connected"
    assert agents["codex"]["today_microcents"] == 0
    assert agents["codex"]["substitutions"] == []
    assert agents["codex"]["budget_cents"] is None and agents["codex"]["paused"] is False
    assert agents["claude-code"]["state"] == "changed"
    assert agents["claude-code"]["name"] == "Claude Code"


async def test_reconnecting_a_changed_agent_through_the_api(desktop_app, seeded, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    settings = home / ".claude" / "settings.json"
    original = b'{"theme": "dark"}\n'
    settings.write_bytes(original)
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        settings.write_text('{"theme": "dark", "autoUpdates": true}')
        listed = {a["id"]: a for a in (await c.get("/v1/app/agents", headers=_auth(root))).json()["agents"]}
        assert listed["claude-code"]["changed"] is True
        r = await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        assert r.status_code == 200 and r.json()["changed"] is False
        assert "ANTHROPIC_BASE_URL" in json.loads(settings.read_text())["env"]
        await c.post("/v1/app/agents/claude-code/disconnect", headers=_auth(root))
    # Orca's values are gone and what the update added stays.
    assert json.loads(settings.read_text()) == {"theme": "dark", "autoUpdates": True}


async def test_agent_substitutions_today_skip_kept_ones(desktop_app, seeded, db_session):
    root, _ = seeded
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        cc = await _key_id(db_session, "agent:claude-code")
        rid = await _key_id(db_session, "default")
        sub = dict(note="substituted", provider="openai", resolved="gpt-4.1")
        db_session.add_all([
            *[_row(cc, requested="claude-sonnet-4-6", **sub) for _ in range(3)],
            _row(cc, requested="claude-haiku-4-5", note="substituted", provider="openai", resolved="gpt-4.1-mini"),
            _row(cc, requested="claude-opus-4-6", **sub),
            _row(cc, requested="claude-sonnet-4-6", when=NOW - timedelta(days=2), **sub),  # not today
            _row(rid, requested="claude-sonnet-4-6", **sub),  # not an agent key
        ])
        await db_session.commit()
        await c.put("/v1/app/settings", headers=_auth(root), json={"kept_substitutions": ["claude-opus-4-6"]})
        agents = {a["id"]: a for a in (await _summary(c, root))["agents"]}
    assert agents["claude-code"]["substitutions"] == [
        {"requested": "claude-sonnet-4-6", "served": "gpt-4.1", "count": 3},
        {"requested": "claude-haiku-4-5", "served": "gpt-4.1-mini", "count": 1},
    ]


async def test_agent_budget_and_paused(desktop_app, seeded, db_session):
    root, _ = seeded
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        cc = await _key_id(db_session, "agent:claude-code")
        db_session.add(_row(cc, cost=4_000_000))
        await db_session.commit()
        await c.put("/v1/app/settings", headers=_auth(root), json={"agent_budgets": {"claude-code": 500}})
        a = {x["id"]: x for x in (await _summary(c, root))["agents"]}["claude-code"]
        assert (a["budget_cents"], a["paused"]) == (500, False)
        db_session.add(_row(cc, cost=1_000_000))
        await db_session.commit()
        a = {x["id"]: x for x in (await _summary(c, root))["agents"]}["claude-code"]
    assert (a["budget_cents"], a["paused"]) == (500, True)


async def test_other_apps_keep_their_bucket(desktop_app, seeded, db_session):
    root, _ = seeded
    db_session.add(_row(await _key_id(db_session, "default"), cost=100))
    await db_session.commit()
    async with _client(desktop_app) as c:
        other = {a["id"]: a for a in (await _summary(c, root))["agents"]}["other"]
    assert other["state"] == "other" and other["substitutions"] == [] and other["paused"] is False


# ── local runtimes ──────────────────────────────────────────────────────


def _runtimes():
    from packages.desktop.local_models import LocalModel, Runtime

    m = LocalModel(id="ollama/qwen3-coder:30b", runtime="ollama", name="qwen3-coder:30b",
                   api_base="http://127.0.0.1:11434", context=262144, tools=True, vision=False)
    return [Runtime("ollama", "Ollama", "127.0.0.1:11434", True, (m,)),
            Runtime("lmstudio", "LM Studio", "127.0.0.1:1234", False)]


async def test_local_runtimes_from_the_last_discovery(desktop_app, seeded):
    from packages.desktop import local_models

    root, _ = seeded
    local_models.remember(_runtimes())
    async with _client(desktop_app) as c:
        local = (await _summary(c, root))["local"]
    assert local == {"runtimes": [
        {"id": "ollama", "name": "Ollama", "url": "127.0.0.1:11434", "running": True, "models": 1},
        {"id": "lmstudio", "name": "LM Studio", "url": "127.0.0.1:1234", "running": False, "models": 0},
    ]}


async def test_summary_never_waits_for_local_discovery(desktop_app, seeded, monkeypatch):
    from packages.desktop import local_models

    root, _ = seeded
    monkeypatch.delenv("ORCA_NO_LOCAL_MODELS", raising=False)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_discover(**_kw):
        started.set()
        await release.wait()
        return []

    monkeypatch.setattr(local_models, "discover", slow_discover)
    try:
        async with _client(desktop_app) as c:
            s = await asyncio.wait_for(_summary(c, root), timeout=5)
            await asyncio.wait_for(started.wait(), timeout=5)  # refreshed in the background
    finally:
        release.set()
    assert s["local"] == {"runtimes": []}


@pytest.mark.parametrize("field", ["today", "week", "hosted", "offers", "agents", "local"])
async def test_summary_keys_present(desktop_app, seeded, field):
    root, _ = seeded
    async with _client(desktop_app) as c:
        assert field in await _summary(c, root)


async def test_free_requests_count_every_free_answer_whatever_its_note(desktop_app, seeded, db_session):
    # A request an agent's model map sent to a free model is noted "mapped",
    # but it was still answered for free.
    root, _ = seeded
    rid = await _key_id(db_session, "default")
    db_session.add_all([
        _row(rid, provider="orcarouter", note="free", resolved="deepseek/deepseek-v4-pro-free"),
        _row(rid, provider="orcarouter", note="mapped", resolved="qwen/qwen3.8-27b-free"),
    ])
    await db_session.commit()
    async with _client(desktop_app) as c:
        s = await _summary(c, root)
    assert s["today"]["free_requests"] == 2


async def test_a_substitution_answered_by_a_free_or_local_model_is_shown(desktop_app, seeded, db_session):
    # Claude Code asked for Claude; a free (or local) model answered. The note
    # says "free"/"local" (it outranks "substituted"), but the user still
    # wasn't given the model the agent asked for.
    root, _ = seeded
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        cc = await _key_id(db_session, "agent:claude-code")
        db_session.add_all([
            _row(cc, requested="claude-sonnet-4-6", note="free", provider="orcarouter",
                 resolved="deepseek/deepseek-v4-pro-free"),
            _row(cc, requested="claude-sonnet-4-6", note="local", provider="local", resolved="ollama/qwen3-coder:30b"),
            _row(cc, requested="auto", note="free", provider="orcarouter", resolved="orcarouter/free"),  # asked for auto
            _row(cc, requested="claude-sonnet-4-6", note="mapped", provider="orcarouter",
                 resolved="qwen/qwen3.8-27b-free"),  # the user's own map
        ])
        await db_session.commit()
        agents = {a["id"]: a for a in (await _summary(c, root))["agents"]}
    assert agents["claude-code"]["substitutions"] == [
        {"requested": "claude-sonnet-4-6", "served": "deepseek/deepseek-v4-pro-free", "count": 1},
        {"requested": "claude-sonnet-4-6", "served": "ollama/qwen3-coder:30b", "count": 1},
    ]


async def test_an_orcarouter_key_that_no_longer_decrypts_is_not_configured(desktop_app, seeded, db_session):
    # The router skips a row it can't decrypt (after an encryption-key
    # change); the summary must agree, or the backup offer would hide and the
    # picker would call OrcaRouter's models available while none are deployed.
    from packages.db.models.provider_key import ProviderKey

    root, _ = seeded
    db_session.add(ProviderKey(provider="orcarouter", encrypted_key=b"not-a-real-ciphertext", is_enabled=True,
                               key_prefix="sk-orca"))
    await db_session.commit()
    async with _client(desktop_app) as c:
        s = await _summary(c, root)
    assert s["hosted"]["configured"] is False
