"""The models a picker can offer (H5), in four groups.

One list for every place the app lets the user choose a model (an agent's
main and background models, Routing's preferred models, setup): what the
user's own keys reach, what runs on this computer, OrcaRouter's free models
and its paid ones, with prices per million tokens from the catalog the
engine ships. Nothing here calls the network.

`available` says whether choosing the model would work right now: OrcaRouter
models need an OrcaRouter key, and paid ones also need "Use paid models"
(`hosted_models == "all"`); a local model needs its runtime running and auto
allowed to use it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from packages.desktop import local_models
from packages.litellm_adapter.catalog import CATALOG_BY_ID, CatalogModel, models_for_provider
from packages.litellm_adapter.hosted_catalog import FREE_HOSTED_MODELS, HOSTED_MODELS
from packages.litellm_adapter.provider_registry import PROVIDERS

HOSTED = "orcarouter"
DEFAULT_LIMIT = 80
MAX_LIMIT = 1000
LABELS = {
    "yours": "Your keys",
    "local": "On this computer",
    "free": "Free on OrcaRouter",
    "paid": "Paid on OrcaRouter",
}
# Hosted models that don't answer chat (images, robotics) aren't offered.
_NOT_CHAT = ("-image", "imagine", "robotics")
_ORDER = {p.id: i for i, p in enumerate(PROVIDERS)}


@dataclass(frozen=True)
class PickerInputs:
    own_providers: frozenset[str]
    runtimes: tuple[local_models.Runtime, ...]
    local_selection: list[str] | None
    hosted_configured: bool
    hosted_models: str  # "free" | "all"


def _per_m(cost: float | None) -> float | None:
    return round(cost * 1_000_000, 6) if cost else None


def _row(model_id: str, name: str, provider: str, meta: CatalogModel | None, *, free: bool, available: bool) -> dict:
    return {
        "id": model_id,
        "name": name,
        "provider": provider,
        "input_per_m": 0.0 if free else _per_m(meta.input_cost_per_token if meta else None),
        "output_per_m": 0.0 if free else _per_m(meta.output_cost_per_token if meta else None),
        "free": free,
        "available": available,
        "tools": bool(meta and meta.supports_tools),
        "vision": bool(meta and meta.supports_vision),
    }


def _price_key(row: dict) -> float:
    if row["input_per_m"] is None and row["output_per_m"] is None:
        return float("inf")
    return (row["input_per_m"] or 0) + (row["output_per_m"] or 0)


def _hosted_meta(bare_id: str) -> CatalogModel | None:
    """The catalog entry for a hosted model, under its own spelling or the
    vendor's (OrcaRouter writes claude-sonnet-4.6 for claude-sonnet-4-6)."""
    return CATALOG_BY_ID.get(bare_id) or CATALOG_BY_ID.get(bare_id.replace(".", "-"))


def yours(providers: Iterable[str]) -> list[dict]:
    seen: set[str] = set()
    rows = []
    for provider in providers:
        if provider == HOSTED:
            continue
        for m in models_for_provider(provider):
            if m.id in seen:
                continue
            seen.add(m.id)
            rows.append(_row(m.id, m.id, provider, m, free=False, available=True))
    rows.sort(key=lambda r: (_ORDER.get(r["provider"], len(_ORDER)), r["provider"], _price_key(r), r["id"]))
    return rows


def local(runtimes: Iterable[local_models.Runtime], selection: list[str] | None) -> list[dict]:
    rows = []
    for rt in runtimes:
        allowed = {m.id for m in local_models.enabled(list(rt.models), selection)}
        for m in rt.models:
            rows.append(_row(m.id, m.name, local_models.PROVIDER, local_models.catalog_entry(m), free=True,
                             available=rt.running and m.id in allowed))
    return rows


def free(hosted_configured: bool) -> list[dict]:
    return [
        _row(wire, wire.split("/", 1)[1] if not wire.startswith(f"{HOSTED}/") else wire, HOSTED,
             CATALOG_BY_ID.get(wire), free=True, available=hosted_configured)
        for wire in FREE_HOSTED_MODELS
    ]


def paid(hosted_configured: bool, hosted_models: str) -> list[dict]:
    free_wire = set(FREE_HOSTED_MODELS)
    rows = []
    for vendor, bare in HOSTED_MODELS:
        if f"{vendor}/{bare}" in free_wire or any(mark in bare for mark in _NOT_CHAT):
            continue
        rows.append(_row(bare, bare, HOSTED, _hosted_meta(bare), free=False,
                         available=hosted_configured and hosted_models == "all"))
    rows.sort(key=lambda r: (_price_key(r), r["id"]))
    return rows


def _matches(row: dict, q: str) -> bool:
    return q in row["id"].lower() or q in row["name"].lower()


def groups(inputs: PickerInputs, *, q: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Every group, each filtered by `q` (case-insensitive) and cut to `limit`
    models; `total` says how many matched before the cut."""
    order = sorted(inputs.own_providers, key=lambda p: (_ORDER.get(p, len(_ORDER)), p))
    lists = {
        "yours": yours(order),
        "local": local(inputs.runtimes, inputs.local_selection),
        "free": free(inputs.hosted_configured),
        "paid": paid(inputs.hosted_configured, inputs.hosted_models),
    }
    needle = (q or "").strip().lower()
    out = []
    for gid, rows in lists.items():
        if needle:
            rows = [r for r in rows if _matches(r, needle)]
        out.append({"id": gid, "label": LABELS[gid], "total": len(rows), "models": rows[:limit]})
    return out
