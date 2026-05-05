"""model="auto" — pick top-N models that meet capability requirements.

The contract:
  1. Inspect the request to figure out required capabilities (tools, vision,
     json_mode) from `tools` / `tool_choice` / `response_format` / message
     image content.
  2. From the catalog, filter to models that advertise every required
     capability.
  3. From the deployable subset (configured providers + hosted upstream),
     return the top-N by blended (input + output) per-token cost — the first
     element is the primary, the rest are intended as LiteLLM Router
     fallbacks for automatic cascade on 404 / cooldown.
  4. The chat handler sends candidates[0] as the model and candidates[1:]
     as fallbacks via `acompletion(fallbacks=...)`.

This is the differentiated feature that LiteLLM's Router does not provide
on its own — Router does the cascade, but it needs to know which models to
fall back to. choose_auto_model produces that ordered list.
"""

from __future__ import annotations

# ── capability detection ────────────────────────────────────────────────

def test_required_capabilities_empty_for_plain_chat():
    from app.auto_routing import required_capabilities

    body = {"messages": [{"role": "user", "content": "hi"}]}
    assert required_capabilities(body) == set()


def test_required_capabilities_picks_up_tools():
    from app.auto_routing import required_capabilities

    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function", "function": {"name": "foo"}}],
    }
    assert "tools" in required_capabilities(body)


def test_required_capabilities_skips_tools_when_choice_is_none():
    """`tool_choice=none` is an explicit opt-out — don't force a tool-capable model."""
    from app.auto_routing import required_capabilities

    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function", "function": {"name": "foo"}}],
        "tool_choice": "none",
    }
    assert "tools" not in required_capabilities(body)


def test_required_capabilities_picks_up_json_mode():
    from app.auto_routing import required_capabilities

    body = {
        "messages": [{"role": "user", "content": "hi"}],
        "response_format": {"type": "json_object"},
    }
    assert "json_mode" in required_capabilities(body)


def test_required_capabilities_picks_up_vision_from_image_url_content():
    from app.auto_routing import required_capabilities

    body = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "what's this?"},
                {"type": "image_url", "image_url": {"url": "data:..."}},
            ],
        }],
    }
    assert "vision" in required_capabilities(body)


# ── selection ───────────────────────────────────────────────────────────

def test_choose_model_picks_cheapest_meeting_no_requirements():
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("expensive", "openai", "openai/", True, True, True, 1e-5, 3e-5),
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
        CatalogModel("medium", "openai", "openai/", True, True, True, 1e-6, 3e-6),
    ]
    deployable = {"cheap", "medium", "expensive"}
    chosen, _scoring = choose_auto_model(needs=set(), deployable=deployable, candidates=candidates)
    # Cheapest first, then the rest in cost order — the full ordered list
    # becomes the primary + fallback chain.
    assert chosen == ["cheap", "medium", "expensive"]


def test_choose_model_excludes_non_deployable():
    """A model that's in the catalog but has no provider key wired up is skipped."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("free-but-not-keyed", "openai", "openai/", True, False, False, 0.0, 0.0),
        CatalogModel("cheap-and-keyed", "anthropic", "anthropic/", True, False, False, 1e-7, 4e-7),
    ]
    deployable = {"cheap-and-keyed"}  # only this provider has a key
    chosen, _scoring = choose_auto_model(needs=set(), deployable=deployable, candidates=candidates)
    assert chosen == ["cheap-and-keyed"]


def test_choose_model_filters_by_capability():
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        # Cheapest but no vision support — must be skipped when vision required.
        CatalogModel("cheap-no-vision", "groq", "groq/", True, False, False, 1e-8, 1e-8),
        # More expensive but supports vision — should win.
        CatalogModel("vision-capable", "openai", "openai/", True, True, True, 1e-6, 3e-6),
    ]
    deployable = {"cheap-no-vision", "vision-capable"}
    chosen, _scoring = choose_auto_model(
        needs={"vision"}, deployable=deployable, candidates=candidates
    )
    # Only one capable model survives the capability filter.
    assert chosen == ["vision-capable"]


def test_choose_model_returns_empty_when_no_candidate_satisfies():
    """Empty list (not None) signals "no available candidate" so callers can
    treat the return type uniformly without isinstance checks."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("text-only", "groq", "groq/", True, False, False, 1e-8, 1e-8),
    ]
    chosen, _scoring = choose_auto_model(
        needs={"vision"}, deployable={"text-only"}, candidates=candidates
    )
    assert chosen == []


