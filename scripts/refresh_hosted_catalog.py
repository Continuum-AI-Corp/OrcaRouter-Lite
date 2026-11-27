"""Regenerate packages/litellm_adapter/hosted_catalog.py from OrcaRouter.

The hosted catalog is a pinned copy of what OrcaRouter serves. When it falls
behind, requests for new models (Claude Code's default claude-opus-5-5, say)
are treated as unknown and substituted, and delisted models are still routed
to and fail. Run this to bring it up to date, then review the diff:

    ORCAROUTER_API_KEY=sk-orca-... python scripts/refresh_hosted_catalog.py

Sources: GET /v1/models (what the account can call, with endpoint types) and
GET /api/pricing (prices, context, modalities, supported parameters).
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import httpx

BASE = os.environ.get("ORCAROUTER_BASE", "https://api.orcarouter.ai").rstrip("/")
OUT = Path(__file__).resolve().parent.parent / "packages" / "litellm_adapter" / "hosted_catalog.py"

# OrcaRouter's own routers and test endpoints aren't models a user picks;
# orcarouter/free is the one exception (a free model in its own right).
_SKIP_VENDORS = {"local", "orcarouter", "orca", "kling", "typesafe"}
_KEEP = {"orcarouter/free"}
_SKIP_WORDS = ("tts", "embedding", "image", "video", "audio", "transcribe", "realtime", "search-api")
# Lite's provider names where they differ from OrcaRouter's vendor prefix.
_PROVIDER = {"grok": "xai", "z-ai": "zai"}
_PREFIX = {"anthropic": "anthropic/", "google": "gemini/", "deepseek": "deepseek/", "xai": "xai/"}


def _chat_model(m: dict) -> bool:
    mid = m["id"]
    if "/" not in mid:
        return False
    vendor = mid.split("/", 1)[0]
    if mid not in _KEEP and (vendor in _SKIP_VENDORS or any(w in mid.lower() for w in _SKIP_WORDS)):
        return False
    return "openai" in (m.get("supported_endpoint_types") or [])


def _prices(p: dict) -> tuple[float, float] | None:
    """USD per token from OrcaRouter's ratios ($2 per 1M tokens at ratio 1)."""
    if p.get("quota_type") not in (0, None):
        return None  # priced per request: auto can't rank it per token
    ratio = float(p.get("model_ratio") or 0)
    inp = ratio * 2 / 1_000_000
    return inp, inp * float(p.get("completion_ratio") or 1)


def _is_free(mid: str, p: dict | None) -> bool:
    if mid == "orcarouter/free":
        return True
    return mid.endswith("-free") and p is not None and not p.get("model_ratio") and not p.get("model_price")


def main() -> int:
    key = os.environ.get("ORCAROUTER_API_KEY")
    if not key:
        print("Set ORCAROUTER_API_KEY.", file=sys.stderr)
        return 2
    h = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=60) as c:
        models = c.get(f"{BASE}/v1/models", headers=h).raise_for_status().json()["data"]
        pricing = {p["model_name"]: p for p in c.get(f"{BASE}/api/pricing", headers=h).raise_for_status().json()["data"]}

    import litellm

    hosted: list[tuple[str, str]] = []
    seen_bare: set[str] = set()
    for m in sorted(models, key=lambda m: m["id"]):
        if not _chat_model(m):
            continue
        vendor, bare = m["id"].split("/", 1)
        if bare in seen_bare:  # model groups are bare ids: first vendor wins
            continue
        seen_bare.add(bare)
        hosted.append((vendor, bare))

    free = [f"{v}/{b}" for v, b in hosted if _is_free(f"{v}/{b}", pricing.get(f"{v}/{b}"))]

    def _free_rank(wire: str):
        p = pricing.get(wire) or {}
        params = p.get("supported_parameters") or []
        types = next((m.get("supported_endpoint_types") or [] for m in models if m["id"] == wire), [])
        # Tool use first (coding agents need it), then the most protocols, then context.
        return (wire == "orcarouter/free", "tools" not in params, -len(types), -(p.get("context_length") or 0), wire)

    free.sort(key=_free_rank)

    supplement: list[tuple] = []
    for vendor, bare in hosted:
        wire = f"{vendor}/{bare}"
        p = pricing.get(wire)
        provider = _PROVIDER.get(vendor, vendor)
        prefix = _PREFIX.get(provider, "openai/")
        if _is_free(wire, p):
            params = (p or {}).get("supported_parameters") or ["tools", "response_format"]
            # Images stay on paid models: a free model's listing may say it takes
            # images, but whether the free tier accepts them isn't verified, and
            # the app's "this request needs a paid model" path depends on it.
            supplement.append((wire, provider, prefix, "tools" in params, False, "response_format" in params, 0.0, 0.0))
            continue
        known = litellm.model_cost.get(bare) or litellm.model_cost.get(f"{prefix}{bare}")
        if known and (known.get("input_cost_per_token") or known.get("output_cost_per_token")):
            continue  # LiteLLM already prices it
        prices = _prices(p) if p else None
        if not prices or not any(prices):
            continue  # no per-token price: deployable when pinned, not ranked by auto
        params = p.get("supported_parameters") or []
        vision = "image" in (p.get("input_modalities") or [])
        supplement.append((bare, provider, prefix, "tools" in params, vision, "response_format" in params, *prices))

    OUT.write_text(_render(hosted, free, supplement), encoding="utf-8", newline="\n")
    print(f"{len(hosted)} hosted models, {len(free)} free, {len(supplement)} supplement rows -> {OUT}")
    return 0


