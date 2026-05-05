"""Unit tests for the AA quality-index fetcher + name normalization.

Per the no-mock-of-layer-under-test rule: we mock at the httpx transport
boundary (the network layer), not at `_fetch_remote` (the module's own
internal helper). That way the real JSON-parse + schema-validation +
score-aggregation code runs end-to-end. A test that monkeypatches
`_fetch_remote` directly would hide the very logic the AA fetcher exists
to do — and exactly that kind of skip caused the empty-response-poisoning
regression we now guard against.
"""

from __future__ import annotations

from typing import Any, Callable

import httpx
import pytest


def _patch_aa_transport(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    """Swap `httpx.AsyncClient` (as used by `quality_index`) with a wrapper
    that injects an `httpx.MockTransport`. Lets us drive AA responses
    without touching the network OR the module's own `_fetch_remote` helper."""
    from packages.litellm_adapter import quality_index

    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(quality_index.httpx, "AsyncClient", _factory)


def _aa_response(payload: list[dict] | dict | None, *, status: int = 200) -> httpx.Response:
    """Build an AA-shaped HTTP response. AA wraps the model list under
    `data`; pass a list to use the standard envelope, a dict for raw
    bodies (testing schema-mismatch paths), or None for an empty body."""
    if payload is None:
        return httpx.Response(status, json={"data": []})
    if isinstance(payload, list):
        return httpx.Response(status, json={"data": payload})
    return httpx.Response(status, json=payload)

# ── name normalization ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "aa_name,expected",
    [
        ("Claude Opus 4.7 (max)", "claude-opus-4-7"),
        ("Claude Opus 4.7", "claude-opus-4-7"),
        ("GPT-5.5 (xhigh)", "gpt-5-5"),
        ("Claude Sonnet 4.6 (max)", "claude-sonnet-4-6"),
        ("Gemini 3.1 Pro Preview", "gemini-3-1-pro-preview"),
        ("DeepSeek V4 Pro (Max)", "deepseek-v4-pro"),
        ("Claude Opus 4.7 (Non-reasoning, high)", "claude-opus-4-7"),
        # Trailing whitespace / multiple spaces
        ("  GPT-4o  ", "gpt-4o"),
    ],
)
def test_normalize_aa_id(aa_name, expected):
    from packages.litellm_adapter.quality_index import _normalize_aa_id
    assert _normalize_aa_id(aa_name) == expected


# ── catalog matching ──────────────────────────────────────────────────


def test_match_catalog_id_exact():
    from packages.litellm_adapter.quality_index import _match_catalog_id
    assert _match_catalog_id("gpt-4o", {"gpt-4o", "claude-opus-4-7"}) == "gpt-4o"


def test_match_catalog_id_strips_prefix():
    """Defensive: catalog ids are already stripped at load time, but the
    helper accepts prefixed forms in case AA ever returns one."""
    from packages.litellm_adapter.quality_index import _match_catalog_id
    assert _match_catalog_id("openai/gpt-4o", {"gpt-4o"}) == "gpt-4o"


def test_match_catalog_id_family_fallback():
    """`claude-opus-4-7` (AA's bare name) maps to `claude-opus-4-7-20260416`
    when only the dated form is in the catalog."""
    from packages.litellm_adapter.quality_index import _match_catalog_id
    catalog = {"claude-opus-4-7-20260416"}
    assert _match_catalog_id("claude-opus-4-7", catalog) == "claude-opus-4-7-20260416"


def test_match_catalog_id_no_match():
    from packages.litellm_adapter.quality_index import _match_catalog_id
    assert _match_catalog_id("totally-fake", {"gpt-4o"}) is None


# ── score aggregation: max across reasoning-effort variants ───────────


def test_build_score_map_takes_max_across_variants():
    """AA splits the same model into separate rows by reasoning effort
    (e.g. 'GPT-5.5 (xhigh)' = 60 vs 'GPT-5.5 (low)' = 51). Our routing
    picks a model_name not an effort, so we keep the highest score per
    base model — the operator can always set effort separately."""
    from packages.litellm_adapter.quality_index import _build_score_map

    aa = [
        {"name": "GPT-5.5 (xhigh)",
         "evaluations": {"artificial_analysis_intelligence_index": 60}},
        {"name": "GPT-5.5 (high)",
         "evaluations": {"artificial_analysis_intelligence_index": 59}},
        {"name": "GPT-5.5 (low)",
         "evaluations": {"artificial_analysis_intelligence_index": 51}},
    ]
    catalog = {"gpt-5-5"}
    scores, raw, matched = _build_score_map(aa, catalog)
    assert scores == {"gpt-5-5": 60.0}, "must keep the max across variants"
    assert raw == 3
    assert matched == 1


