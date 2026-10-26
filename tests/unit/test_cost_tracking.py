"""Per-request cost computation for the analytics dashboard.

`cost_microcents` used to be hard-coded to 0 in `_build_log_row`, which
made every request look free in the dashboard's "Today's spend" tile and
falsely inflated the savings-vs-baseline percentage on
/v1/analytics/savings (baseline non-zero, actual zero, savings = 100%).

Current implementation is two-tier:

  Tier 1 — nonnegative upstream usage.cost_usd, then LiteLLM's estimate from
  `_orca_meta`. The upstream billed cost wins when both are present.
  The adapter estimate knows about cache usage and provider aliasing.

  Tier 2 — `tokens × catalog price` fallback. Used when LiteLLM didn't
  attach a cost (cache hits served from our prompt cache, exception paths,
  custom upstreams).

Tests below pass `litellm_cost_usd=None` to exercise tier 2 directly and
pass a non-None value to exercise tier 1.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("upstream,expected", [
    (0.123, 123000), (0.000125, 125),
    (None, 500), (0, 0), (-1, 500), (float("nan"), 500),
    (float("inf"), 500), (True, 500), ("0.123", 500),
])
async def test_log_prefers_valid_upstream_cost_then_adapter_estimate(upstream, expected):
    import time

    from app.routes.chat import _build_log_row
    from app.schemas import ChatCompletionRequest
    from packages.auth.types import KeyContext

    row = await _build_log_row(
        body=ChatCompletionRequest(model="gpt-5", messages=[{"role": "user", "content": "hi"}]),
        kc=KeyContext(key_id="test-key", workspace_id="test-workspace", name="test"),
        response={"model": "gpt-5", "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost_usd": upstream},
                  "_orca_meta": {"provider": "orcarouter", "cost_usd": 0.0005}},
        status_code=200, error_type=None, started_perf=time.perf_counter(),
        strategy="balanced", requested_model="gpt-5",
    )
    assert row.cost_microcents == expected


async def test_zero_adapter_estimate_remains_unknown_for_catalog_fallback(monkeypatch):
    import time

    from app.routes.chat import _build_log_row
    from app.schemas import ChatCompletionRequest
    from packages.auth.types import KeyContext
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    monkeypatch.setitem(CATALOG_BY_ID, "test-zero-estimate", SimpleNamespace(
        input_cost_per_token=1e-6, output_cost_per_token=2e-6,
        cache_read_input_token_cost=None, provider="openai",
    ))
    row = await _build_log_row(
        body=ChatCompletionRequest(model="test-zero-estimate", messages=[{"role": "user", "content": "hi"}]),
        kc=KeyContext(key_id="test-key", workspace_id="test-workspace", name="test"),
        response={"model": "test-zero-estimate", "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
                  "_orca_meta": {"provider": "openai", "cost_usd": 0}},
        status_code=200, error_type=None, started_perf=time.perf_counter(),
        strategy="balanced", requested_model="test-zero-estimate",
    )
    assert row.cost_microcents == 1200


@pytest.mark.parametrize("history,expected", [
    (None, None), ({}, None), ([], None), ([None, {}, {"usage": None}], None),
    ([{"usage": {"cost": 0.123}}], None),
    ([{"usage": {"cost_usd": -1}}], None),
    # Unassociated historical costs cannot establish the final bill.
    ([{"usage": {"cost_usd": 0.123}}], None),
    ([SimpleNamespace(usage=SimpleNamespace(cost_usd=0.123))], None),
])
def test_retained_stream_history_requires_associated_upstream_cost(history, expected):
    from app.routes.chat import _retained_upstream_cost_usd

    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    assert _retained_upstream_cost_usd(SimpleNamespace(chunks=history), usage) == expected
    assert _retained_upstream_cost_usd(object(), usage) is None


@pytest.mark.parametrize("details,top,rate,provider,expected", [
    ({"cached_tokens": 9000}, None, 1.25e-6, "openai", 14750),
    ({"cached_tokens": 9000, "cache_write_tokens": 500}, None, 1.25e-6, "openai", 14750),
    ({"cached_tokens": 9000, "cache_write_tokens": 1001}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": 9000, "cache_write_tokens": -1}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": 9000, "cache_write_tokens": 1, "cache_creation_tokens": 2}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": 0}, None, 1.25e-6, "openai", 26000),
    ({}, 9000, 1.25e-6, "openai", 14750),
    ({"cached_tokens": 9000}, 9000, 1.25e-6, "openai", 14750),
    ({"cached_tokens": 9000}, 8000, 1.25e-6, "openai", 26000),
    ({"cached_tokens": 9000}, None, None, "openai", 26000),
    ({"cached_tokens": 9000}, None, 0.0, "openai", 3500),
    ({"cached_tokens": 9000}, None, 1.25e-6, "orcarouter", 26000),
    ({"cached_tokens": 9000}, None, 1.25e-6, "unknown", 14750),
    ({"cached_tokens": -1}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": 10001}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": True}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": "9000"}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": 9000.5}, None, 1.25e-6, "openai", 26000),
    ({"cached_tokens": None}, None, 1.25e-6, "openai", 26000),
])
def test_cache_read_fallback_uses_only_known_bounded_read_tokens(monkeypatch, details, top, rate, provider, expected):
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    model = SimpleNamespace(**{**vars(CATALOG_BY_ID["gpt-4o"]),
                              "input_cost_per_token": 2.5e-6, "output_cost_per_token": 1e-5,
                              "cache_read_input_token_cost": rate})
    monkeypatch.setitem(CATALOG_BY_ID, "gpt-4o", model)
    usage = {"prompt_tokens_details": details}
    if top is not None:
        usage["cache_read_input_tokens"] = top
    assert _compute_cost_microcents(
        litellm_cost_usd=None, model_id="openai/gpt-4o", input_tokens=10000,
        output_tokens=100, usage=usage, provider=provider,
    ) == expected


@pytest.mark.parametrize("rate", [-1.0, float("nan"), float("inf"), "unknown", True])
def test_catalog_omits_unusable_cache_read_rates(monkeypatch, rate):
    import litellm

    from packages.litellm_adapter.catalog import _build_catalog_from_litellm

    monkeypatch.setattr(litellm, "model_cost", {"invalid-cache-rate": {
        "litellm_provider": "openai", "mode": "chat", "cache_read_input_token_cost": rate,
    }})
    model = next(m for m in _build_catalog_from_litellm() if m.id == "invalid-cache-rate")
    assert model.cache_read_input_token_cost is None


@pytest.mark.parametrize("resolved", ["unpriced-rebrand", "gpt-4o-20991231"])
def test_requested_or_version_guessed_model_does_not_establish_cache_read_rate(monkeypatch, resolved):
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    model = SimpleNamespace(**{**vars(CATALOG_BY_ID["gpt-4o"]),
                              "input_cost_per_token": 2.5e-6, "output_cost_per_token": 1e-5,
                              "cache_read_input_token_cost": 1.25e-6})
    monkeypatch.setitem(CATALOG_BY_ID, "gpt-4o", model)
    assert _compute_cost_microcents(
        litellm_cost_usd=None, model_id=resolved, fallback_model="gpt-4o",
        input_tokens=10000, output_tokens=100, usage={"prompt_tokens_details": {"cached_tokens": 9000}},
    ) == 26000

# ── Tier 1: LiteLLM's pre-computed cost takes priority ──────────────────


def test_tier1_litellm_cost_used_when_present():
    """When _orca_meta carries cost_usd, use it directly. Multiplier:
    USD × 1_000_000 = microcents."""
    from app.routes.chat import _compute_cost_microcents
    result = _compute_cost_microcents(
        litellm_cost_usd=0.000_500,  # = 500 microcents
        model_id="any-model",
        input_tokens=1, output_tokens=1,
    )
    assert result == 500


def test_tier1_overrides_catalog_even_when_catalog_would_disagree():
    """Tier 1 wins because LiteLLM's number is more accurate (cache /
    reasoning aware) than our flat catalog calc."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    # Catalog says 100 microcents, but LiteLLM said 500 (e.g. because it
    # accounted for cache_creation = 1.25x base). Use LiteLLM.
    fake = CatalogModel(
        id="t1-overrides", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1e-7, output_cost_per_token=2e-7,
    )
    CATALOG_BY_ID["t1-overrides"] = fake
    try:
        result = _compute_cost_microcents(
            litellm_cost_usd=0.000_500,
            model_id="t1-overrides",
            input_tokens=1000, output_tokens=500,
        )
        assert result == 500, "tier 1 must win over tier 2 when both available"
    finally:
        CATALOG_BY_ID.pop("t1-overrides", None)