def _render(hosted, free, supplement) -> str:
    counts: dict[str, int] = {}
    for v, _b in hosted:
        counts[v] = counts.get(v, 0) + 1
    count_line = " / ".join(f"{v} {n}" for v, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    w = max(len(repr(r[0])) for r in supplement) if supplement else 0
    lines = [
        '"""Authoritative list of OrcaRouter hosted-routable models.',
        "",
        f"Generated by scripts/refresh_hosted_catalog.py on {date.today().isoformat()} from",
        "OrcaRouter's /v1/models (chat-capable models) and /api/pricing (prices,",
        "modalities, parameters). Re-run it when OrcaRouter adds or delists models;",
        "do not edit the lists by hand.",
        "",
        f"Provider counts: {count_line}",
        "",
        "Format: (provider, bare_model_id) where provider is OrcaRouter's wire prefix",
        "and bare_model_id is what users put in model=\"...\". Wire format =",
        "f\"{provider}/{bare_id}\".",
        "",
        "HOSTED_CATALOG_SUPPLEMENT: catalog metadata for hosted models LiteLLM's",
        "model_cost table doesn't price. catalog.py merges these into CATALOG /",
        "CATALOG_BY_ID (but NOT into PROVIDERS_TO_MODELS) so auto-routing sees",
        "OrcaRouter's ids while local provider routing keeps LiteLLM's own ids.",
        "",
        "Format: (id, provider, litellm_prefix, tools, vision, json_mode,",
        "         in_$/tok, out_$/tok)",
        "Pricing: OrcaRouter's list price at generation time. Scheduling weights,",
        "not billing truth: the X-OrcaRouter-beta-usd response header (or the",
        "response's usage.cost_usd) is the per-request cost in RequestLog.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "HOSTED_MODELS: tuple[tuple[str, str], ...] = (",
        *(f"    ({v!r}, {b!r})," for v, b in hosted),
        ")",
        "",
        "# OrcaRouter's public API uses provider-qualified IDs for its zero-credit models.",
        "# Keep the normal bare model group for compatibility, and additionally expose",
        "# these exact wire IDs so OpenAI-compatible clients can copy an ID directly",
        "# from api.orcarouter.ai/v1/models into their local Lite request unchanged.",
        "HOSTED_MODEL_ALIASES: frozenset[str] = frozenset({",
        *(f"    {m!r}," for m in sorted(free)),
        "})",
        "",
        "# OrcaRouter's free models, in the order the desktop app offers them (tool use",
        "# first). They are real zero-priced models (unlike litellm's unpriced rows), so",
        "# auto may pick them, and in the app's default \"free\" mode they're the only",
        "# hosted models deployed and rank first. Each is also deployed under its bare id.",
        "FREE_HOSTED_MODELS: tuple[str, ...] = (",
        *(f"    {m!r}," for m in free),
        ")",
        "# Every name a free model is deployed under (wire id and bare id).",
        "FREE_HOSTED_NAMES: frozenset[str] = frozenset(",
        "    {*FREE_HOSTED_MODELS, *(m.split('/', 1)[1] for m in FREE_HOSTED_MODELS)}",
        ")",
        "# The free models' usable context, in tokens. OrcaRouter doesn't publish a",
        "# per-model figure; this is a conservative bound so a prompt that clearly",
        "# can't fit asks for a paid model instead of failing upstream.",
        "FREE_HOSTED_CONTEXT_TOKENS = 128_000",
        "",
        "",
        "def is_free_hosted(model: str | None) -> bool:",
        "    return bool(model) and model in FREE_HOSTED_NAMES",
        "",
        "",
        "# Supplemental catalog metadata for hosted models LiteLLM doesn't price.",
        "# Models in HOSTED_MODELS but absent here (and absent from LiteLLM) are",
        "# deployable via explicit pin but skipped by auto-routing (no cost metadata).",
        "HOSTED_CATALOG_SUPPLEMENT: tuple[tuple, ...] = (",
        *(f"    ({r[0]!r:<{w}}, {r[1]!r}, {r[2]!r}, {r[3]}, {r[4]}, {r[5]}, {r[6]:.2e}, {r[7]:.2e}),"
          for r in supplement),
        ")",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