def test_choose_model_uses_blended_input_plus_output_cost():
    """Realistic scoring weights output 70% (typical I/O ratio for chat)."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        # High input, tiny output → low blended cost (mostly output)
        CatalogModel("a", "openai", "openai/", True, False, False, 1e-5, 1e-7),
        # Low input, high output → high blended cost
        CatalogModel("b", "openai", "openai/", True, False, False, 1e-7, 1e-5),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(), deployable={"a", "b"}, candidates=candidates
    )
    # `a` wins the blended-cost comparison (output dominates).
    assert chosen == ["a", "b"]


# ── strategy-aware selection ────────────────────────────────────────────

def test_choose_model_quality_strategy_picks_most_expensive():
    """`quality` is the inverse of `cheapest` — biggest as a proxy for best."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
        CatalogModel("medium", "openai", "openai/", True, False, False, 1e-6, 3e-6),
        CatalogModel("expensive", "openai", "openai/", True, False, False, 1e-5, 3e-5),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap", "medium", "expensive"},
        candidates=candidates,
        strategy="quality",
    )
    # `quality` reverses the order — most expensive first, then descending.
    assert chosen == ["expensive", "medium", "cheap"]


def test_choose_model_cheapest_strategy_matches_default():
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
        CatalogModel("expensive", "openai", "openai/", True, False, False, 1e-5, 3e-5),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap", "expensive"},
        candidates=candidates,
        strategy="cheapest",
    )
    assert chosen == ["cheap", "expensive"]


def test_choose_model_preferred_models_narrows_eligible_set():
    """When `preferred_models` is set and any are eligible, restrict to them."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap-not-preferred", "openai", "openai/", True, False, False, 1e-8, 1e-8),
        CatalogModel("preferred-mid", "openai", "openai/", True, False, False, 1e-6, 3e-6),
        CatalogModel("preferred-big", "openai", "openai/", True, False, False, 1e-5, 3e-5),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap-not-preferred", "preferred-mid", "preferred-big"},
        candidates=candidates,
        strategy="cheapest",
        preferred_models=["preferred-mid", "preferred-big"],
    )
    # Eligible set is restricted to the preferred list, then sorted cheapest-first.
    assert chosen == ["preferred-mid", "preferred-big"]


def test_choose_model_preferred_models_falls_back_when_none_eligible():
    """If preferred_models has no eligible entries, ignore the filter."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap"},
        candidates=candidates,
        preferred_models=["does-not-exist", "neither-does-this"],
    )
    assert chosen == ["cheap"]


# ── litellm strategy mapping ────────────────────────────────────────────

def test_litellm_routing_strategy_maps_known_values():
    from app.auto_routing import litellm_routing_strategy

    assert litellm_routing_strategy("cheapest") == "cost-based-routing"
    # `balanced`, `fastest`, `quality` are all None as of PR 4 — strategy
    # intent is realized in `choose_auto_model`'s ranking logic, not via
    # litellm's routing_strategy. `latency-based-routing` is a no-op for
    # 1-deployment-per-model anyway, so we don't pass it.
    assert litellm_routing_strategy("balanced") is None
    assert litellm_routing_strategy("fastest") is None
    assert litellm_routing_strategy("quality") is None


def test_litellm_routing_strategy_returns_none_for_unknown_or_empty():
    from app.auto_routing import litellm_routing_strategy

    assert litellm_routing_strategy(None) is None
    assert litellm_routing_strategy("") is None
    assert litellm_routing_strategy("not-a-real-strategy") is None


# ── top-N truncation ────────────────────────────────────────────────────

