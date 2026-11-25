"""GET /v1/app/models (H5), GET /v1/app/local + POST /v1/app/local/refresh (P2),
GET /v1/app/agents/{id}/requests (D3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.test_desktop_api import _auth, _client, _key_id, desktop_app, desktop_dirs, seeded  # noqa: F401
from tests.integration.test_desktop_summary_more import _row

M_KEYS = {"id", "name", "provider", "input_per_m", "output_per_m", "free", "available", "tools", "vision"}


@pytest.fixture
def only_openai(monkeypatch):
    from app import config

    for var in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "ORCAROUTER_API_KEY", "DEEPSEEK_API_KEY", "XAI_API_KEY",
                "MISTRAL_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY", "FIREWORKS_API_KEY", "COHERE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-0123456789")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _local_runtimes():
    from packages.desktop.local_models import LocalModel, Runtime

    coder = LocalModel(id="ollama/qwen3-coder:30b", runtime="ollama", name="qwen3-coder:30b",
                       api_base="http://127.0.0.1:11434", context=262144, tools=True, vision=False)
    chat = LocalModel(id="ollama/llama3.3:70b", runtime="ollama", name="llama3.3:70b",
                      api_base="http://127.0.0.1:11434", context=131072, tools=False, vision=False)
    return [Runtime("ollama", "Ollama", "127.0.0.1:11434", True, (coder, chat)),
            Runtime("lmstudio", "LM Studio", "127.0.0.1:1234", False),
            Runtime("llamacpp", "llama.cpp", "127.0.0.1:8080", False)]


async def _models(c, root, **params):
    r = await c.get("/v1/app/models", headers=_auth(root), params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    return body, {g["id"]: g for g in body["groups"]}


# ── models ──────────────────────────────────────────────────────────────


async def test_model_groups_in_order_with_prices_per_million(desktop_app, seeded, only_openai):
    from packages.desktop import local_models
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    root, _ = seeded
    local_models.remember(_local_runtimes())
    async with _client(desktop_app) as c:
        body, groups = await _models(c, root)
    assert [g["id"] for g in body["groups"]] == ["yours", "local", "free", "paid"]
    assert [g["label"] for g in body["groups"]] == ["Your keys", "On this computer", "Free on OrcaRouter",
                                                   "Paid on OrcaRouter"]
    assert body["hosted_configured"] is False
    for g in body["groups"]:
        for m in g["models"]:
            assert set(m) == M_KEYS
    yours = {m["id"]: m for m in groups["yours"]["models"]}
    assert {m["provider"] for m in yours.values()} == {"openai"}
    gpt = yours["gpt-4o"]
    assert gpt["input_per_m"] == pytest.approx(CATALOG_BY_ID["gpt-4o"].input_cost_per_token * 1e6)
    assert gpt["output_per_m"] == pytest.approx(CATALOG_BY_ID["gpt-4o"].output_cost_per_token * 1e6)
    assert gpt["available"] is True and gpt["free"] is False and gpt["tools"] is True
    # Free models, and paid ones, need an OrcaRouter key.
    free = {m["id"]: m for m in groups["free"]["models"]}
    assert "z-ai/glm-5.3-flash-free" in free
    assert all(m["free"] and m["input_per_m"] == 0 and not m["available"] for m in free.values())
    assert groups["paid"]["models"] and not any(m["available"] for m in groups["paid"]["models"])
    assert all(m["provider"] == "orcarouter" for m in groups["paid"]["models"])
    # Models on this computer: free, available when their runtime runs and auto may use them.
    local = {m["id"]: m for m in groups["local"]["models"]}
    assert local["ollama/qwen3-coder:30b"]["available"] is True
    assert local["ollama/qwen3-coder:30b"]["free"] is True
    assert local["ollama/llama3.3:70b"]["available"] is False  # no tools: not enabled by default


async def test_yours_is_capped_and_sorted_by_provider_then_price(desktop_app, seeded, only_openai):
    root, _ = seeded
    async with _client(desktop_app) as c:
        _, groups = await _models(c, root, limit=5)
    yours = groups["yours"]["models"]
    assert len(yours) == 5
    assert groups["yours"]["total"] > 5
    prices = [(m["input_per_m"] or 0) + (m["output_per_m"] or 0) for m in yours]
    assert prices == sorted(prices)


async def test_search_reaches_every_group(desktop_app, seeded, only_openai):
    root, _ = seeded
    async with _client(desktop_app) as c:
        _, groups = await _models(c, root, q="SONNET")
    assert groups["yours"]["models"] == []  # no Anthropic key
    assert groups["paid"]["models"]
    assert all("sonnet" in m["id"] for m in groups["paid"]["models"])
    assert groups["free"]["models"] == []


async def test_with_an_orcarouter_key_free_models_are_available_and_paid_ones_need_all(
        desktop_app, seeded, only_openai, monkeypatch):
    from app import config

    root, _ = seeded
    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-test-key-1234567890")
    config.get_settings.cache_clear()
    async with _client(desktop_app) as c:
        body, groups = await _models(c, root)
        assert body["hosted_configured"] is True
        assert all(m["available"] for m in groups["free"]["models"])
        assert not any(m["available"] for m in groups["paid"]["models"])
        await c.put("/v1/app/settings", headers=_auth(root), json={"hosted_models": "all"})
        _, groups = await _models(c, root)
        assert all(m["available"] for m in groups["paid"]["models"])
        # The paid list is longer than one page of the picker: find it by name.
        _, groups = await _models(c, root, q="claude-sonnet-4.6")
    sonnet = next(m for m in groups["paid"]["models"] if m["id"] == "claude-sonnet-4.6")
    assert sonnet["input_per_m"] and sonnet["output_per_m"]


# ── local ───────────────────────────────────────────────────────────────


async def test_local_lists_runtimes_and_models_with_enabled(desktop_app, seeded):
    from packages.desktop import local_models

    root, _ = seeded
    local_models.remember(_local_runtimes())
    async with _client(desktop_app) as c:
        r = await c.get("/v1/app/local", headers=_auth(root))
        assert r.status_code == 200, r.text
        ollama = r.json()["runtimes"][0]
        assert {k: ollama[k] for k in ("id", "name", "url", "running")} == {
            "id": "ollama", "name": "Ollama", "url": "127.0.0.1:11434", "running": True}
        assert ollama["models"] == [
            {"id": "ollama/qwen3-coder:30b", "name": "qwen3-coder:30b", "tools": True, "vision": False,
             "context": 262144, "enabled": True},
            {"id": "ollama/llama3.3:70b", "name": "llama3.3:70b", "tools": False, "vision": False,
             "context": 131072, "enabled": False},
        ]
        await c.put("/v1/app/settings", headers=_auth(root), json={"local_models": ["ollama/llama3.3:70b"]})
        models = (await c.get("/v1/app/local", headers=_auth(root))).json()["runtimes"][0]["models"]
    assert [m["enabled"] for m in models] == [False, True]


async def test_refresh_rediscovers_and_rebuilds_the_router(desktop_app, seeded, monkeypatch):
    from app import router_cache
    from packages.desktop import local_models

    root, _ = seeded
    calls = []

    async def fake_discover(*, force=False, **_kw):
        calls.append(force)
        local_models.remember(_local_runtimes())
        return local_models.last()

    invalidated = []
    monkeypatch.setattr(local_models, "discover", fake_discover)
    monkeypatch.setattr(router_cache, "invalidate_router", lambda: invalidated.append(True))
    async with _client(desktop_app) as c:
        r = await c.post("/v1/app/local/refresh", headers=_auth(root))
    assert r.status_code == 200, r.text
    assert calls == [True] and invalidated == [True]
    assert [rt["id"] for rt in r.json()["runtimes"]] == ["ollama", "lmstudio", "llamacpp"]


# ── per-agent request log ───────────────────────────────────────────────


async def test_agent_requests_newest_first_only_that_agents_keys(desktop_app, seeded, db_session):
    root, _ = seeded
    now = datetime.now(timezone.utc)
    async with _client(desktop_app) as c:
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))
        first_key = await _key_id(db_session, "agent:claude-code")
        db_session.add(_row(first_key, cost=100, when=now - timedelta(minutes=30), requested="claude-sonnet-4-6",
                            resolved="claude-sonnet-4-6"))
        await db_session.commit()
        await c.post("/v1/app/agents/claude-code/connect", headers=_auth(root))  # a new key; the old one's rows stay
        cc = await _key_id(db_session, "agent:claude-code")
        rid = await _key_id(db_session, "default")
        db_session.add_all([
            _row(cc, cost=71_000, when=now - timedelta(minutes=2), requested="claude-sonnet-4-6",
                 resolved="gpt-4.1", provider="openai", note="substituted", tokens=(18200, 1100)),
            _row(cc, cost=89_000, when=now - timedelta(minutes=10), requested="claude-sonnet-4-6",
                 resolved="gpt-4.1", provider="openai", fallback=1),
            _row(cc, when=now - timedelta(minutes=5), status=503, note="no_fallback"),
            _row(rid, cost=5, when=now - timedelta(minutes=1)),  # another app's request
        ])
        await db_session.commit()
        r = await c.get("/v1/app/agents/claude-code/requests", headers=_auth(root))
        limited = await c.get("/v1/app/agents/claude-code/requests", headers=_auth(root), params={"limit": 2})
        unknown = await c.get("/v1/app/agents/notepad/requests", headers=_auth(root))
    assert r.status_code == 200, r.text
    reqs = r.json()["requests"]
    assert [q["cost_microcents"] for q in reqs] == [71_000, 0, 89_000, 100]
    top = reqs[0]
    assert set(top) == {"at", "model_requested", "model", "provider", "input_tokens", "output_tokens",
                        "cost_microcents", "latency_ms", "status", "rescued", "note"}
    assert (top["model_requested"], top["model"], top["provider"]) == ("claude-sonnet-4-6", "gpt-4.1", "openai")
    assert (top["input_tokens"], top["output_tokens"], top["status"], top["note"]) == (18200, 1100, 200, "substituted")
    assert top["rescued"] is False and reqs[2]["rescued"] is True
    assert reqs[1]["status"] == 503 and reqs[1]["note"] == "no_fallback" and reqs[1]["rescued"] is False
    assert datetime.fromisoformat(top["at"]).tzinfo is not None
    assert len(limited.json()["requests"]) == 2
    assert unknown.status_code == 404
