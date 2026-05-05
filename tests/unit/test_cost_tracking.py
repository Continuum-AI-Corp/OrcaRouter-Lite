"""Per-request cost computation for the analytics dashboard.

Used to be hard-coded to 0 in `_build_log_row`, which made every request
look free in the dashboard's "Today's spend" tile and falsely inflated
the savings-vs-baseline percentage on /v1/analytics/savings (baseline
was non-zero, actual was zero, savings = 100%).

These tests pin the cost calculation against the same USD/token unit
convention as `analytics.py:savings` (1 USD = 1,000,000 microcents) so
both sides of that comparison stay consistent.
"""

from __future__ import annotations


def test_cost_microcents_basic_arithmetic():
    """Reference: gpt-4o-mini priced at 1.5e-7 / 6e-7 USD per token.
    1000 input + 500 output = 1.5e-4 + 3e-4 = 4.5e-4 USD = 450 microcents."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    fake = CatalogModel(
        id="test-model", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1.5e-7, output_cost_per_token=6e-7,
    )
    CATALOG_BY_ID["test-model"] = fake
    try:
        result = _compute_cost_microcents("test-model", 1000, 500)
        assert result == 450, f"expected 450 microcents, got {result}"
    finally:
        CATALOG_BY_ID.pop("test-model", None)


def test_cost_zero_for_zero_tokens():
    """A pre-flight failure (e.g. validation reject) has 0 tokens and must
    record 0 cost — not crash and not invent a phantom charge."""
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents("gpt-4o", 0, 0) == 0


def test_cost_zero_for_unknown_model():
    """LiteLLM may rewrite response.model to a provider-specific name we
    don't carry. Better to under-report this row's cost than to crash the
    log-write path. The savings dashboard's baseline is computed
    separately, so a 0 here just means 'this row didn't bill' — not 'this
    row had an error.'"""
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents("totally-fake-model-x", 1000, 500) == 0


def test_cost_strips_provider_prefix():
    """LiteLLM sometimes returns response.model as 'openai/gpt-4o' instead
    of bare 'gpt-4o'. The cost helper should strip the prefix before
    looking up the catalog entry — otherwise every prefixed response would
    log 0."""
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel

    fake = CatalogModel(
        id="prefix-test", provider="x", litellm_prefix="x/",
        supports_tools=True, supports_vision=False, supports_json_mode=False,
        input_cost_per_token=1e-7, output_cost_per_token=2e-7,
    )
    CATALOG_BY_ID["prefix-test"] = fake
    try:
        bare = _compute_cost_microcents("prefix-test", 100, 100)
        prefixed = _compute_cost_microcents("openai/prefix-test", 100, 100)
        assert bare == prefixed, (
            "provider-prefixed and bare names must price identically"
        )
        assert bare > 0
    finally:
        CATALOG_BY_ID.pop("prefix-test", None)


def test_cost_handles_none_model():
    """`actual_resolved` may be None on early failures. Don't blow up."""
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents(None, 100, 100) == 0


def test_cost_clamps_negative_tokens_to_zero():
    """Defensive: usage data from upstream can occasionally be malformed.
    Don't write negative cost into the DB."""
    from app.routes.chat import _compute_cost_microcents
    assert _compute_cost_microcents("gpt-4o", -10, 100) == 0
    assert _compute_cost_microcents("gpt-4o", 100, -10) == 0


def test_cost_unit_matches_savings_baseline_convention():
    """`/v1/analytics/savings` computes the baseline as
    `tokens * cost_per_token * 1_000_000` (analytics.py:171). Our
    per-row cost must use the SAME multiplier or the savings percentage
    is meaningless. This test pins both sides to the same convention."""
    from app.routes.analytics import _hosted_auto_savings  # noqa: F401  (proves import works)
    from app.routes.chat import _compute_cost_microcents
    from packages.litellm_adapter.catalog import CATALOG_BY_ID

    # Pick any real catalog model with non-zero pricing.
    real = next((m for m in CATALOG_BY_ID.values() if m.input_cost_per_token > 0), None)
    assert real is not None, "expected at least one priced model in catalog"

    expected = int(
        100 * real.input_cost_per_token * 1_000_000
        + 50 * real.output_cost_per_token * 1_000_000
    )
    actual = _compute_cost_microcents(real.id, 100, 50)
    assert actual == expected, (
        f"cost convention mismatch: chat row uses {actual}, "
        f"savings baseline would compute {expected}"
    )