def test_choose_model_caps_results_at_top_n():
    """Caller can opt into a smaller fallback chain to keep latency tight."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel(f"m{i}", "openai", "openai/", True, False, False,
                     1e-7 * (i + 1), 4e-7 * (i + 1))
        for i in range(10)
    ]
    deployable = {f"m{i}" for i in range(10)}
    chosen, _scoring = choose_auto_model(
        needs=set(), deployable=deployable, candidates=candidates, top_n=3
    )
    # Cheapest 3 in cost order; the rest are dropped.
    assert chosen == ["m0", "m1", "m2"]


def test_quality_strategy_uses_quality_scores_when_provided():
    """The motivating bug: with cost-based proxy, `claude-opus-4-20250514`
    ($5.7e-5) outranks `claude-opus-4-7` ($1.9e-5, 3x cheaper). With
    real AA scores, 4-7 (score 57) must win over the older Opus 4."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        # Old Opus 4: more expensive, lower benchmark score.
        CatalogModel("claude-opus-4-old", "anthropic", "anthropic/",
                     True, False, False, 1.5e-5, 7.5e-5),
        # New Opus 4.7: cheaper but stronger.
        CatalogModel("claude-opus-4-7", "anthropic", "anthropic/",
                     True, False, False, 5e-6, 2.5e-5),
    ]
    deployable = {"claude-opus-4-old", "claude-opus-4-7"}
    quality_scores = {"claude-opus-4-7": 57.0, "claude-opus-4-old": 47.0}

    chosen, _scoring = choose_auto_model(
        needs=set(), deployable=deployable, candidates=candidates,
        strategy="quality", quality_scores=quality_scores,
    )
    assert chosen[0] == "claude-opus-4-7", (
        "AA scores must override cost-as-quality-proxy"
    )


def test_quality_strategy_falls_back_to_cost_when_scores_empty():
    """Backward compatibility: when no AA key is configured, scores arrive
    as None or {} → quality reverts to the legacy 'most expensive first'
    behavior. The system still works, just less accurately."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("expensive", "openai", "openai/", True, False, False, 1e-5, 3e-5),
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
    ]
    chosen_none, _ = choose_auto_model(
        needs=set(), deployable={"cheap", "expensive"}, candidates=candidates,
        strategy="quality", quality_scores=None,
    )
    chosen_empty, _ = choose_auto_model(
        needs=set(), deployable={"cheap", "expensive"}, candidates=candidates,
        strategy="quality", quality_scores={},
    )
    assert chosen_none[0] == "expensive"
    assert chosen_empty[0] == "expensive"


def test_quality_unscored_models_drop_below_scored():
    """Models with no AA score (e.g. niche providers AA doesn't track)
    aren't excluded from quality routing — they just rank below any
    scored model. Better than disappearing them."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("scored-low", "openai", "openai/", True, False, False, 1e-7, 4e-7),
        CatalogModel("unscored-expensive", "openai", "openai/", True, False, False, 1e-5, 3e-5),
        CatalogModel("scored-high", "openai", "openai/", True, False, False, 1e-6, 3e-6),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"scored-low", "unscored-expensive", "scored-high"},
        candidates=candidates,
        strategy="quality",
        quality_scores={"scored-high": 57.0, "scored-low": 30.0},
    )
    # Top 3: scored-high (57), scored-low (30), unscored-expensive (0).
    assert chosen == ["scored-high", "scored-low", "unscored-expensive"]


def test_quality_cost_breaks_score_ties():
    """Equal AA scores → break the tie by cost desc (more expensive
    among equally-scored models tends to be the flagship variant
    rather than a smaller distillation)."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("flagship", "openai", "openai/", True, False, False, 1e-5, 3e-5),
        CatalogModel("distill", "openai", "openai/", True, False, False, 1e-7, 4e-7),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(), deployable={"flagship", "distill"}, candidates=candidates,
        strategy="quality",
        quality_scores={"flagship": 57.0, "distill": 57.0},
    )
    assert chosen[0] == "flagship", "tie-break: more expensive wins"


def test_choose_model_default_top_n_is_5():
    """Default cap of 5 keeps the LiteLLM fallbacks list at a reasonable length."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel(f"m{i}", "openai", "openai/", True, False, False,
                     1e-7 * (i + 1), 4e-7 * (i + 1))
        for i in range(10)
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(), deployable={f"m{i}" for i in range(10)}, candidates=candidates
    )
    assert len(chosen) == 5