def test_build_score_map_skips_unmatched():
    """Models that don't map to any catalog id are dropped — no point
    surfacing scores we can't act on."""
    from packages.litellm_adapter.quality_index import _build_score_map

    aa = [
        {"name": "Some Future Model X",
         "evaluations": {"artificial_analysis_intelligence_index": 70}},
        {"name": "Claude Opus 4.7 (max)",
         "evaluations": {"artificial_analysis_intelligence_index": 57}},
    ]
    catalog = {"claude-opus-4-7"}
    scores, raw, matched = _build_score_map(aa, catalog)
    assert scores == {"claude-opus-4-7": 57.0}
    assert raw == 2
    assert matched == 1


def test_build_score_map_skips_missing_score():
    """AA entries without an intelligence_index field (e.g. brand-new
    additions, deprecated rows) are skipped — better to omit than to
    invent a fake score."""
    from packages.litellm_adapter.quality_index import _build_score_map

    aa = [
        {"name": "Claude Opus 4.7 (max)", "evaluations": {}},
        {"name": "GPT-5"},  # no evaluations at all
    ]
    catalog = {"claude-opus-4-7", "gpt-5"}
    scores, _raw, matched = _build_score_map(aa, catalog)
    assert scores == {}
    assert matched == 0


# ── end-to-end fetch with httpx mocked at the boundary ────────────────


async def test_fetch_remote_accepts_bare_list_envelope(monkeypatch):
    """AA's docs imply `{data: [...]}` but some endpoints return a bare
    `[...]`. Real `_fetch_remote` must accept both — running the real
    parser through the boundary mock catches a regression here that a
    `_fetch_remote` monkeypatch would silently miss."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        # Bare top-level array (no `data` wrapper).
        return httpx.Response(200, json=[
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)
    idx = await quality_index.get_quality_index(catalog_ids={"claude-opus-4-7"})
    assert idx.source == "live"
    assert idx.scores == {"claude-opus-4-7": 57.0}


async def test_fetch_remote_unknown_schema_falls_through_to_stale(monkeypatch, db_session):
    """If AA changes the response shape entirely (e.g., wraps under
    `result.models` instead of `data`), our parser must treat it as a
    fetch failure rather than persist `{}`. Verifies the real
    `_AAFetchUnusable` raise path through the transport boundary."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    state = {"mode": "live"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["mode"] == "schema-changed":
            # Neither bare list nor `{data: list}` — totally unknown shape.
            return httpx.Response(200, json={"result": {"models": []}})
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # Prime DB with a real snapshot.
    await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )

    # AA changes shape after a deploy on their side.
    quality_index.reset_cache()
    state["mode"] = "schema-changed"

    idx = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"},
        db=db_session, workspace_id="default", force_refresh=True,
    )
    assert idx.source == "stale-db", "schema mismatch must fall through to stale, not poison snapshot"
    assert idx.scores == {"claude-opus-4-7": 57.0}


async def test_get_quality_index_returns_missing_key_when_unconfigured(monkeypatch):
    """No API key → no fetch attempt. Source flag tells the dashboard
    to render the 'configure AA' setup card."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "")
    cfg.get_settings.cache_clear()

    idx = await quality_index.get_quality_index(catalog_ids={"gpt-4o"})
    assert idx.source == "missing-key"
    assert idx.scores == {}


async def test_get_quality_index_fetches_and_caches(monkeypatch):
    """Real fetch + cache flow: first call drives the AA-shaped HTTP mock
    through the real `_fetch_remote` parser; second call within TTL
    returns cached value without re-issuing the request."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    fetch_calls = {"n": 0, "last_key": None}

    def handler(request: httpx.Request) -> httpx.Response:
        fetch_calls["n"] += 1
        fetch_calls["last_key"] = request.headers.get("x-api-key")
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
            {"name": "GPT-4o",
             "evaluations": {"artificial_analysis_intelligence_index": 50}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    idx1 = await quality_index.get_quality_index(catalog_ids={"claude-opus-4-7", "gpt-4o"})
    assert idx1.source == "live"
    assert idx1.scores == {"claude-opus-4-7": 57.0, "gpt-4o": 50.0}
    assert fetch_calls["n"] == 1
    # Confirms the real _fetch_remote ran and forwarded our key header —
    # if we'd monkeypatched _fetch_remote we'd never know.
    assert fetch_calls["last_key"] == "sk-aa-test"

    # Second call within TTL → cached, no fetch.
    idx2 = await quality_index.get_quality_index(catalog_ids={"claude-opus-4-7", "gpt-4o"})
    assert idx2.scores == idx1.scores
    assert fetch_calls["n"] == 1, "cache hit should not refetch"

    # force_refresh bypasses cache.
    idx3 = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7", "gpt-4o"}, force_refresh=True
    )
    assert idx3.scores == idx1.scores
    assert fetch_calls["n"] == 2


