"""Per-request cost computation for the analytics dashboard.

`cost_microcents` used to be hard-coded to 0 in `_build_log_row`, which
made every request look free in the dashboard's "Today's spend" tile and
falsely inflated the savings-vs-baseline percentage on
/v1/analytics/savings (baseline non-zero, actual zero, savings = 100%).

Current implementation is two-tier:

  Tier 1 — `litellm_cost_usd` plumbed through the response's `_orca_meta`.
  This is LiteLLM's `_hidden_params.response_cost`, computed at the moment
  the Router knew which provider it actually called. Authoritative because
  it knows about Anthropic prompt caching, OpenAI reasoning tokens, audio
  pricing, and provider aliasing.

  Tier 2 — `tokens × catalog price` fallback. Used when LiteLLM didn't
  attach a cost (cache hits served from our prompt cache, exception paths,
  custom upstreams).

Tests below pass `litellm_cost_usd=None` to exercise tier 2 directly and
pass a non-None value to exercise tier 1.
"""

from __future__ import annotations

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