def test_allowlist_filters_before_top_n_truncation():
    """An allowed model that ranks beyond top_n must NOT be falsely dropped.

    The pre-fix code applied allowlist after the top-N truncation, so an
    allow-listed model at position 6 would get filtered out by the top_n=5
    cut, and the caller would see an empty result and falsely report 403.
    """
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    # 10 models, allowed model is the *last* (most expensive) one.
    candidates = [
        CatalogModel(f"m{i}", "openai", "openai/", True, False, False,
                     1e-7 * (i + 1), 4e-7 * (i + 1))
        for i in range(10)
    ]
    deployable = {f"m{i}" for i in range(10)}
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable=deployable,
        candidates=candidates,
        allowlist=["m9"],   # only the rank-10 (most expensive) model is allowed
    )
    assert chosen == ["m9"], (
        "allowed model ranked beyond top_n must survive — "
        "filter must run before truncation"
    )


def test_allowlist_with_intersection_returns_only_allowed():
    """When multiple allowed models exist, return them in cost order, capped at top_n."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-8, 1e-8),
        CatalogModel("medium", "openai", "openai/", True, False, False, 1e-7, 4e-7),
        CatalogModel("expensive", "openai", "openai/", True, False, False, 1e-5, 3e-5),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap", "medium", "expensive"},
        candidates=candidates,
        allowlist=["medium", "expensive"],
    )
    # cheap is filtered out by allowlist; medium wins on cost.
    assert chosen == ["medium", "expensive"]


def test_allowlist_with_no_intersection_returns_empty():
    """Empty result when no eligible model is in the allowlist — caller decides 403/422."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap"},
        candidates=candidates,
        allowlist=["model-not-in-deployable"],
    )
    assert chosen == []


def test_explicit_empty_allowlist_denies_all():
    """An empty list is an explicit "allow nothing" signal — used by operators
    to fully lock down a key. Falsy-check (`if allowlist`) would silently
    treat it as "no restriction" and route normally, inverting intent."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap"},
        candidates=candidates,
        allowlist=[],   # explicit deny-all
    )
    assert chosen == [], "empty allowlist must deny everything"


def test_none_allowlist_means_no_restriction():
    """Distinct from empty list: allowlist=None means "no allowlist set" — all
    eligible models pass through. The is-not-None check in the implementation
    relies on this distinction."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("cheap", "openai", "openai/", True, False, False, 1e-7, 4e-7),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"cheap"},
        candidates=candidates,
        allowlist=None,
    )
    assert chosen == ["cheap"]


# ── canonical_model_base: strip version-suffixes for dedupe ─────────────


def test_canonical_base_strips_dated_alias():
    from app.auto_routing import canonical_model_base
    assert canonical_model_base("gpt-5-nano-2025-08-07") == "gpt-5-nano"
    assert canonical_model_base("claude-3-5-sonnet-20241022") == "claude-3-5-sonnet"


def test_canonical_base_strips_revision_suffix():
    from app.auto_routing import canonical_model_base
    assert canonical_model_base("gemini-2.0-flash-lite-001") == "gemini-2.0-flash-lite"
    assert canonical_model_base("gemini-1.5-pro-002") == "gemini-1.5-pro"


def test_canonical_base_strips_semver():
    from app.auto_routing import canonical_model_base
    assert canonical_model_base("foo-v1") == "foo"
    assert canonical_model_base("foo-v2.1.0") == "foo"


def test_canonical_base_leaves_non_version_suffix_alone():
    """Branding suffixes are not versions — preserve as-is so distinct catalog
    models stay distinct."""
    from app.auto_routing import canonical_model_base
    assert canonical_model_base("gpt-4o-mini") == "gpt-4o-mini"
    assert canonical_model_base("gpt-4-turbo-preview") == "gpt-4-turbo-preview"
    assert canonical_model_base("claude-3-5-sonnet-latest") == "claude-3-5-sonnet-latest"


def test_canonical_base_with_no_suffix_is_identity():
    from app.auto_routing import canonical_model_base
    assert canonical_model_base("gpt-4o") == "gpt-4o"
    assert canonical_model_base("claude-opus-4-7") == "claude-opus-4-7"


# ── choose_auto_model: dedupe sibling versions out of fallback list ─────


