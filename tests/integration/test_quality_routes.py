"""Integration tests for /v1/quality endpoints.

Per the no-mock-of-layer-under-test rule:
  - Real FastAPI app (not a mock router)
  - Real SQLite (not a mock DB session)
  - Real auto_routing + CATALOG (not stubbed)
  - Mock httpx for AA only (the actual network boundary)

This means a passing test proves the full stack works: AA fetcher →
score map → DB merge → resolver picks the right model → preview /
overrides reflect operator state.
"""

from __future__ import annotations

import pytest


@pytest.fixture
async def quality_client(tmp_sqlite_url, monkeypatch):
    """Booted lite app + AsyncClient with the seeded API key, AA fetcher
    mocked at the httpx boundary."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")

    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from app import router_cache
    router_cache.invalidate_router()

    # Mock the AA boundary. Returns scores that match real catalog ids
    # so resolver tests can verify routing actually changes.
    from packages.litellm_adapter import quality_index
    quality_index.reset_cache()

    aa_payload = [
        {"name": "Claude Opus 4.7 (max)",
         "evaluations": {"artificial_analysis_intelligence_index": 57}},
        {"name": "Claude Opus 4.7 (Non-reasoning, high)",
         "evaluations": {"artificial_analysis_intelligence_index": 52}},
        {"name": "GPT-4o",
         "evaluations": {"artificial_analysis_intelligence_index": 41}},
        {"name": "Claude 3.5 Haiku",
         "evaluations": {"artificial_analysis_intelligence_index": 28}},
    ]

    fetch_calls = {"n": 0}

    async def _fake_aa(url, api_key, timeout=10.0):
        fetch_calls["n"] += 1
        return aa_payload

    monkeypatch.setattr(quality_index, "_fetch_remote", _fake_aa)

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        yield c, seed.api_key, fetch_calls

    await engine.dispose()
    session_mod._session_factory = None


# ── GET /v1/quality (status + table) ──────────────────────────────────


async def test_status_reports_aa_index_configured(quality_client):
    """When AA key is set, status shows source=live + matched count > 0."""
    client, _, _ = quality_client
    r = await client.get("/v1/quality")
    assert r.status_code == 200
    body = r.json()
    assert body["aa_index"]["source"] == "live"
    assert body["aa_index"]["configured"] is True
    assert body["aa_index"]["matched_count"] >= 1, (
        "at least one of our mocked AA names should match the live catalog"
    )
    assert "models" in body and len(body["models"]) > 100, (
        "table should include the full chat-model catalog"
    )
    assert body["attribution"]["url"] == "https://artificialanalysis.ai"


async def test_status_each_row_has_score_and_cost_columns(quality_client):
    client, _, _ = quality_client
    r = await client.get("/v1/quality")
    body = r.json()
    sample = body["models"][0]
    for required in (
        "id", "provider", "blended_cost", "input_cost_per_token",
        "output_cost_per_token", "aa_score", "manual_score", "effective_score",
        "deployable", "supports_tools", "supports_vision",
    ):
        assert required in sample, f"missing column: {required}"


async def test_status_sorted_by_effective_score_desc(quality_client):
    client, _, _ = quality_client
    r = await client.get("/v1/quality")
    rows = r.json()["models"]
    # First several rows must be the scored models, descending.
    scored = [row for row in rows if row["effective_score"] is not None]
    assert len(scored) >= 2
    for i in range(len(scored) - 1):
        assert scored[i]["effective_score"] >= scored[i + 1]["effective_score"]
    # Unscored rows come after scored ones.
    if any(row["effective_score"] is None for row in rows):
        last_scored_idx = max(
            i for i, row in enumerate(rows) if row["effective_score"] is not None
        )
        first_unscored_idx = min(
            i for i, row in enumerate(rows) if row["effective_score"] is None
        )
        assert last_scored_idx < first_unscored_idx


# ── POST /v1/quality/refresh ──────────────────────────────────────────


async def test_refresh_forces_a_new_aa_fetch(quality_client):
    client, _, fetch_calls = quality_client
    # Prime the cache via a status call.
    await client.get("/v1/quality")
    n_after_status = fetch_calls["n"]
    assert n_after_status == 1

    # Status again — cached, no new fetch.
    await client.get("/v1/quality")
    assert fetch_calls["n"] == 1, "cache should serve second status"

    # Refresh — bypasses cache.
    r = await client.post("/v1/quality/refresh")
    assert r.status_code == 200
    assert r.json()["aa_index"]["source"] == "live"
    assert fetch_calls["n"] == 2, "refresh must trigger a fresh fetch"


# ── GET /v1/quality/auto-preview ──────────────────────────────────────


async def test_auto_preview_returns_primary_and_fallbacks(quality_client):
    client, _, _ = quality_client
    r = await client.get("/v1/quality/auto-preview")
    assert r.status_code == 200
    body = r.json()
    assert "strategy" in body
    assert "primary" in body
    assert "fallbacks" in body
    assert "scoring_source" in body


async def test_auto_preview_uses_aa_scores_under_quality_strategy(quality_client, monkeypatch):
    """Switch the workspace strategy to 'quality' and verify the preview
    picks a model AA scored highly, not the legacy most-expensive."""
    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.routing_config import RoutingConfig

    factory = session_mod._session_factory
    async with factory() as s:
        cfg_row = (await s.execute(select(RoutingConfig))).scalar_one()
        cfg_row.strategy = "quality"
        await s.commit()

    from app import router_cache
    router_cache.invalidate_router()

    client, _, _ = quality_client
    r = await client.get("/v1/quality/auto-preview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["strategy"] == "quality"
    assert body["scoring_source"] == "quality_scores"
    # The primary should be a model that AA scored. Concrete name depends
    # on what's in the live catalog vs what our mock AA payload covers,
    # but we can at least assert the score is non-null.
    assert body["primary"] is not None
    assert body["primary_score"] is not None
    assert body["primary_score"] >= 28, (
        "primary should match one of our mocked AA-scored models"
    )


# ── overrides CRUD ────────────────────────────────────────────────────


async def test_put_override_then_get_lists_it(quality_client):
    client, _, _ = quality_client
    r = await client.put(
        "/v1/quality/overrides/gpt-4o",
        json={"score": 88.5, "note": "our internal eval beats AA"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["model_id"] == "gpt-4o"
    assert r.json()["score"] == 88.5

    listing = await client.get("/v1/quality/overrides")
    assert listing.status_code == 200
    assert any(o["model_id"] == "gpt-4o" and o["score"] == 88.5
               for o in listing.json()["overrides"])


async def test_put_override_appears_in_status_table_as_effective(quality_client):
    client, _, _ = quality_client
    await client.put("/v1/quality/overrides/gpt-4o", json={"score": 88.5})
    r = await client.get("/v1/quality")
    rows = r.json()["models"]
    gpt4o = next(row for row in rows if row["id"] == "gpt-4o")
    assert gpt4o["manual_score"] == 88.5
    assert gpt4o["effective_score"] == 88.5, (
        "manual override must take precedence over AA score in effective"
    )


async def test_delete_override_reverts_effective_to_aa(quality_client):
    client, _, _ = quality_client
    # Set + verify
    await client.put("/v1/quality/overrides/gpt-4o", json={"score": 88.5})
    r1 = await client.get("/v1/quality")
    gpt4o_1 = next(row for row in r1.json()["models"] if row["id"] == "gpt-4o")
    assert gpt4o_1["effective_score"] == 88.5

    # Delete + verify revert
    r_del = await client.delete("/v1/quality/overrides/gpt-4o")
    assert r_del.status_code == 204

    r2 = await client.get("/v1/quality")
    gpt4o_2 = next(row for row in r2.json()["models"] if row["id"] == "gpt-4o")
    assert gpt4o_2["manual_score"] is None
    # effective_score reverts to AA's score (41 in our mock payload).
    assert gpt4o_2["effective_score"] == 41


async def test_put_override_rejects_unknown_model(quality_client):
    client, _, _ = quality_client
    r = await client.put(
        "/v1/quality/overrides/totally-fake-model-xyz",
        json={"score": 50.0},
    )
    assert r.status_code == 404


async def test_delete_unknown_override_is_noop_204(quality_client):
    """Operator's intent ('no override on this model') is satisfied
    whether the row existed or not. 204 either way."""
    client, _, _ = quality_client
    r = await client.delete("/v1/quality/overrides/never-set-this")
    assert r.status_code == 204


async def test_override_score_validation_bounds(quality_client):
    """Scores must be 0-100 (matches AA's Intelligence Index scale)."""
    client, _, _ = quality_client
    r_too_high = await client.put(
        "/v1/quality/overrides/gpt-4o", json={"score": 150.0}
    )
    assert r_too_high.status_code == 422
    r_negative = await client.put(
        "/v1/quality/overrides/gpt-4o", json={"score": -5.0}
    )
    assert r_negative.status_code == 422


# ── full integration: override changes routing ────────────────────────


async def test_override_actually_changes_auto_preview(quality_client):
    """The whole point of overrides: setting one must change which model
    auto would pick under quality strategy. End-to-end round trip."""
    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.routing_config import RoutingConfig

    factory = session_mod._session_factory
    async with factory() as s:
        cfg_row = (await s.execute(select(RoutingConfig))).scalar_one()
        cfg_row.strategy = "quality"
        await s.commit()

    from app import router_cache
    router_cache.invalidate_router()

    client, _, _ = quality_client
    r1 = await client.get("/v1/quality/auto-preview")
    primary_before = r1.json()["primary"]

    # Find a deployable model that's NOT currently the primary, override
    # its score to 99 (above AA's max), and re-preview.
    status = (await client.get("/v1/quality")).json()
    deployable_ids = [row["id"] for row in status["models"] if row["deployable"]]
    other_choice = next(mid for mid in deployable_ids if mid != primary_before)

    await client.put(
        f"/v1/quality/overrides/{other_choice}",
        json={"score": 99.0, "note": "force this for integration test"},
    )

    r2 = await client.get("/v1/quality/auto-preview")
    assert r2.json()["primary"] == other_choice, (
        f"override should have flipped primary from {primary_before} to {other_choice}, "
        f"got {r2.json()['primary']}"
    )
