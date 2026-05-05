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


# Blended weights — chat output dominates cost in practice. Same heuristic
# as `apps/api/router_cache.py:_provider_order_key`.
_INPUT_WEIGHT = 0.3
_OUTPUT_WEIGHT = 0.7


# Map our user-facing strategy names to litellm.Router's `routing_strategy`.
# `balanced` and `quality` use litellm's default (simple-shuffle, weighted by
# RPM/TPM) — strategy intent is realised in `choose_auto_model` for `quality`,
# and is a no-op for `balanced`. `None` means "don't pass routing_strategy".
STRATEGY_TO_LITELLM: dict[str, str | None] = {
    "balanced": None,
    "cheapest": "cost-based-routing",
    "fastest": "latency-based-routing",
    "quality": None,
}


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
    top_n: int = 5,
) -> list[str]:
    """Return up to `top_n` deployable models matching all `needs`, best first.

    Empty list means no candidate satisfies the request. The first element is
    the primary; subsequent elements are intended as LiteLLM Router fallbacks
    so a 404 / cooldown on the primary cascades to the next-best candidate
    without the user seeing an error.

    Selection rule by strategy:
      - `quality`: highest quality_score first (when scores are non-empty),
        cost as the tie-breaker. Falls back to "highest blended cost" when
        no scores are provided — the legacy proxy that breaks for newer
        flagships priced lower than older ones (Anthropic Opus 4.7 vs
        Opus 4 from May 2024). Provide AA scores via `quality_scores=`.
      - everything else (`cheapest` / `balanced` / `fastest` / None): lowest
        blended cost. `fastest` shares the cheapest-capable rule because the
        catalog has no per-model latency data; ordering across deployments of
        the same model is handled by litellm's `latency-based-routing`.

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
        return []
    if strategy == "quality":
        # When AA scores (or operator overrides) are available, sort by
        # score descending. Cost is a tie-breaker (most expensive among
        # equally-scored models tends to be the flagship version vs a
        # smaller variant). Unscored models drop to the bottom of the
        # quality ranking but stay eligible — better to surface them
        # than to disappear them on a transient AA outage.
        if quality_scores:
            eligible.sort(
                key=lambda m: (-quality_scores.get(m.id, 0.0), -_blended_cost(m), m.id)
            )
        else:
            # Legacy fallback: cost-as-quality-proxy. Wrong for modern
            # pricing but stable when no benchmark data is available.
            eligible.sort(key=lambda m: (-_blended_cost(m), m.id))
    else:
        eligible.sort(key=lambda m: (_blended_cost(m), m.id))

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

    return [m.id for m in deduped[:top_n]]
