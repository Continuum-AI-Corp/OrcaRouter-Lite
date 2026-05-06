"""`model="auto"` — pick catalog models that meet the request's capability
requirements AND have a deployable provider configured. Selection rule depends
on the active routing strategy.

Two pure functions:
  - `required_capabilities(body)`  → set of {"tools", "vision", "json_mode"}
  - `choose_auto_model(needs, deployable, candidates, strategy, preferred_models)`
    → list of model_ids ordered by strategy (best first; empty if none)

The chat handler resolves `model="auto"` by:
  1. computing needs = required_capabilities(request_body)
  2. computing deployable = {dep.model_name for dep in active_deployments}
  3. calling choose_auto_model(...) to get top-N candidates
  4. using candidates[0] as the primary model and candidates[1:] as Router
     fallbacks so a 404/cooldown on the primary cascades automatically.

Adapted from `apps/api/routes/chat.py:_required_capabilities` /
`_score_model_for_auto` in the SaaS edition.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from packages.litellm_adapter.catalog import CatalogModel

# Suffix shapes that mark a model id as a more-specific *version* of a base
# model rather than a different model. Matched against the substring AFTER
# `base + "-"` in a candidate id. Shared with the prompt-cache canonicalization
# in chat.py so both layers agree on what counts as "same model, different
# version stamp."
#   "2024-08-06"   — OpenAI dated version
#   "20241022"     — Anthropic dated version (compact form)
#   "001" / "002"  — Google Vertex / Gemini revision suffix (always 3+ digits)
#   "v1.5"         — Generic version tag
#
# What we deliberately do NOT collapse:
#   "turbo"        — distinct catalog model, not a version variant
#   "latest"       — request-side alias only
#   "mini"         — branding suffix
#   single digits  — Anthropic uses these for semantic version (claude-opus-4-7
#                    is NOT a version of claude-opus-4 — they're different
#                    models). Rev-codes are always 3+ digits.
_VERSION_SUFFIX_RE = re.compile(
    r"^("
    r"\d{4}-\d{2}-\d{2}"     # YYYY-MM-DD
    r"|\d{6,}"                # YYYYMMDD or compact dates / build numbers
    r"|\d{3,4}"               # 001, 002, 1234 (revision codes — always 3+ digits)
    r"|v\d[\d.]*"             # v1, v1.5, v2.0.1
    r")$"
)


def canonical_model_base(model_id: str) -> str:
    """Strip a known version suffix to get the model's canonical base id.

    "gemini-2.0-flash-lite-001" -> "gemini-2.0-flash-lite"
    "gpt-5-nano-2025-08-07"     -> "gpt-5-nano"
    "claude-opus-4-7"           -> "claude-opus-4-7" (single digits NOT stripped)
    "claude-3-5-sonnet"         -> "claude-3-5-sonnet" (no change)

    Used to dedupe sibling versions out of the auto-routing fallback list:
    when the primary picks `gemini-2.0-flash-lite`, we don't want
    `gemini-2.0-flash-lite-001` as the next fallback (Google rolls them
    together — they share an outage and just add ~400ms of useless retry
    latency before the real cross-provider fallback kicks in).
    """
    # Try the LONGEST plausible suffix first so the dashed-date pattern
    # (3 dash-separated segments: YYYY-MM-DD) gets a chance before the
    # bare-digit pattern matches just the last segment. Cap at 3 segments —
    # anything longer is overwhelmingly likely to be the model name itself.
    parts = model_id.split("-")
    for cut in range(min(len(parts) - 1, 3), 0, -1):
        suffix = "-".join(parts[-cut:])
        if _VERSION_SUFFIX_RE.match(suffix):
            base = "-".join(parts[:-cut])
            if base:
                return base
    return model_id

_CAP_FIELD = {
    "tools": "supports_tools",
    "vision": "supports_vision",
    "json_mode": "supports_json_mode",
}


def _lookup_score(scores: dict[str, float], model_id: str) -> float | None:
    """Score lookup with dot→hyphen fallback for O2-native dotted IDs.

    O2 registers models with dots (claude-opus-4.7, gpt-5.1-codex) while
    Artificial Analysis normalizes model names to hyphens (claude-opus-4-7).
    Without this fallback every dotted ID resolves to score=0, so quality/
    balanced routing always ranks AA-scored cheap models above unscored
    expensive ones — actively wrong. Returns None when no score exists in
    either form.
    """
    s = scores.get(model_id)
    if s is None and "." in model_id:
        s = scores.get(model_id.replace(".", "-"))
    return s


# Blended weights — chat output dominates cost in practice. Same heuristic
# as `apps/api/router_cache.py:_provider_order_key`.
_INPUT_WEIGHT = 0.3
_OUTPUT_WEIGHT = 0.7


# Map our user-facing strategy names to litellm.Router's `routing_strategy`.
# We do the strategy-specific ordering ourselves in `choose_auto_model`
# (balanced + fastest as of PR 4); litellm only sees the resulting fallback
# chain. `latency-based-routing` is a no-op when each model has a single
# deployment, which is our shape — so `fastest` is None too.
STRATEGY_TO_LITELLM: dict[str, str | None] = {
    "balanced": None,
    "cheapest": "cost-based-routing",
    "fastest": None,
    "quality": None,
}


@dataclass(frozen=True)
class ScoringDetail:
    """Per-model scoring breakdown returned alongside ranked candidates.

    Lets `/auto-preview` surface the same numbers the ranker used (no
    DRY drift from re-implementing normalize / weight in the route).

    `primary_score`:
      - `None` for `cheapest` (single axis, raw cost has no 0-100 sense)
      - 0-100 int for `quality` (raw AA intelligence_index, rounded)
      - 0-100 int for `balanced` / `fastest` (combined × 100, rounded)

    `breakdown`:
      - `cheapest` → `{"cost": {"raw": float, "normalized": None}}`
      - `quality`  → `{"quality": {"raw": float, "normalized": None}}`
      - `balanced` → `{"quality": {raw, normalized}, "cost": {raw, normalized}}`
      - `fastest`  → `{"tps": {raw, normalized}, "ttft": {raw, normalized}}`
    """
    primary_score: int | None
    breakdown: dict[str, dict[str, float | None]]


def _normalize(values: dict[str, float], model_ids: list[str]) -> dict[str, float]:
    """min-max normalize to [0, 1] over models present in `values`.

    Caller pre-filters: only model_ids that have data in this axis are
    expected. range collapse (all equal) → all 1.0 so tiebreakers
    decide. Empty input → empty output (let caller handle the empty
    candidate set explicitly).
    """
    present = [values[mid] for mid in model_ids if mid in values]
    if not present:
        return {}
    lo, hi = min(present), max(present)
    if hi == lo:
        return {mid: 1.0 for mid in model_ids if mid in values}
    span = hi - lo
    return {
        mid: (values[mid] - lo) / span
        for mid in model_ids if mid in values
    }


def _cheapest_breakdown(m: CatalogModel) -> ScoringDetail:
    """Cheapest has a single raw axis (blended cost). No primary_score
    because there's no meaningful 0-100 mapping for raw token cost."""
    return ScoringDetail(
        primary_score=None,
        breakdown={"cost": {"raw": _blended_cost(m), "normalized": None}},
    )


