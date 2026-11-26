"""GET /v1/app/report + POST /v1/app/report/save (H7), GET /v1/app/share/card (V2)
and GET /v1/app/share/setup (V3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tests.integration.test_desktop_api import _auth, _client, _key_id, desktop_app, desktop_dirs, seeded  # noqa: F401
from tests.integration.test_desktop_summary_more import _row

NOW = datetime.now(timezone.utc)
THIS_MONDAY = (NOW - timedelta(days=NOW.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
LAST_MONDAY = THIS_MONDAY - timedelta(days=7)


async def _week_of_requests(c, root, db_session):
    await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
    cc = await _key_id(db_session, "agent:claude-code")
    rid = await _key_id(db_session, "default")
    db_session.add_all([
        _row(cc, cost=1_250_000, when=LAST_MONDAY + timedelta(hours=10), resolved="claude-sonnet-4-6"),
        _row(cc, cost=750_000, when=LAST_MONDAY + timedelta(days=6, hours=23), resolved="claude-sonnet-4-6"),
        _row(cc, cost=100_000, when=LAST_MONDAY + timedelta(days=2), resolved="gpt-4.1", provider="openai",
             fallback=1),
        _row(rid, cost=40_000, when=LAST_MONDAY + timedelta(days=3), resolved="gpt-4o-mini", provider="openai"),
        _row(cc, cost=9_000_000, when=LAST_MONDAY - timedelta(minutes=1)),  # the week before
        _row(cc, cost=5_000_000, when=LAST_MONDAY + timedelta(days=1), status=500),  # failed: no spend
        _row(cc, cost=300_000, when=THIS_MONDAY + timedelta(minutes=1)),  # this week
    ])
    await db_session.commit()


# ── weekly report ───────────────────────────────────────────────────────


async def test_last_weeks_report_as_csv(desktop_app, seeded, db_session):
    root, _ = seeded
    async with _client(desktop_app) as c:
        await _week_of_requests(c, root, db_session)
        r = await c.get("/v1/app/report", headers=_auth(root),
                        params={"format": "csv", "week": "last", "tz_offset_minutes": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"filename", "content"}
    assert body["filename"] == f"orca-week-{LAST_MONDAY.date().isoformat()}.csv"
    lines = body["content"].strip().splitlines()
    assert lines[0] == "week_start,agent,model,provider,requests,input_tokens,output_tokens,spend_usd"
    week = LAST_MONDAY.date().isoformat()
    assert f"{week},Claude Code,claude-sonnet-4-6,anthropic,2,2000,1000,2.00" in lines
    assert f"{week},Claude Code,gpt-4.1,openai,1,1000,500,0.10" in lines
    assert f"{week},Other apps,gpt-4o-mini,openai,1,1000,500,0.04" in lines
    assert len(lines) == 4


async def test_this_weeks_report_as_markdown(desktop_app, seeded, db_session):
    root, _ = seeded
    async with _client(desktop_app) as c:
        await _week_of_requests(c, root, db_session)
        r = await c.get("/v1/app/report", headers=_auth(root), params={"format": "markdown", "week": "this"})
        last = (await c.get("/v1/app/report", headers=_auth(root), params={"format": "markdown"})).json()
    body = r.json()
    assert body["filename"] == f"orca-week-{THIS_MONDAY.date().isoformat()}.md"
    assert body["content"].startswith("# Coding-agent spend")
    assert "| Claude Code | $0.30 | 1 |" in body["content"]
    # Last week by default: spend by agent, and by model.
    assert "Total: $2.14 across 4 requests" in last["content"]
    assert "| Claude Code | $2.10 | 3 |" in last["content"]
    assert "| claude-sonnet-4-6 | anthropic | $2.00 | 2 |" in last["content"]
    assert "1 failed request was retried on another provider." in last["content"]


async def test_report_rejects_unknown_formats(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/report", headers=_auth(root), params={"format": "pdf"})
    assert r.status_code == 422


async def test_save_writes_to_downloads(desktop_app, seeded, db_session, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    (home / "Downloads").mkdir()
    async with _client(desktop_app) as c:
        await _week_of_requests(c, root, db_session)
        r = await c.post("/v1/app/report/save", headers=_auth(root), json={"format": "csv"})
    assert r.status_code == 200, r.text
    name = f"orca-week-{LAST_MONDAY.date().isoformat()}.csv"
    assert r.json() == {"path": f"~/Downloads/{name}"}
    assert (home / "Downloads" / name).read_text().startswith("week_start,agent")


async def test_save_without_a_downloads_folder_uses_home(desktop_app, seeded, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/report/save", headers=_auth(root), json={"format": "markdown", "week": "this"})
    assert r.json() == {"path": f"~/orca-week-{THIS_MONDAY.date().isoformat()}.md"}
    assert (home / f"orca-week-{THIS_MONDAY.date().isoformat()}.md").exists()


# ── share ───────────────────────────────────────────────────────────────


async def test_share_card_has_totals_only(desktop_app, seeded, db_session, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    (home / ".codex").mkdir()
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        await c.post("/v1/app/agents/codex/connect", headers=_auth(root))
        await c.post("/v1/app/agents/opencode/connect", headers=_auth(root))  # connected, but unused this week
        cc = await _key_id(db_session, "agent:claude-code")
        cx = await _key_id(db_session, "agent:codex")
        db_session.add_all([
            _row(cc, cost=2_000_000, when=NOW - timedelta(days=1), fallback=1),
            _row(cx, cost=500_000, when=NOW - timedelta(days=2), provider="openai", resolved="gpt-5"),
            _row(cx, cost=0, when=NOW - timedelta(days=2), provider="local", note="local",
                 resolved="ollama/qwen3-coder:30b"),
        ])
        await db_session.commit()
        summary = (await c.get("/v1/app/summary", headers=_auth(root))).json()
        r = await c.get("/v1/app/share/card", headers=_auth(root))
    assert r.status_code == 200, r.text
    card = r.json()
    assert card == {
        "week_saved_microcents": summary["week"]["saved_microcents"],
        "week_spend_microcents": 2_500_000,
        "rescued": 1,
        "agents": ["Claude Code", "Codex"],
        "local_requests": 1,
        "link": "https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-card",
    }


async def test_share_setup_link_names_agents_and_budget_only(desktop_app, seeded, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    (home / ".codex").mkdir()
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/share/setup", headers=_auth(root))
        assert r.json() == {"link": "orca://setup"}
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        await c.post("/v1/app/agents/codex/connect", headers=_auth(root))
        await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 500})
        r = await c.get("/v1/app/share/setup", headers=_auth(root))
    assert r.json() == {"link": "orca://setup?agents=claude-code,codex&budget=500"}
    assert "sk-" not in r.text


async def test_saving_twice_never_overwrites_the_first_file(desktop_app, seeded, desktop_dirs):
    root, _ = seeded
    home, _ = desktop_dirs
    (home / "Downloads").mkdir(exist_ok=True)
    async with _client(desktop_app) as c:
        first = (await c.post("/v1/app/report/save", headers=_auth(root), json={"format": "csv"})).json()["path"]
        second = (await c.post("/v1/app/report/save", headers=_auth(root), json={"format": "csv"})).json()["path"]
    assert first != second
    assert second.endswith("-2.csv")