def test_choose_model_dedupes_sibling_versions():
    """Regression: gemini-2.0-flash-lite and gemini-2.0-flash-lite-001 used
    to both end up in the fallback list, which doubled the dead-deployment
    retry latency on a Google outage. Dedupe by canonical base — keep the
    highest-ranked sibling, drop the rest."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("gemini-2.0-flash-lite", "gemini", "gemini/", True, False, False, 1e-7, 4e-7),
        CatalogModel("gemini-2.0-flash-lite-001", "gemini", "gemini/", True, False, False, 1.1e-7, 4.1e-7),
        CatalogModel("gpt-5-nano", "openai", "openai/", True, False, False, 2e-7, 5e-7),
        CatalogModel("gpt-5-nano-2025-08-07", "openai", "openai/", True, False, False, 2.1e-7, 5.1e-7),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={c.id for c in candidates},
        candidates=candidates,
        strategy="cheapest",
    )
    # Each canonical base should appear at most once. The cheaper sibling
    # within each base wins (cheapest strategy sorts by cost asc first).
    assert "gemini-2.0-flash-lite" in chosen
    assert "gemini-2.0-flash-lite-001" not in chosen, (
        "version-suffix sibling should be deduped out of the fallback list"
    )
    assert "gpt-5-nano" in chosen
    assert "gpt-5-nano-2025-08-07" not in chosen


def test_dedupe_preserves_strategy_ranking():
    """Dedupe must run AFTER sort so the highest-ranked sibling per base
    survives, not an arbitrary one. Under quality strategy, the sibling with
    the higher AA score should win."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("foo", "x", "x/", True, False, False, 1e-7, 4e-7),
        CatalogModel("foo-001", "x", "x/", True, False, False, 1e-7, 4e-7),
    ]
    # Give the suffix-variant the higher score.
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"foo", "foo-001"},
        candidates=candidates,
        strategy="quality",
        quality_scores={"foo": 50.0, "foo-001": 80.0},
    )
    assert chosen == ["foo-001"], (
        "quality-ranked sibling (higher score) should survive the dedupe"
    )


def test_dedupe_does_not_collapse_unrelated_models():
    """gpt-4o and gpt-4o-mini share a prefix but `mini` isn't a version
    suffix — they must stay distinct."""
    from app.auto_routing import choose_auto_model
    from packages.litellm_adapter.catalog import CatalogModel

    candidates = [
        CatalogModel("gpt-4o", "openai", "openai/", True, False, False, 5e-6, 15e-6),
        CatalogModel("gpt-4o-mini", "openai", "openai/", True, False, False, 1.5e-7, 6e-7),
    ]
    chosen, _scoring = choose_auto_model(
        needs=set(),
        deployable={"gpt-4o", "gpt-4o-mini"},
        candidates=candidates,
        strategy="cheapest",
    )
    assert "gpt-4o" in chosen and "gpt-4o-mini" in chosen, (
        "branding suffix is not a version — both must remain"
    )


# ── balanced + fastest: PR 4 strict-coverage strategies ────────────────


def _mk(id_, cost, *, vision=False, json_mode=True):
    """Test-only constructor — keeps fixtures readable."""
    from packages.litellm_adapter.catalog import CatalogModel
    return CatalogModel(id_, "test", None, True, vision, json_mode, cost, cost)


def test_balanced_normalized_50_50_avoids_cheap_bias():
    """Critical bias regression: under naive skip-on-missing weighting,
    a cheap-but-no-quality model normalized to 1.0 on cost would beat
    a fully-scored mid-quality model. Strict coverage drops the cheap
    unscored model from the candidate set so the 50/50 normalize gives
    a real middle-ground winner."""
    from app.auto_routing import choose_auto_model

    A = _mk("A", 1e-7)   # cheap, low quality
    B = _mk("B", 5e-6)   # expensive, high quality
    C = _mk("C", 1e-6)   # middle on both
    candidates = [A, B, C]
    quality = {"A": 20.0, "B": 80.0, "C": 50.0}

    chosen, scoring = choose_auto_model(
        needs=set(),
        deployable={m.id for m in candidates},
        candidates=candidates,
        strategy="balanced",
        quality_scores=quality,
    )
    # C wins (best balance), A and B tie at 0.5 → cost tiebreak puts A
    # second, B last.
    assert chosen == ["C", "A", "B"]
    assert scoring["C"].primary_score == 66
    assert scoring["A"].primary_score == 50
    assert scoring["B"].primary_score == 50