def litellm_routing_strategy(strategy: str | None) -> str | None:
    """Return the litellm `routing_strategy` for a UI strategy, or None."""
    if not strategy:
        return None
    return STRATEGY_TO_LITELLM.get(strategy)


def _has_vision_content(messages: list[dict]) -> bool:
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in (
                    "image_url", "image", "input_image",
                ):
                    return True
    return False


def required_capabilities(body: dict) -> set[str]:
    """Return the set of capabilities the request needs."""
    needs: set[str] = set()

    has_tools_payload = bool(body.get("tools"))
    tool_choice = body.get("tool_choice")
    tool_choice_explicit_none = (
        isinstance(tool_choice, str) and tool_choice == "none"
    )

    if has_tools_payload and not tool_choice_explicit_none:
        needs.add("tools")
    if isinstance(tool_choice, dict):
        needs.add("tools")
    elif isinstance(tool_choice, str) and tool_choice not in ("", "none"):
        needs.add("tools")

    rf = body.get("response_format")
    if isinstance(rf, dict) and rf.get("type") in ("json_object", "json_schema"):
        needs.add("json_mode")

    if _has_vision_content(body.get("messages") or []):
        needs.add("vision")

    return needs


def _model_meets(model: CatalogModel, needs: Iterable[str]) -> bool:
    return all(getattr(model, _CAP_FIELD[n], False) for n in needs if n in _CAP_FIELD)


def _blended_cost(model: CatalogModel) -> float:
    return (
        _INPUT_WEIGHT * model.input_cost_per_token
        + _OUTPUT_WEIGHT * model.output_cost_per_token
    )