def test_tier1_zero_falls_through_to_catalog():
    """LiteLLM returning cost_usd=0 means it couldn't price (unknown
    model in its table). Don't accept that as 'authoritative zero' —
    let the catalog have a shot."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    fake = CatalogModel(
        id="t1-zero", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1e-7, output_cost_per_token=2e-7,
    )
    CATALOG_BY_ID["t1-zero"] = fake
    try:
        result = _compute_cost_microcents(
            litellm_cost_usd=0.0,
            model_id="t1-zero",
            input_tokens=1000, output_tokens=500,
        )
        expected = int((1000 * 1e-7 + 500 * 2e-7) * 1_000_000)
        assert result == expected, (
            "tier-1 zero must fall through to tier-2 catalog calculation"
        )
    finally:
        CATALOG_BY_ID.pop("t1-zero", None)


def test_tier1_negative_cost_clamped_to_zero():
    """Defensive: never write negative cost into the DB regardless of
    where the number came from."""
    from app.routes.chat import _compute_cost_microcents
    result = _compute_cost_microcents(
        litellm_cost_usd=-0.5,  # malformed
        model_id="any",
        input_tokens=1, output_tokens=1,
    )
    # Negative tier-1 is treated as "no tier-1 data" and falls through.
    # With model_id not in catalog and no fallback, returns 0.
    assert result == 0


# ── Tier 2: catalog × tokens fallback ───────────────────────────────────


def test_tier2_basic_arithmetic():
    """Reference: 1.5e-7 / 6e-7 USD per token, 1000 input + 500 output =
    1.5e-4 + 3e-4 = 4.5e-4 USD = 450 microcents."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    fake = CatalogModel(
        id="t2-basic", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1.5e-7, output_cost_per_token=6e-7,
    )
    CATALOG_BY_ID["t2-basic"] = fake
    try:
        result = _compute_cost_microcents(
            litellm_cost_usd=None,
            model_id="t2-basic",
            input_tokens=1000, output_tokens=500,
        )
        assert result == 450
    finally:
        CATALOG_BY_ID.pop("t2-basic", None)


