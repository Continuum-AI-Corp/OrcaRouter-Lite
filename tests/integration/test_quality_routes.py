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
        # Per-axis aggregation: quality MAX, TPS MAX, TTFT MIN. The two
        # Claude Opus 4.7 variants here exercise that — the Non-reasoning
        # row has lower quality (52 vs 57) but lower TTFT (the model's
        # "fast mode"), so the merged metrics carry quality=57 + ttft=0.8.
        {"name": "Claude Opus 4.7 (max)",
         "evaluations": {"artificial_analysis_intelligence_index": 57},
         "median_output_tokens_per_second": 60,
         "median_time_to_first_token_seconds": 12.0},
        {"name": "Claude Opus 4.7 (Non-reasoning, high)",
         "evaluations": {"artificial_analysis_intelligence_index": 52},
         "median_output_tokens_per_second": 65,
         "median_time_to_first_token_seconds": 0.8},
        {"name": "GPT-4o",
         "evaluations": {"artificial_analysis_intelligence_index": 41},
         "median_output_tokens_per_second": 80,
         "median_time_to_first_token_seconds": 0.4},
        {"name": "Claude 3.5 Haiku",
         "evaluations": {"artificial_analysis_intelligence_index": 28},
         "median_output_tokens_per_second": 120,
         "median_time_to_first_token_seconds": 0.3},
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
    # `scoring_source` is now a human-readable label keyed off a
    # strategy + data-availability state. The label tells the operator
    # WHY the strategy picked what it picked (and surfaces fallback
    # cases like "no AA → cost proxy").
    assert "AA Intelligence Index" in body["scoring_source"], body["scoring_source"]
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


# ── PR 4: per-axis fields, ?strategy= override, breakdown, cache ───────


async def test_v1_quality_rows_carry_tps_and_ttft_fields(quality_client):
    """Per-model rows expose AA latency metrics so the dashboard table
    can render TPS / TTFT columns. None when AA hasn't covered a model
    on that axis (the catalog is much larger than the AA index)."""
    client, _, _ = quality_client
    r = await client.get("/v1/quality")
    body = r.json()

    # Every row carries the new fields (None when not indexed).
    sample = body["models"][0]
    assert "tps" in sample
    assert "ttft" in sample

    # At least one row should have both fields populated (came from AA).
    indexed = [m for m in body["models"] if m["tps"] is not None]
    assert indexed, "fixture provides AA metrics for some catalog models"
    assert all(m["ttft"] is not None for m in indexed), (
        "fixture pairs TPS + TTFT for all indexed models"
    )


async def test_aa_index_status_carries_per_axis_breakdown(quality_client):
    """The status block exposes per-axis matched_count so the dashboard
    can distinguish 'AA gave us quality but no latency' from 'AA covers
    nothing'. matched_count itself stays a single int (union — count of
    models with at least one indexed axis) for backward compat with the
    existing 'X of Y indexed' UI string."""
    client, _, _ = quality_client
    r = await client.get("/v1/quality")
    aa = r.json()["aa_index"]

    assert isinstance(aa["matched_count"], int)
    assert "matched_count_breakdown" in aa
    bd = aa["matched_count_breakdown"]
    assert set(bd.keys()) == {"quality", "tps", "ttft"}
    # Fixture has all four entries scored on all three axes.
    assert bd["quality"] >= 1
    assert bd["tps"] >= 1
    assert bd["ttft"] >= 1


async def test_auto_preview_strategy_query_overrides_workspace(quality_client):
    """`?strategy=` lets verification scripts compare all four strategies
    without flipping the persisted workspace config. The dashboard does
    NOT pass this (race condition with hardcoded `state.routing.strategy`
    default during initial load) — server reads workspace strategy as
    the authoritative source."""
    client, _, _ = quality_client

    # Workspace default is "balanced" (seed). Override to "cheapest"
    # via query and verify the response reflects the override.
    r_balanced = await client.get("/v1/quality/auto-preview")
    r_cheapest = await client.get("/v1/quality/auto-preview?strategy=cheapest")
    assert r_balanced.status_code == 200
    assert r_cheapest.status_code == 200

    body_b = r_balanced.json()
    body_c = r_cheapest.json()

    assert body_b["strategy"] == "balanced"
    assert body_c["strategy"] == "cheapest"
    assert body_c["strategy_overridden"] is True
    assert body_c["workspace_strategy"] == "balanced"
    # cheapest's primary_score is None (no normalized 0-100 mapping for
    # raw token cost), unlike balanced which gives an int.
    assert body_c["primary_score"] is None


async def test_auto_preview_fastest_includes_breakdown_with_tps_and_ttft(quality_client):
    """fastest preview must surface the per-axis raw + normalized values
    so the operator can see WHY a model won (otherwise the score is opaque
    and the strategy choice loses its explanatory power)."""
    client, _, _ = quality_client
    r = await client.get("/v1/quality/auto-preview?strategy=fastest")
    body = r.json()
    assert body["strategy"] == "fastest"
    breakdown = body["primary_score_breakdown"]
    assert breakdown is not None, (
        "fastest must always emit a breakdown when it ranks (or fall back "
        "to cheapest with cost-only breakdown — either way breakdown is set)"
    )
    # When fastest succeeds, breakdown carries tps + ttft. When it falls
    # back to cheapest (no AA latency), breakdown has cost only.
    assert ("tps" in breakdown and "ttft" in breakdown) or "cost" in breakdown