async def test_db_snapshot_persists_across_in_process_cache_reset(monkeypatch, db_session):
    """The point of the DB layer: docker compose down/up shouldn't burn an
    AA fetch if we already have fresh data. Simulate process restart by
    clearing the in-process cache and verify the next call is served from
    DB without hitting AA again."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    fetch_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        fetch_calls["n"] += 1
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # First call: fetch + persist to DB.
    idx1 = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"},
        db=db_session, workspace_id="default",
    )
    assert idx1.source == "live"
    assert fetch_calls["n"] == 1

    # Simulate process restart: nuke the in-process cache. DB row remains.
    quality_index.reset_cache()

    # Next call must serve from DB without re-fetching.
    idx2 = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"},
        db=db_session, workspace_id="default",
    )
    assert fetch_calls["n"] == 1, "DB snapshot should serve cold-start, not refetch"
    assert idx2.scores == {"claude-opus-4-7": 57.0}


async def test_db_snapshot_invalidated_on_key_rotation(monkeypatch, db_session):
    """A snapshot fetched under AA key A must NOT be served when the
    operator rotates to AA key B. Different account = potentially
    different model coverage / scores."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-key-A")
    cfg.get_settings.cache_clear()

    fetch_calls = {"n": 0, "last_key": None}

    def handler(request: httpx.Request) -> httpx.Response:
        fetch_calls["n"] += 1
        fetch_calls["last_key"] = request.headers.get("x-api-key")
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # Prime under key A.
    await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )
    assert fetch_calls["n"] == 1
    assert fetch_calls["last_key"] == "sk-aa-key-A"

    # Rotate the key, clear in-process cache (simulating a config reload).
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-key-B")
    cfg.get_settings.cache_clear()
    quality_index.reset_cache()

    # New key → DB row from key A must be ignored, must refetch.
    await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )
    assert fetch_calls["n"] == 2
    assert fetch_calls["last_key"] == "sk-aa-key-B"


async def test_db_snapshot_freshness_uses_wall_clock_not_monotonic(monkeypatch, db_session):
    """Cross-process correctness regression test.

    `time.monotonic()` is per-process (zero point varies). If the freshness
    check used the saved monotonic value vs the current process's monotonic
    clock, a snapshot from a long-running process would always look "fresh"
    after restart (smaller new-process monotonic minus larger saved
    monotonic = negative, < TTL, looks fresh) — defeating the TTL entirely.

    This test pre-ages the DB row's `updated_at` to 2h in the past
    (beyond the 1h TTL) and verifies the resolver REFETCHES rather than
    serving the stale row as fresh.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app import config as cfg
    from packages.db.models.quality_score_snapshot import QualityScoreSnapshot
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    fetch_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        fetch_calls["n"] += 1
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # 1. Prime the DB with a snapshot.
    await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )
    assert fetch_calls["n"] == 1

    # 2. Simulate the row being old: rewrite updated_at to 2h ago.
    row = (await db_session.execute(select(QualityScoreSnapshot))).scalar_one()
    row.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db_session.commit()

    # 3. Simulate process restart by clearing in-process cache.
    quality_index.reset_cache()

    # 4. Next call must REFETCH because the DB row is older than TTL by
    # wall-clock. If freshness used monotonic, the test would fail here:
    # the saved monotonic value would be tiny vs current monotonic, the
    # subtraction would underflow / be ignored, and the stale row would
    # be served as fresh.
    await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )
    assert fetch_calls["n"] == 2, (
        "DB row older than TTL must trigger AA refetch; freshness check must "
        "use wall-clock (updated_at) not per-process monotonic time"
    )


async def test_aa_failure_falls_back_to_db_snapshot(monkeypatch, db_session):
    """When AA is unreachable AND the in-process cache is cold, the DB
    snapshot is the last line of defense before degrading to cost-based.
    Source flag tells the dashboard the data is stale."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    state = {"mode": "live"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["mode"] == "fail":
            # Simulate AA outage at the network layer (5xx is what the
            # SDK actually gets, not a Python exception).
            return httpx.Response(503, json={"error": "service unavailable"})
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # Prime DB with a successful fetch.
    await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )

    # Simulate process restart + AA outage.
    quality_index.reset_cache()
    state["mode"] = "fail"

    idx = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"},
        db=db_session, workspace_id="default", force_refresh=True,
    )
    assert idx.source == "stale-db", (
        "must flag the source as DB-stale so the dashboard can show 'AA outage'"
    )
    assert idx.scores == {"claude-opus-4-7": 57.0}