def choose_auto_model(
    *,
    needs: set[str],
    deployable: set[str],
    candidates: Iterable[CatalogModel],
    strategy: str | None = None,
    preferred_models: list[str] | None = None,
    allowlist: list[str] | set[str] | None = None,
    quality_scores: dict[str, float] | None = None,
    tps_scores: dict[str, float] | None = None,
    ttft_scores: dict[str, float] | None = None,
    top_n: int = 5,
) -> tuple[list[str], dict[str, ScoringDetail]]:
    """Return up to `top_n` deployable models matching all `needs`, best first,
    plus a per-model scoring breakdown for the survivors.

    Empty `(list, dict)` means no candidate satisfies the request. The first
    list element is the primary; subsequent elements are intended as LiteLLM
    Router fallbacks so a 404 / cooldown on the primary cascades to the
    next-best candidate without the user seeing an error.

    The scoring dict is keyed by **dedupe-survivor model_id** (the same
    ones in the returned list). `/auto-preview` uses it to render the
    breakdown without re-implementing the ranker (no DRY drift).

    Selection rule by strategy:
      - `quality`: highest quality_score first (when scores are non-empty),
        cost as the tie-breaker. Unscored models drop to the bottom of the
        quality ranking but stay eligible — better to surface them than to
        disappear them on a transient AA outage. Falls back to
        "highest blended cost" when no scores are provided (the legacy
        proxy that breaks for newer flagships priced lower than older ones).
      - `balanced`: 50/50 weighted normalize of quality (max=better) and
        inverted cost (min=better). STRICT axis coverage: a model needs
        BOTH axes to participate in ranking; cost is universal but quality
        depends on AA + overrides. Models lacking quality data are dropped
        from the candidate set entirely (NOT re-appended at the end —
        keeping them in would let LiteLLM's fallback chain serve traffic
        from a model the operator's strategy says shouldn't be eligible).
        Operators who need to cover unscored models should use `cheapest`
        or add a manual quality override.
      - `fastest`: 50/50 weighted normalize of TPS (max=faster) and inverted
        TTFT (min=faster). STRICT axis coverage: BOTH TPS and TTFT
        required, same drop semantics as balanced. Without strict-both,
        a single-axis model normalizes to 1.0 on its only axis and beats
        a fully-scored model with mixed performance — reverse bias.
      - `cheapest` / None: lowest blended cost.

    If `preferred_models` is non-empty AND at least one entry is deployable
    + capability-matching, the eligible set is restricted to that list. This
    lets users pin a quality tier without giving up auto resolution.

    If `allowlist` is non-empty, the eligible set is intersected with it
    BEFORE the top-N cut so an allowed model that would otherwise rank 6+
    isn't accidentally dropped. Empty intersection → empty result, and the
    caller is responsible for surfacing the right HTTP error to the user.

    Excludes models with zero blended cost — those are unpriced entries in
    litellm's catalogue, not actually free, and routing to them would skew
    the savings calculation.
    """
    eligible = [
        m for m in candidates
        if m.id in deployable
        and _model_meets(m, needs)
        and _blended_cost(m) > 0
    ]
    if preferred_models:
        preferred_set = set(preferred_models)
        narrowed = [m for m in eligible if m.id in preferred_set]
        if narrowed:
            eligible = narrowed
    if allowlist is not None:
        # Apply the key's allowlist before sorting + truncation. Without
        # this, an allowed model ranked beyond top_n would be dropped and
        # the caller would falsely report no allowed match.
        # `is not None` (not truthiness): an explicit empty allowlist is
        # a "deny everything" signal from the operator; falsy check would
        # silently invert that into "no restriction" — a security hole.
        allow_set = set(allowlist)
        eligible = [m for m in eligible if m.id in allow_set]
    if not eligible:
        return [], {}

    # Per-strategy: sort `eligible` (which may shrink under strict-coverage)
    # AND build a per-model `scoring_per_model` dict keyed by id. Dedupe +
    # truncate at the end keeps the scoring entries for the survivors.
    scoring_per_model: dict[str, ScoringDetail] = {}

    if strategy == "quality":
        # PR #20 behavior preserved: scored models first by quality desc,
        # unscored stay eligible at the bottom. NOT strict-coverage (a
        # `quality` operator with partial AA still wants their unscored
        # models routable as fallback rather than disappearing).
        if quality_scores:
            eligible.sort(
                key=lambda m: (-(_lookup_score(quality_scores, m.id) or 0.0), -_blended_cost(m), m.id)
            )
            for m in eligible:
                raw = _lookup_score(quality_scores, m.id)
                scoring_per_model[m.id] = ScoringDetail(
                    primary_score=int(round(raw)) if raw is not None else None,
                    breakdown={
                        "quality": {
                            "raw": float(raw) if raw is not None else None,
                            "normalized": None,
                        }
                    },
                )
        else:
            # Legacy: cost-as-quality-proxy when no benchmark data.
            eligible.sort(key=lambda m: (-_blended_cost(m), m.id))
            for m in eligible:
                scoring_per_model[m.id] = _cheapest_breakdown(m)

    elif strategy == "balanced":
        # Strict coverage: model needs BOTH quality and cost. Drop unscored.
        if quality_scores:
            scored_models = [m for m in eligible if _lookup_score(quality_scores, m.id) is not None]
            if scored_models:
                scored_ids = [m.id for m in scored_models]
                cost_inv = {m.id: -_blended_cost(m) for m in scored_models}
                c_norm = _normalize(cost_inv, scored_ids)
                q_subset = {mid: _lookup_score(quality_scores, mid) for mid in scored_ids}
                q_norm = _normalize(q_subset, scored_ids)

                def _bal_score(m: CatalogModel) -> float:
                    return 0.5 * q_norm[m.id] + 0.5 * c_norm[m.id]

                scored_models.sort(key=lambda m: (
                    -_bal_score(m),
                    _blended_cost(m),  # tiebreak 1: cheapest wins
                    m.id,              # tiebreak 2: stable
                ))
                eligible = scored_models  # ← strict drop
                for m in scored_models:
                    scoring_per_model[m.id] = ScoringDetail(
                        primary_score=int(round(_bal_score(m) * 100)),
                        breakdown={
                            "quality": {
                                "raw": float(_lookup_score(quality_scores, m.id)),
                                "normalized": q_norm[m.id],
                            },
                            "cost": {
                                "raw": _blended_cost(m),
                                "normalized": c_norm[m.id],
                            },
                        },
                    )
            else:
                # Strict-cov empty: fall back to cheapest within current
                # eligible (already filtered for deployable / allowlist).
                eligible.sort(key=lambda m: (_blended_cost(m), m.id))
                for m in eligible:
                    scoring_per_model[m.id] = _cheapest_breakdown(m)
        else:
            # No AA + no overrides → cheapest within eligible.
            eligible.sort(key=lambda m: (_blended_cost(m), m.id))
            for m in eligible:
                scoring_per_model[m.id] = _cheapest_breakdown(m)

    elif strategy == "fastest":
        # Strict coverage: model needs BOTH TPS and TTFT.
        if tps_scores and ttft_scores:
            scored_models = [
                m for m in eligible
                if _lookup_score(tps_scores, m.id) is not None
                and _lookup_score(ttft_scores, m.id) is not None
            ]
            if scored_models:
                scored_ids = [m.id for m in scored_models]
                tps_subset = {mid: _lookup_score(tps_scores, mid) for mid in scored_ids}
                tps_norm = _normalize(tps_subset, scored_ids)
                # Lower TTFT = faster, so invert before normalizing so the
                # normalized score points the same way as TPS (higher = better).
                ttft_inv = {mid: -_lookup_score(ttft_scores, mid) for mid in scored_ids}
                ttft_norm = _normalize(ttft_inv, scored_ids)

                def _fast_score(m: CatalogModel) -> float:
                    return 0.5 * tps_norm[m.id] + 0.5 * ttft_norm[m.id]

                scored_models.sort(key=lambda m: (
                    -_fast_score(m),
                    _blended_cost(m),
                    m.id,
                ))
                eligible = scored_models  # ← strict drop
                for m in scored_models:
                    scoring_per_model[m.id] = ScoringDetail(
                        primary_score=int(round(_fast_score(m) * 100)),
                        breakdown={
                            "tps": {
                                "raw": float(_lookup_score(tps_scores, m.id)),
                                "normalized": tps_norm[m.id],
                            },
                            "ttft": {
                                "raw": float(_lookup_score(ttft_scores, m.id)),
                                "normalized": ttft_norm[m.id],
                            },
                        },
                    )
            else:
                eligible.sort(key=lambda m: (_blended_cost(m), m.id))
                for m in eligible:
                    scoring_per_model[m.id] = _cheapest_breakdown(m)
        else:
            eligible.sort(key=lambda m: (_blended_cost(m), m.id))
            for m in eligible:
                scoring_per_model[m.id] = _cheapest_breakdown(m)

    else:  # cheapest / None
        eligible.sort(key=lambda m: (_blended_cost(m), m.id))
        for m in eligible:
            scoring_per_model[m.id] = _cheapest_breakdown(m)

    # Dedupe sibling versions: a model and its dated/numbered variants
    # ("gemini-2.0-flash-lite" + "...-001", "gpt-5-nano" + "...-2025-08-07")
    # share an upstream outage. Keeping both in the fallback list just
    # adds dead-deployment retry latency before the real cross-provider
    # cascade. Keep the highest-ranked one per canonical base.
    seen_bases: set[str] = set()
    deduped: list[CatalogModel] = []
    for m in eligible:
        base = canonical_model_base(m.id)
        if base in seen_bases:
            continue
        seen_bases.add(base)
        deduped.append(m)

    final = deduped[:top_n]
    final_ids = [m.id for m in final]
    # Filter scoring to survivors only — sibling-deduped models drop out.
    scoring = {mid: scoring_per_model[mid] for mid in final_ids if mid in scoring_per_model}
    return final_ids, scoring
