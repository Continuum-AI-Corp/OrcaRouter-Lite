"""The desktop settings added for routing (hosted models, per-agent models
and budgets, offers, local models, router knobs) round-trip through
/v1/app/settings and are validated there."""

from __future__ import annotations

import pytest

from tests.integration.test_desktop_api import (  # noqa: F401  (fixtures)
    _auth,
    _client,
    desktop_app,
    desktop_dirs,
    seeded,
)


async def test_new_fields_have_defaults(desktop_app, seeded):
    root, _ = seeded
    async with _client(desktop_app) as c:
        s = (await c.get("/v1/app/settings", headers=_auth(root))).json()
    assert s["hosted_models"] == "free"
    assert s["agent_models"] == {} and s["agent_budgets"] == {}
    assert s["kept_substitutions"] == [] and s["dismissed_offers"] == {}
    assert s["local_models"] is None
    assert s["router_num_retries"] is None and s["router_cooldown_seconds"] is None


async def test_new_fields_round_trip_and_partial_put_keeps_others(desktop_app, seeded):
    root, _ = seeded
    body = {
        "hosted_models": "all",
        "agent_models": {"claude-code": {"main": "claude-sonnet-4-6", "background": "deepseek-v4-flash",
                                         "fallback_to_auto": True}},
        "agent_budgets": {"claude-code": 500},
        "kept_substitutions": ["claude-sonnet-4-6"],
        "dismissed_offers": {"backup": "2026-11-24"},
        "local_models": ["ollama/qwen3-coder:30b"],
        "router_num_retries": 2,
        "router_cooldown_seconds": 60,
    }
    async with _client(desktop_app) as c:
        r = await c.put("/v1/app/settings", headers=_auth(root), json=body)
        assert r.status_code == 200, r.text
        r = await c.put("/v1/app/settings", headers=_auth(root), json={"daily_budget_cents": 100})
        saved = (await c.get("/v1/app/settings", headers=_auth(root))).json()
    for k, v in body.items():
        assert saved[k] == v, k


@pytest.mark.parametrize("bad", [
    {"hosted_models": "some"},
    {"router_num_retries": 6},
    {"router_num_retries": -1},
    {"router_cooldown_seconds": 3601},
    {"agent_budgets": {"codex": -5}},
    {"dismissed_offers": {"backup": "yesterday"}},
    {"agent_models": {"codex": {"main": 3}}},
])
async def test_invalid_values_are_refused(desktop_app, seeded, bad):
    root, _ = seeded
    async with _client(desktop_app) as c:
        r = await c.put("/v1/app/settings", headers=_auth(root), json=bad)
    assert r.status_code == 422, r.text
