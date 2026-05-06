"""Model catalog for orcarouter-lite — sourced from litellm.model_cost.

LiteLLM ships a community-maintained catalogue of ~2,600 models across
~100 providers (the `model_cost` dict). Lite reads it once at import time,
filters to chat-capable entries from the providers we care about, and
exposes them as `CatalogModel` records with capability flags + per-token
pricing.

Falls back to a small static seed when litellm isn't installed (tests
of unrelated modules don't need it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# ── Provider mapping: litellm prefix → (our provider id, litellm prefix string) ──
# Each entry maps a litellm provider key (the part before the `/` in the model
# string, or the `litellm_provider` field in model_cost) to our internal id +
# the full prefix used when constructing litellm_model strings.
_PROVIDER_BY_LITELLM_KEY: dict[str, tuple[str, str]] = {
    "openai": ("openai", "openai/"),
    "anthropic": ("anthropic", "anthropic/"),
    "gemini": ("google", "gemini/"),
    "vertex_ai-language-models": ("google", "gemini/"),
    "groq": ("groq", "groq/"),
    "together_ai": ("together", "together_ai/"),
    "fireworks_ai": ("fireworks", "fireworks_ai/"),
    "mistral": ("mistral", "mistral/"),
    "deepseek": ("deepseek", "deepseek/"),
    "cohere_chat": ("cohere", "cohere_chat/"),
    "perplexity": ("perplexity", "perplexity/"),
    "xai": ("xai", "xai/"),
}

# Models where litellm doesn't tag mode but we know they're chat-capable.
_FORCE_INCLUDE = {"o1", "o1-mini", "o3", "o3-mini"}

# Excluded non-chat modes.
_EXCLUDED_MODES = {"embedding", "image_generation", "audio_speech",
                   "audio_transcription", "rerank", "moderation"}


@dataclass(frozen=True)
class CatalogModel:
    id: str
    provider: str
    litellm_prefix: str
    supports_tools: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    # ISO-8601 (YYYY-MM-DD) sourced from litellm meta, or None when unknown.
    # Surfaced for UI display; routing-time exclusion happens at load via
    # `_is_obviously_dead` below, not by reading this field.
    deprecation_date: str | None = None


def _is_obviously_dead(meta: dict) -> bool:
    """Return True when meta declares a deprecation_date that is today or earlier.

    Filters out models that the upstream provider has already retired, per
    LiteLLM's community-maintained metadata. We trust this only as a hint —
    providers sometimes pull a model earlier than the published date, which
    is why LiteLLM Router's runtime cooldown is the second line of defense.

    Tolerates malformed values (placeholder strings like LiteLLM's `sample_spec`
    entry) by treating them as "not dead".
    """
    dep = meta.get("deprecation_date", "")
    if not isinstance(dep, str) or not dep:
        return False
    try:
        return date.fromisoformat(dep) <= date.today()
    except ValueError:
        return False


def _is_chat_model(meta: dict) -> bool:
    mode = meta.get("mode", "chat")
    if mode in _EXCLUDED_MODES:
        return False
    return mode in ("chat", "completion") or mode == "chat"


def _strip_prefix(litellm_id: str) -> str:
    """`anthropic/claude-3-5-sonnet-latest` → `claude-3-5-sonnet-latest`."""
    return litellm_id.split("/", 1)[1] if "/" in litellm_id else litellm_id


def _build_catalog_from_litellm() -> list[CatalogModel]:
    try:
        import litellm
    except Exception:
        return _STATIC_FALLBACK[:]

    out: list[CatalogModel] = []
    seen: set[str] = set()
    model_cost = getattr(litellm, "model_cost", {}) or {}

    for raw_id, meta in model_cost.items():
        if not isinstance(meta, dict):
            continue
        litellm_provider = meta.get("litellm_provider", "")
        mapped = _PROVIDER_BY_LITELLM_KEY.get(litellm_provider)
        if mapped is None:
            continue
        provider_id, prefix = mapped
        if not _is_chat_model(meta) and _strip_prefix(raw_id) not in _FORCE_INCLUDE:
            continue
        # Drop models the upstream provider has already retired per LiteLLM's
        # metadata. Models that LiteLLM hasn't marked yet but the provider has
        # killed (e.g. early-deprecation cases) are caught at runtime by the
        # Router's cooldown after the first 404.
        if _is_obviously_dead(meta):
            continue

        canonical = _strip_prefix(raw_id)
        # Some entries duplicate (e.g. "openai/gpt-4o" and "gpt-4o"); first wins.
        if canonical in seen:
            continue
        seen.add(canonical)

        dep_raw = meta.get("deprecation_date")
        out.append(
            CatalogModel(
                id=canonical,
                provider=provider_id,
                litellm_prefix=prefix,
                supports_tools=bool(
                    meta.get("supports_function_calling")
                    or meta.get("supports_tool_choice")
                ),
                supports_vision=bool(meta.get("supports_vision")),
                supports_json_mode=bool(
                    meta.get("supports_response_schema")
                    or meta.get("supports_json_schema")
                ),
                input_cost_per_token=float(meta.get("input_cost_per_token") or 0.0),
                output_cost_per_token=float(meta.get("output_cost_per_token") or 0.0),
                deprecation_date=dep_raw if isinstance(dep_raw, str) and dep_raw else None,
            )
        )

    # Make sure a few flagship aliases are always present even if the litellm
    # version pins a different canonical ID. This keeps demos / examples stable
    # across litellm upgrades. Each alias still respects deprecation: if the
    # underlying model is past its deprecation_date in litellm's metadata, the
    # alias is skipped here as well.
    flagship = {
        "claude-3-5-sonnet-latest": (
            "anthropic", "anthropic/", True, True, False,
            3e-6, 1.5e-5,
        ),
        "claude-3-5-haiku-latest": (
            "anthropic", "anthropic/", True, False, False,
            8e-7, 4e-6,
        ),
    }
    existing_ids = {m.id for m in out}
    for fid, (prov, prefix, tools, vision, json_mode, in_c, out_c) in flagship.items():
        if fid in existing_ids:
            continue
        # Inherit deprecation_date from any model_cost entry whose stripped id
        # matches this alias. If any of them is dead, treat the alias as dead.
        flagship_dep = _flagship_deprecation(model_cost, fid)
        if _is_obviously_dead({"deprecation_date": flagship_dep}):
            continue
        out.append(CatalogModel(
            id=fid, provider=prov, litellm_prefix=prefix,
            supports_tools=tools, supports_vision=vision,
            supports_json_mode=json_mode,
            input_cost_per_token=in_c, output_cost_per_token=out_c,
            deprecation_date=flagship_dep,
        ))

    out.sort(key=lambda m: (m.provider, m.id))
    return out


def _flagship_deprecation(model_cost: dict, fid: str) -> str | None:
    """Find the earliest deprecation_date among model_cost entries matching `fid`.

    A flagship alias like `claude-3-5-sonnet-latest` is a virtual name we add on
    top of whatever the provider currently calls the latest version. If the
    underlying versions have all been retired, the alias should be retired too.
    Returns the earliest ISO date string found, or None if no match has one.
    """
    earliest: str | None = None
    for raw, meta in model_cost.items():
        if not isinstance(meta, dict):
            continue
        if _strip_prefix(raw) != fid:
            continue
        dep = meta.get("deprecation_date")
        if not isinstance(dep, str) or not dep:
            continue
        try:
            date.fromisoformat(dep)
        except ValueError:
            continue
        if earliest is None or dep < earliest:
            earliest = dep
    return earliest


# Tiny fallback used when litellm isn't importable.
_STATIC_FALLBACK: list[CatalogModel] = [
    CatalogModel("gpt-4o", "openai", "openai/", True, True, True, 2.5e-6, 1e-5),
    CatalogModel("gpt-4o-mini", "openai", "openai/", True, True, True, 1.5e-7, 6e-7),
    CatalogModel("claude-3-5-sonnet-latest", "anthropic", "anthropic/", True, True, False, 3e-6, 1.5e-5),
    CatalogModel("claude-3-5-haiku-latest", "anthropic", "anthropic/", True, False, False, 8e-7, 4e-6),
    CatalogModel("gemini-1.5-pro", "google", "gemini/", True, True, True, 1.25e-6, 5e-6),
    CatalogModel("gemini-1.5-flash", "google", "gemini/", True, True, True, 7.5e-8, 3e-7),
]


CATALOG: list[CatalogModel] = _build_catalog_from_litellm()
CATALOG_BY_ID: dict[str, CatalogModel] = {m.id: m for m in CATALOG}
PROVIDERS_TO_MODELS: dict[str, list[CatalogModel]] = {}
for _m in CATALOG:
    PROVIDERS_TO_MODELS.setdefault(_m.provider, []).append(_m)

# Merge supplemental entries for O2-hosted models not in LiteLLM's catalog.
# Added to CATALOG/CATALOG_BY_ID only — NOT to PROVIDERS_TO_MODELS — so
# build_deployments's local-provider loop (which reads PROVIDERS_TO_MODELS)
# won't create deployments with O2-style dotted IDs against a direct provider
# endpoint (Anthropic, OpenAI, etc.) that may not accept them.
try:
    from packages.litellm_adapter.hosted_catalog import HOSTED_CATALOG_SUPPLEMENT as _HCS
    for _row in _HCS:
        _id, _prov, _prefix, _tools, _vis, _json, _in, _out = _row
        if _id not in CATALOG_BY_ID:
            _sm = CatalogModel(
                id=_id, provider=_prov, litellm_prefix=_prefix,
                supports_tools=_tools, supports_vision=_vis,
                supports_json_mode=_json,
                input_cost_per_token=_in, output_cost_per_token=_out,
            )
            CATALOG.append(_sm)
            CATALOG_BY_ID[_id] = _sm
except ImportError:
    pass


def all_model_ids() -> list[str]:
    return list(CATALOG_BY_ID.keys())


def models_for_provider(provider: str) -> list[CatalogModel]:
    return PROVIDERS_TO_MODELS.get(provider, [])