def test_tier2_zero_for_zero_tokens():
    """Pre-flight failures have 0 tokens → 0 cost, no crash."""
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents(
        litellm_cost_usd=None, model_id="gpt-4o",
        input_tokens=0, output_tokens=0,
    ) == 0


def test_tier2_zero_for_unknown_model():
    """Unknown to catalog AND no fallback → 0. Better to under-report
    than crash the log-write path."""
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents(
        litellm_cost_usd=None, model_id="totally-fake-model-x",
        input_tokens=1000, output_tokens=500,
    ) == 0


def test_tier2_strips_provider_prefix():
    """`openai/gpt-4o` → `gpt-4o` for catalog lookup."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    fake = CatalogModel(
        id="t2-prefix", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1e-7, output_cost_per_token=2e-7,
    )
    CATALOG_BY_ID["t2-prefix"] = fake
    try:
        bare = _compute_cost_microcents(
            litellm_cost_usd=None, model_id="t2-prefix",
            input_tokens=100, output_tokens=100,
        )
        prefixed = _compute_cost_microcents(
            litellm_cost_usd=None, model_id="openai/t2-prefix",
            input_tokens=100, output_tokens=100,
        )
        assert bare == prefixed > 0
    finally:
        CATALOG_BY_ID.pop("t2-prefix", None)


def test_tier2_handles_none_model():
    """`actual_resolved` may be None on early failures."""
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents(
        litellm_cost_usd=None, model_id=None,
        input_tokens=100, output_tokens=100,
    ) == 0


def test_tier2_clamps_negative_tokens():
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents(
        litellm_cost_usd=None, model_id="gpt-4o",
        input_tokens=-10, output_tokens=100,
    ) == 0
    assert _compute_cost_microcents(
        litellm_cost_usd=None, model_id="gpt-4o",
        input_tokens=100, output_tokens=-10,
    ) == 0


def test_tier2_strips_version_suffix_for_dated_alias():
    """When the response is `claude-3-5-sonnet-20241022` but only the
    base `claude-3-5-sonnet` is in catalog, strip the date and find it."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    fake_base = CatalogModel(
        id="t2-aliastest-sonnet", provider="anthropic", litellm_prefix="anthropic/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=3e-6, output_cost_per_token=15e-6,
    )
    CATALOG_BY_ID["t2-aliastest-sonnet"] = fake_base
    try:
        result = _compute_cost_microcents(
            litellm_cost_usd=None,
            model_id="t2-aliastest-sonnet-20241022",
            input_tokens=1000, output_tokens=500,
        )
        baseline = _compute_cost_microcents(
            litellm_cost_usd=None,
            model_id="t2-aliastest-sonnet",
            input_tokens=1000, output_tokens=500,
        )
        assert result == baseline > 0, "version-stripped alias should match base price"
    finally:
        CATALOG_BY_ID.pop("t2-aliastest-sonnet", None)