async def test_empty_aa_response_does_not_poison_db_snapshot(monkeypatch, db_session):
    """Regression: AA returning an empty list (transient outage, quota
    exceeded with 200, schema regression) used to be treated as a healthy
    fetch and persisted as `{}` over the existing good snapshot. Next
    restart would then serve `{}` from DB and quality routing would
    silently degrade to cost-based.

    The fix: empty raw / zero-matched results raise `_AAFetchUnusable`,
    which routes through the stale-fallback path. The good DB snapshot
    is preserved, and the operator sees source='stale-db' in the
    dashboard so they know AA is unreachable.
    """
    from sqlalchemy import select

    from app import config as cfg
    from packages.db.models.quality_score_snapshot import QualityScoreSnapshot
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    state = {"mode": "live"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["mode"] == "empty":
            return _aa_response([])  # AA returns 200 with `{"data": []}`
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # 1. Prime the DB with a real snapshot.
    idx_live = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )
    assert idx_live.source == "live"
    assert idx_live.scores == {"claude-opus-4-7": 57.0}

    # 2. Simulate process restart + AA glitch returning empty data.
    quality_index.reset_cache()
    state["mode"] = "empty"

    idx_after = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"},
        db=db_session, workspace_id="default", force_refresh=True,
    )

    # Must serve the stale snapshot, not poison-overwrite with `{}`.
    assert idx_after.source == "stale-db"
    assert idx_after.scores == {"claude-opus-4-7": 57.0}, (
        "empty AA fetch must not overwrite existing DB snapshot"
    )

    # And the DB row must still hold the good data, not `{}`.
    row = (await db_session.execute(select(QualityScoreSnapshot))).scalar_one()
    import json as _json
    assert _json.loads(row.scores_json) == {"claude-opus-4-7": 57.0}, (
        "DB snapshot must not have been overwritten with empty score map"
    )


async def test_aa_response_with_no_catalog_matches_does_not_poison_snapshot(monkeypatch, db_session):
    """Regression: AA returning entries that all fail to map to our
    catalog (normalization regression after AA renames) used to persist
    `{}` and silently disable quality routing. Now treated as a fetch
    failure → stale fallback runs.
    """
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    state = {"mode": "live"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["mode"] == "renamed":
            # AA renamed everything; nothing maps to our catalog.
            return _aa_response([
                {"name": "Brand-New Provider Model X",
                 "evaluations": {"artificial_analysis_intelligence_index": 70}},
            ])
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # Prime DB with a good snapshot.
    await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, db=db_session, workspace_id="default",
    )

    # Process restart + AA "renamed everything" regression.
    quality_index.reset_cache()
    state["mode"] = "renamed"

    idx = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"},
        db=db_session, workspace_id="default", force_refresh=True,
    )
    assert idx.source == "stale-db", (
        "zero matched_count must be treated as failure, not silently overwrite snapshot"
    )
    assert idx.scores == {"claude-opus-4-7": 57.0}


async def test_get_quality_index_serves_stale_on_failure(monkeypatch):
    """AA having a bad day shouldn't disable quality routing entirely.
    Within the stale-grace window, return the last known good values
    with source='stale-cache'."""
    from app import config as cfg
    from packages.litellm_adapter import quality_index

    quality_index.reset_cache()
    monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "sk-aa-test")
    cfg.get_settings.cache_clear()

    state = {"mode": "live"}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["mode"] == "fail":
            # 5xx is what AA actually serves on outage; the SDK will
            # raise via raise_for_status() and our except branch runs.
            return httpx.Response(503, json={"error": "service unavailable"})
        return _aa_response([
            {"name": "Claude Opus 4.7 (max)",
             "evaluations": {"artificial_analysis_intelligence_index": 57}},
        ])

    _patch_aa_transport(monkeypatch, handler)

    # Prime the cache.
    idx_live = await quality_index.get_quality_index(catalog_ids={"claude-opus-4-7"})
    assert idx_live.source == "live"

    # Now break AA, force refresh — must serve stale.
    state["mode"] = "fail"
    idx_stale = await quality_index.get_quality_index(
        catalog_ids={"claude-opus-4-7"}, force_refresh=True,
    )
    assert idx_stale.source == "stale-cache"
    assert idx_stale.scores == {"claude-opus-4-7": 57.0}, "stale value preserved"