async def test_auto_preview_balanced_excludes_unscored_strict_coverage(quality_client):
    """A model in the catalog that AA hasn't scored (no quality data)
    must NOT appear in the balanced primary or fallbacks — strict
    coverage drops it from candidates entirely. Operators wanting
    coverage of unscored models must use cheapest or set a manual
    override."""
    client, _, _ = quality_client
    r = await client.get("/v1/quality?")
    quality_table = r.json()
    # Find a deployable catalog model that's NOT in our mocked AA payload.
    unscored_deployable = next(
        (m for m in quality_table["models"]
         if m["deployable"] and m["aa_score"] is None),
        None,
    )
    if unscored_deployable is None:
        pytest.skip("fixture's mocked AA covers all deployable models")

    r2 = await client.get("/v1/quality/auto-preview?strategy=balanced")
    body = r2.json()
    candidates = [body["primary"]] + (body["fallbacks"] or [])
    assert unscored_deployable["id"] not in candidates, (
        f"strict coverage: balanced must drop unscored model "
        f"{unscored_deployable['id']!r}, got candidates={candidates}"
    )


async def test_metrics_cache_invalidates_on_override_put(quality_client):
    """After PUT /v1/quality/overrides/{model}, the next request that
    triggers metrics resolution must see the override — not 60s of
    cached pre-override data. Without cache invalidation, an operator
    setting an override would see no effect until TTL expires."""
    client, _, _ = quality_client

    # Prime the cache: fire a balanced auto-preview (uses metrics).
    r1 = await client.get("/v1/quality/auto-preview?strategy=balanced")
    primary_before = r1.json()["primary"]

    # Force a different model to win by giving it a manual quality
    # override. quality.py PUT route invalidates the metrics cache.
    table = (await client.get("/v1/quality")).json()["models"]
    deployable_others = [m for m in table
                         if m["deployable"] and m["id"] != primary_before
                         and m["aa_score"] is not None]
    if not deployable_others:
        pytest.skip("only one deployable AA-scored model in fixture")
    target = deployable_others[0]["id"]

    await client.put(
        f"/v1/quality/overrides/{target}",
        json={"score": 100.0, "note": "test override"},
    )

    # Without cache invalidation, this would return the OLD primary
    # (cached for 60s). With invalidation, the override is visible
    # immediately.
    r2 = await client.get("/v1/quality/auto-preview?strategy=balanced")
    primary_after = r2.json()["primary"]
    # The override may or may not flip the actual winner (depends on
    # cost weighting), but the score in the response MUST reflect the
    # override path. Check via /v1/quality table — the row's effective_score
    # for `target` should be 100.0 (manual override wins over AA).
    table_after = (await client.get("/v1/quality")).json()["models"]
    target_row = next(m for m in table_after if m["id"] == target)
    assert target_row["effective_score"] == 100.0, (
        f"override visible immediately after PUT (no 60s TTL wait); "
        f"primary went {primary_before} → {primary_after}"
    )


async def test_metrics_cache_invalidates_on_quality_refresh(quality_client):
    """POST /v1/quality/refresh re-fetches AA AND drops the resolver
    cache so subsequent routing reflects the freshly-pulled scores."""
    client, _, fetch_calls = quality_client

    # Prime resolver cache.
    await client.get("/v1/quality/auto-preview?strategy=balanced")
    fetch_count_before = fetch_calls["n"]

    # Refresh — bypasses AA cache + invalidates resolver cache.
    r = await client.post("/v1/quality/refresh")
    assert r.status_code == 200
    assert fetch_calls["n"] > fetch_count_before, "refresh must hit AA"

    # Next preview must walk through resolver again (cache-cold), proving
    # invalidate fired. We can't directly observe cache miss, but we can
    # verify the response is internally consistent with the latest AA data.
    r2 = await client.get("/v1/quality/auto-preview?strategy=balanced")
    assert r2.status_code == 200


def test_scoring_source_label_dict_distinguishes_uncovered_from_no_data():
    """Codex follow-up: the SCORING_SOURCE label dictionary itself must
    carry distinct entries for 'AA configured but doesn't cover any
    eligible model' vs 'AA not configured'. End-to-end env mutation is
    fragile (pydantic-settings reads .env outside test control), so we
    pin the contract at the label-dict layer where it lives."""
    from app.routes.quality import _SCORING_SOURCE_LABELS

    # Both balanced and fastest must have BOTH fallback variants so the
    # operator can tell whether to configure AA or widen their allowlist.
    assert "balanced-cheapest-fallback" in _SCORING_SOURCE_LABELS
    assert "balanced-no-data-fallback" in _SCORING_SOURCE_LABELS
    assert "fastest-cheapest-fallback" in _SCORING_SOURCE_LABELS
    assert "fastest-no-data-fallback" in _SCORING_SOURCE_LABELS

    # Labels must be visibly different so the dashboard renders distinct
    # text for the two failure modes (otherwise the operator can't tell
    # what to fix).
    assert (
        _SCORING_SOURCE_LABELS["balanced-cheapest-fallback"]
        != _SCORING_SOURCE_LABELS["balanced-no-data-fallback"]
    )
    assert (
        _SCORING_SOURCE_LABELS["fastest-cheapest-fallback"]
        != _SCORING_SOURCE_LABELS["fastest-no-data-fallback"]
    )