def test_balanced_strict_coverage_drops_unscored_from_candidates():
    """Strict-coverage means: a model with no quality data is not
    appended at the end — it's removed from the candidate set entirely.
    Otherwise LiteLLM's fallback chain could still serve traffic from
    a model the operator's strategy says shouldn't be eligible."""
    from app.auto_routing import choose_auto_model

    A = _mk("A", 1e-7)
    B = _mk("B", 5e-6)
    D = _mk("D", 2e-6)   # NO quality data
    candidates = [A, B, D]
    quality = {"A": 20.0, "B": 80.0}   # D missing

    chosen, scoring = choose_auto_model(
        needs=set(),
        deployable={m.id for m in candidates},
        candidates=candidates,
        strategy="balanced",
        quality_scores=quality,
    )
    assert "D" not in chosen, "unscored model must be dropped, not re-appended"
    assert "D" not in scoring


def test_balanced_falls_back_to_cheapest_within_eligible_only():
    """Strict-coverage drop with an empty result must NOT re-expand the
    candidate pool to the full catalog — that would route to models
    outside the deployable set (no provider key configured)."""
    from app.auto_routing import choose_auto_model

    deployed = _mk("deployed", 1e-6)
    not_deployed = _mk("not-deployed", 1e-9)
    candidates = [deployed, not_deployed]

    chosen, _ = choose_auto_model(
        needs=set(),
        deployable={"deployed"},   # not_deployed excluded upfront
        candidates=candidates,
        strategy="balanced",
        quality_scores={},   # no scored models → fallback path
    )
    assert chosen == ["deployed"]
    assert "not-deployed" not in chosen


def test_fastest_combines_tps_and_ttft_50_50():
    """fastest = 0.5 × tps_norm + 0.5 × ttft_inverted_norm. Verified
    against the plan fixture (computed by hand): A dominates both
    axes, B is worst on both, C is middle and gets ~53/100."""
    from app.auto_routing import choose_auto_model

    A = _mk("A", 1e-7)
    B = _mk("B", 5e-6)
    C = _mk("C", 1e-6)
    candidates = [A, B, C]
    tps =  {"A": 200.0, "B": 50.0,  "C": 120.0}
    ttft = {"A": 0.3,   "B": 2.0,   "C": 1.0}

    chosen, scoring = choose_auto_model(
        needs=set(),
        deployable={m.id for m in candidates},
        candidates=candidates,
        strategy="fastest",
        tps_scores=tps,
        ttft_scores=ttft,
    )
    assert chosen == ["A", "C", "B"]
    assert scoring["A"].primary_score == 100
    assert scoring["C"].primary_score == 53   # round(0.527 * 100)
    assert scoring["B"].primary_score == 0


def test_fastest_strict_two_axis_drops_single_axis_models():
    """A model with only TPS (no TTFT) would normalize to 1.0 on its
    only axis under skip-on-missing — the same reverse bias balanced
    fixed. fastest requires BOTH axes to participate."""
    from app.auto_routing import choose_auto_model

    A = _mk("A", 1e-7)
    B = _mk("B", 5e-6)
    SINGLE = _mk("only-tps", 1e-6)   # has TPS but no TTFT
    candidates = [A, B, SINGLE]
    tps =  {"A": 200.0, "B": 50.0, "only-tps": 999.0}
    ttft = {"A": 0.3,   "B": 2.0}   # SINGLE missing

    chosen, _ = choose_auto_model(
        needs=set(),
        deployable={m.id for m in candidates},
        candidates=candidates,
        strategy="fastest",
        tps_scores=tps,
        ttft_scores=ttft,
    )
    assert "only-tps" not in chosen, (
        "single-axis model must not participate (would get inflated score)"
    )


def test_fastest_falls_back_to_cheapest_without_any_metrics():
    """No TPS, no TTFT → fall back to cheapest within eligible. Without
    this the fastest strategy would silently return zero candidates
    when AA isn't configured."""
    from app.auto_routing import choose_auto_model

    A = _mk("A", 1e-7)
    B = _mk("B", 5e-6)
    candidates = [A, B]

    chosen, scoring = choose_auto_model(
        needs=set(),
        deployable={m.id for m in candidates},
        candidates=candidates,
        strategy="fastest",
        tps_scores=None,
        ttft_scores=None,
    )
    assert chosen == ["A", "B"], "fall back to cheapest order"
    # cheapest scoring → primary_score is None
    assert scoring["A"].primary_score is None