def test_tier2_falls_back_to_requested_model_when_resolved_unknown():
    """Last-resort: when both resolved and canonicalized resolved miss
    the catalog, try the originally requested model id."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    requested = CatalogModel(
        id="t2-reqfallback", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1e-7, output_cost_per_token=2e-7,
    )
    CATALOG_BY_ID["t2-reqfallback"] = requested
    try:
        result = _compute_cost_microcents(
            litellm_cost_usd=None,
            model_id="vendor-x-internal-rebrand-xyz",
            input_tokens=1000, output_tokens=500,
            fallback_model="t2-reqfallback",
        )
        expected = int((1000 * 1e-7 + 500 * 2e-7) * 1_000_000)
        assert result == expected
    finally:
        CATALOG_BY_ID.pop("t2-reqfallback", None)


def test_tier2_resolved_priced_takes_precedence_over_fallback():
    """Resolved (what was actually served) wins over fallback (what was
    asked) when both are catalog hits."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    cheap = CatalogModel(
        id="t2-cheap", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1e-8, output_cost_per_token=2e-8,
    )
    expensive = CatalogModel(
        id="t2-expensive", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1e-5, output_cost_per_token=2e-5,
    )
    CATALOG_BY_ID["t2-cheap"] = cheap
    CATALOG_BY_ID["t2-expensive"] = expensive
    try:
        result = _compute_cost_microcents(
            litellm_cost_usd=None, model_id="t2-cheap",
            input_tokens=1000, output_tokens=500,
            fallback_model="t2-expensive",
        )
        cheap_only = _compute_cost_microcents(
            litellm_cost_usd=None, model_id="t2-cheap",
            input_tokens=1000, output_tokens=500,
        )
        assert result == cheap_only, (
            "must price the served (resolved) model, not the requested one"
        )
    finally:
        CATALOG_BY_ID.pop("t2-cheap", None)
        CATALOG_BY_ID.pop("t2-expensive", None)


def test_tier2_unit_matches_savings_baseline_convention():
    """`/v1/analytics/savings` baseline uses tokens × cost_per_token ×
    1_000_000. Tier 2 must use the SAME convention so the savings
    percentage is meaningful."""
    from app.routes.analytics import _hosted_auto_savings  # noqa: F401  (proves import works)
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    real = next((m for m in CATALOG_BY_ID.values() if m.input_cost_per_token > 0), None)
    assert real is not None

    expected = int(
        100 * real.input_cost_per_token * 1_000_000
        + 50 * real.output_cost_per_token * 1_000_000
    )
    actual = _compute_cost_microcents(
        litellm_cost_usd=None, model_id=real.id,
        input_tokens=100, output_tokens=50,
    )
    assert actual == expected