def test_normalize_helper_handles_collapsed_range():
    """All-equal values would divide by zero in min-max. Guard returns
    1.0 for everyone so tiebreakers decide."""
    from app.auto_routing import _normalize

    # All same value
    out = _normalize({"a": 5.0, "b": 5.0, "c": 5.0}, ["a", "b", "c"])
    assert out == {"a": 1.0, "b": 1.0, "c": 1.0}


def test_normalize_helper_returns_empty_on_no_input():
    """Empty input → empty output. Caller must handle (we don't return
    {a: 0, b: 0} which would silently let the caller invent rankings)."""
    from app.auto_routing import _normalize

    assert _normalize({}, []) == {}
    assert _normalize({}, ["a", "b"]) == {}


def test_choose_auto_model_returns_scoring_dict_keyed_on_winner_after_dedupe():
    """Sibling-version dedupe runs after sort. The returned scoring dict
    must be keyed only by the deduped survivors (the IDs in the result
    list), not include the dropped sibling."""
    from app.auto_routing import choose_auto_model

    base = _mk("gemini-2.0-flash", 1e-7)
    dated = _mk("gemini-2.0-flash-001", 1e-7)   # version sibling
    other = _mk("other", 5e-6)
    candidates = [base, dated, other]

    chosen, scoring = choose_auto_model(
        needs=set(),
        deployable={m.id for m in candidates},
        candidates=candidates,
        strategy="cheapest",
    )
    # One of the gemini siblings drops out; whichever survives is in scoring.
    assert set(scoring.keys()) == set(chosen)
    assert "other" in scoring


def test_primary_score_is_int_0_to_100():
    """Score scale contract: balanced/fastest emit int 0-100. UI
    `toFixed(0)` callsites would silently break if the type drifted
    back to float (or worse, NaN)."""
    from app.auto_routing import choose_auto_model

    A = _mk("A", 1e-7)
    B = _mk("B", 5e-6)
    C = _mk("C", 1e-6)
    candidates = [A, B, C]

    _, scoring = choose_auto_model(
        needs=set(),
        deployable={m.id for m in candidates},
        candidates=candidates,
        strategy="balanced",
        quality_scores={"A": 20.0, "B": 80.0, "C": 50.0},
    )
    for sd in scoring.values():
        assert isinstance(sd.primary_score, int)
        assert 0 <= sd.primary_score <= 100


def test_balanced_falls_back_when_aa_covers_no_eligible_model():
    """Edge case codex caught: AA quality data is configured GLOBALLY
    (`quality_scores` is non-empty) but no model in this request's
    eligible set is in it (allowlist or capability filter excluded all
    covered models). Plan-intentional behavior: fall back to cheapest
    of the eligible set so traffic still flows. The dashboard's
    `scoring_source` distinguishes this from the no-AA-configured case."""
    from app.auto_routing import choose_auto_model

    covered = _mk("covered", 1e-6)
    uncovered_only = _mk("uncovered", 5e-6)
    candidates = [covered, uncovered_only]
    # AA has quality for `covered` — but `covered` is NOT in deployable
    # (eg the operator's only configured provider key serves `uncovered`).
    quality = {"covered": 90.0}
    chosen, scoring = choose_auto_model(
        needs=set(),
        deployable={"uncovered"},
        candidates=candidates,
        strategy="balanced",
        quality_scores=quality,
    )
    assert chosen == ["uncovered"]
    assert scoring["uncovered"].primary_score is None, (
        "fall-back path emits cheapest scoring (no primary_score), so the "
        "dashboard can show the operator they're not getting balanced ranking"
    )


def test_fastest_falls_back_when_aa_covers_no_eligible_model():
    """Same as above for fastest. AA TPS+TTFT exist, but no eligible model
    is covered on both axes. Fall back to cheapest, surface via scoring."""
    from app.auto_routing import choose_auto_model

    covered = _mk("covered", 1e-6)
    uncovered = _mk("uncovered", 5e-6)
    candidates = [covered, uncovered]
    tps =  {"covered": 200.0}   # eligible (uncovered) not in maps
    ttft = {"covered": 0.3}
    chosen, scoring = choose_auto_model(
        needs=set(),
        deployable={"uncovered"},
        candidates=candidates,
        strategy="fastest",
        tps_scores=tps,
        ttft_scores=ttft,
    )
    assert chosen == ["uncovered"]
    assert scoring["uncovered"].primary_score is None
