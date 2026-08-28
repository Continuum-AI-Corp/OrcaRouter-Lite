"""Quality scoring endpoints — backs the dashboard's Quality page.

Surface area:
  GET    /v1/quality                    — full scored-model table + index status
  POST   /v1/quality/refresh            — force-refresh the AA cache
  GET    /v1/quality/auto-preview       — live preview of which model auto would
                                          pick now under the current strategy
  GET    /v1/quality/overrides          — list manual overrides
  PUT    /v1/quality/overrides/{model_id} — set a manual override
  DELETE /v1/quality/overrides/{model_id} — remove an override (revert to AA)

The dashboard uses these to give the operator transparency over (and
control of) the routing decisions the `quality` strategy makes. AA scores
alone aren't always right for every team — overrides let a developer
encode their own evals on top.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import router_cache
from app._time_util import iso_utc
from app.auto_routing import (
    choose_auto_model,
    litellm_routing_strategy,
)
from app.cache_invalidation_bus import broadcast_metrics_cache_invalidation
from app.deps import get_db, get_key_context
from app.quality_scores import (
    fetch_aa_index,
    load_overrides,
    resolve_model_metrics,
)
from packages.auth.guards import require_unrestricted
from packages.auth.types import KeyContext
from packages.db.models.quality_score_override import QualityScoreOverride
from packages.litellm_adapter.catalog import CATALOG, CATALOG_BY_ID

router = APIRouter(prefix="/v1/quality", tags=["quality"])


def _blended_cost(m) -> float:
    """Match auto_routing's blended cost formula (kept private so we don't
    leak the formula into the public surface)."""
    return 0.3 * m.input_cost_per_token + 0.7 * m.output_cost_per_token


def _serialize_aa_index(idx) -> dict[str, Any]:
    """Project a QualityIndex into a JSON-friendly status block.

    `QualityIndex.fetched_at` is per-process monotonic time and is
    re-anchored to "now" whenever the index is loaded from the DB
    snapshot, so it's not a meaningful wall-clock value to surface to
    clients. The dashboard uses `raw_count` / `matched_count` for
    freshness signal; the `source` flag distinguishes live vs stale
    (in-process) vs stale (DB).

    `matched_count` is the union (catalog IDs covered by ANY axis), so
    the dashboard's "X of Y AA models indexed" string still reads as a
    single useful number. `matched_count_breakdown` exposes the per-axis
    counts for callers that want to distinguish quality vs latency
    coverage.
    """
    return {
        "source": idx.source,
        "raw_count": idx.raw_count,
        "matched_count": idx.matched_count,
        "matched_count_breakdown": {
            "quality": idx.matched_count_quality,
            "tps": idx.matched_count_tps,
            "ttft": idx.matched_count_ttft,
        },
        "configured": idx.source != "missing-key",
    }


@router.get("")
async def quality_status(
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Full table of catalog models with their effective quality scores.

    Each row carries:
      - id, provider, blended_cost (per-token, blended 0.3/0.7 in/out)
      - aa_score (from Artificial Analysis, may be None)
      - manual_score (operator override, may be None)
      - effective_score (manual if set, else aa_score, else None)
      - capable_for_chat (always True here — catalog is filtered to chat)
      - deployable (whether a configured provider key covers this model)

    Also includes the AA index status (configured? matched count? source?).
    """
    aa = await fetch_aa_index(db=db, workspace_id=str(kc.workspace_id))
    overrides = await load_overrides(db, str(kc.workspace_id))

    # Build the deployable set from the live router cache.
    client = await router_cache.get_router(db)
    deployable: set[str] = {
        d.model_name for d in getattr(client, "_deployments", []) or []
    }

    rows: list[dict] = []
    for m in CATALOG:
        aa_score = aa.scores.get(m.id)
        manual_score = overrides.get(m.id)
        effective = manual_score if manual_score is not None else aa_score
        rows.append(
            {
                "id": m.id,
                "provider": m.provider,
                "blended_cost": _blended_cost(m),
                "input_cost_per_token": m.input_cost_per_token,
                "output_cost_per_token": m.output_cost_per_token,
                "aa_score": aa_score,
                "manual_score": manual_score,
                "effective_score": effective,
                # Latency metrics from AA — None when AA didn't cover this
                # model on that axis. Dashboard renders "—" for None.
                "tps": aa.tps_scores.get(m.id),
                "ttft": aa.ttft_scores.get(m.id),
                "supports_tools": m.supports_tools,
                "supports_vision": m.supports_vision,
                "supports_json_mode": m.supports_json_mode,
                "deployable": m.id in deployable,
                "deprecation_date": m.deprecation_date,
            }
        )

    # Sort by effective_score desc (None at the bottom), then by cost desc.
    rows.sort(
        key=lambda r: (
            -(r["effective_score"] if r["effective_score"] is not None else -1),
            -r["blended_cost"],
            r["id"],
        )
    )

    return {
        "aa_index": _serialize_aa_index(aa),
        "override_count": len(overrides),
        "models": rows,
        "attribution": {
            "name": "Artificial Analysis",
            "url": "https://artificialanalysis.ai",
            "shown_when": "any AA score appears in routing or the dashboard",
        },
    }


@router.post("/refresh")
async def quality_refresh(
    kc: KeyContext = Depends(get_key_context),
    _restricted: None = Depends(require_unrestricted),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force a fresh fetch of the AA Intelligence Index.

    Bypasses the 1h cache TTL AND the DB snapshot freshness check.
    Counts against the AA daily request quota (1000/day on the free
    tier) — operators with an outage or a very stale snapshot can use
    this to get back online without waiting for natural expiry.
    On AA success, the new snapshot is also persisted to the DB so the
    next process restart inherits it.

    Also drops the resolver-layer metrics cache so balanced/fastest
    routing sees the fresh values on the very next request, not after
    the 60s TTL.
    """
    aa = await fetch_aa_index(
        db=db, workspace_id=str(kc.workspace_id), force_refresh=True,
    )
    await broadcast_metrics_cache_invalidation()  # global — AA fetch refreshes all workspaces
    return {"aa_index": _serialize_aa_index(aa)}


_VALID_STRATEGIES = {"cheapest", "balanced", "fastest", "quality"}

# Human-readable scoring source per strategy + data-availability state.
# Surfaced verbatim in the dashboard preview ("scoring: ...").
#
# The two fallback labels per strategy distinguish:
#   - "*-cheapest-fallback":         AA data is configured but doesn't cover ANY
#                                     model in this request's eligible set
#                                     (deployable + capability + allowlist).
#                                     Operator likely needs to widen the
#                                     allowlist or add a manual quality override.
#   - "*-no-data-fallback":          AA data is globally unavailable (no key
#                                     configured, AA outage, no overrides).
#                                     Operator should configure AA or accept
#                                     cost-only routing.
# Both fall back to cheapest of the eligible set; differentiating in the UI
# tells the operator which knob to turn.
_SCORING_SOURCE_LABELS = {
    "balanced": "AA quality + catalog cost (50/50 normalized)",
    "balanced-cheapest-fallback": "AA covers no eligible models — fell back to cheapest",
    "balanced-no-data-fallback": "no AA quality data configured — fell back to cheapest",
    "fastest": "AA TPS + AA TTFT (50/50 normalized)",
    "fastest-cheapest-fallback": "AA covers no eligible models on TPS+TTFT — fell back to cheapest",
    "fastest-no-data-fallback": "no AA latency data configured — fell back to cheapest",
    "quality": "AA Intelligence Index + manual overrides",
    "quality-cost-fallback": "no AA quality data — using cost-as-quality proxy (legacy)",
    "cheapest": "blended cost (0.3 input + 0.7 output)",
}


@router.get("/auto-preview")
async def quality_auto_preview(
    needs: str | None = Query(
        None,
        description=(
            "Comma-separated capability requirements: 'tools', 'vision', "
            "'json_mode'. Empty for plain chat."
        ),
    ),
    strategy: str | None = Query(
        None,
        description=(
            "Override the workspace's active strategy for this preview only. "
            "Lets verification curl/tests compare all four strategies "
            "without flipping the persisted routing config. Dashboard does "
            "NOT pass this — it relies on the workspace strategy as the "
            "authoritative source to avoid race conditions during initial load."
        ),
    ),
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Show what model `model='auto'` would resolve to right now under the
    workspace's active strategy (or the `?strategy=` override, if given).

    Returns the same scoring breakdown the ranker computed, so the
    dashboard renders exactly the numbers that drove the decision (no
    DRY drift from re-implementing normalize / weight in the route).
    """
    needs_set: set[str] = (
        {n.strip() for n in needs.split(",") if n.strip()} if needs else set()
    )

    client = await router_cache.get_router(db)
    raw_strategy = getattr(client, "strategy", None)
    workspace_strategy = (
        raw_strategy if isinstance(raw_strategy, str) and raw_strategy else "balanced"
    )
    if strategy and strategy in _VALID_STRATEGIES:
        effective_strategy = strategy
    else:
        effective_strategy = workspace_strategy

    raw_preferred = getattr(client, "preferred_models", None)
    preferred_models = raw_preferred if isinstance(raw_preferred, list) else []

    deployable: set[str] = {
        d.model_name for d in getattr(client, "_deployments", []) or []
    }

    quality_scores: dict[str, float] | None = None
    tps_scores: dict[str, float] | None = None
    ttft_scores: dict[str, float] | None = None
    if effective_strategy in ("quality", "balanced", "fastest"):
        metrics = await resolve_model_metrics(
            db=db, workspace_id=str(kc.workspace_id)
        )
        quality_scores = metrics.quality_scores
        tps_scores = metrics.tps_scores
        ttft_scores = metrics.ttft_scores

    candidates, scoring = choose_auto_model(
        needs=needs_set,
        deployable=deployable,
        candidates=CATALOG,
        strategy=effective_strategy,
        preferred_models=preferred_models,
        allowlist=kc.model_allowlist,
        quality_scores=quality_scores,
        tps_scores=tps_scores,
        ttft_scores=ttft_scores,
    )

    primary = candidates[0] if candidates else None
    primary_model = CATALOG_BY_ID.get(primary) if primary else None
    primary_detail = scoring.get(primary) if primary else None

    # scoring_source: distinguish "ran the strategy as designed" vs
    # "fell back to cheapest because the data wasn't there". Helps the
    # operator interpret a primary that doesn't match their strategy
    # selection (and could indicate a missing AA key vs a too-narrow
    # allowlist that excludes everything AA covers).
    if effective_strategy == "balanced":
        if (primary_detail and primary_detail.breakdown
                and "quality" in primary_detail.breakdown):
            source_key = "balanced"
        elif quality_scores:
            # AA data is configured (and possibly covers OTHER models)
            # but no eligible model in this request has it. Operator
            # likely has an allowlist that excludes covered models.
            source_key = "balanced-cheapest-fallback"
        else:
            source_key = "balanced-no-data-fallback"
    elif effective_strategy == "fastest":
        if (primary_detail and primary_detail.breakdown
                and "tps" in primary_detail.breakdown):
            source_key = "fastest"
        elif tps_scores and ttft_scores:
            source_key = "fastest-cheapest-fallback"
        else:
            source_key = "fastest-no-data-fallback"
    elif effective_strategy == "quality":
        source_key = "quality" if quality_scores else "quality-cost-fallback"
    else:
        source_key = "cheapest"

    # Serialize ScoringDetail for JSON. dataclass with frozen=True doesn't
    # JSON-encode automatically; pull fields explicitly to keep the wire
    # format under our control (no leaky internal types).
    primary_score = primary_detail.primary_score if primary_detail else None
    primary_breakdown = primary_detail.breakdown if primary_detail else None

    return {
        "strategy": effective_strategy,
        "workspace_strategy": workspace_strategy,
        "strategy_overridden": effective_strategy != workspace_strategy,
        "litellm_routing_strategy": litellm_routing_strategy(effective_strategy),
        "needs": sorted(needs_set),
        "preferred_models": preferred_models,
        "deployable_count": len(deployable),
        "primary": primary,
        "primary_score": primary_score,
        "primary_score_breakdown": primary_breakdown,
        "primary_blended_cost": (
            _blended_cost(primary_model) if primary_model else None
        ),
        "fallbacks": candidates[1:] if len(candidates) > 1 else [],
        "fallbacks_count": max(0, len(candidates) - 1),
        "scoring_source": _SCORING_SOURCE_LABELS.get(source_key, source_key),
    }


# ── Manual overrides CRUD ─────────────────────────────────────────────


class OverrideBody(BaseModel):
    """Request shape for PUT /v1/quality/overrides/{model_id}."""

    score: float = Field(
        ..., ge=0.0, le=100.0,
        description="Operator-assigned quality score on the same 0-100 scale "
                    "as AA's Intelligence Index. Higher is better.",
    )
    note: str | None = Field(
        None, max_length=2000,
        description="Free-form rationale for the override; surfaced in the "
                    "dashboard so future operators understand the reasoning.",
    )


def _serialize_override(row: QualityScoreOverride) -> dict:
    return {
        "model_id": row.model_id,
        "score": row.score,
        "note": row.note,
        "created_at": iso_utc(row.created_at),
        "updated_at": iso_utc(row.updated_at),
    }


@router.get("/overrides")
async def list_overrides(
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = (
        await db.execute(
            select(QualityScoreOverride).where(
                QualityScoreOverride.workspace_id == str(kc.workspace_id)
            )
        )
    ).scalars().all()
    return {"overrides": [_serialize_override(r) for r in rows]}


@router.put("/overrides/{model_id}")
async def upsert_override(
    model_id: str,
    body: OverrideBody = Body(...),
    kc: KeyContext = Depends(get_key_context),
    _restricted: None = Depends(require_unrestricted),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create or update an override. Idempotent on (workspace, model_id).

    `session.merge()` is select-then-write under the hood, so two
    concurrent PUTs for the same (workspace, model) can both observe
    "row not present" and both attempt INSERT — the loser gets an
    IntegrityError. We retry once: on the retry, the row is guaranteed
    to exist, so merge() takes the UPDATE path and succeeds.

    A single retry is enough because the failure window is bounded by
    the duration of a single SELECT+INSERT — a second concurrent writer
    would have already committed by the time we re-enter.
    """
    if model_id not in CATALOG_BY_ID:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Model '{model_id}' is not in the catalog. Overrides can only "
                "be set for models the router knows about."
            ),
        )

    workspace_id = str(kc.workspace_id)

    async def _do_merge() -> QualityScoreOverride:
        row = await db.merge(QualityScoreOverride(
            workspace_id=workspace_id,
            model_id=model_id,
            score=body.score,
            note=body.note,
        ))
        await db.commit()
        await db.refresh(row)
        return row

    try:
        row = await _do_merge()
    except IntegrityError:
        # Concurrent writer beat us to the INSERT. Roll back the failed
        # transaction, then issue a direct UPDATE — the row is guaranteed
        # to exist now (the other writer committed it). UPDATE is
        # unconditionally safe even if their value is now ours; PUT
        # semantics say last-writer-wins anyway.
        await db.rollback()
        await db.execute(
            update(QualityScoreOverride)
            .where(
                QualityScoreOverride.workspace_id == workspace_id,
                QualityScoreOverride.model_id == model_id,
            )
            .values(score=body.score, note=body.note)
        )
        await db.commit()
        row = (
            await db.execute(
                select(QualityScoreOverride).where(
                    QualityScoreOverride.workspace_id == workspace_id,
                    QualityScoreOverride.model_id == model_id,
                )
            )
        ).scalar_one()
    # Drop the resolver cache so balanced + quality routing see the new
    # override on the very next request (otherwise stale up to 60s TTL).
    await broadcast_metrics_cache_invalidation(workspace_id)
    return _serialize_override(row)


@router.delete("/overrides/{model_id}", status_code=204)
async def delete_override(
    model_id: str,
    kc: KeyContext = Depends(get_key_context),
    _restricted: None = Depends(require_unrestricted),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove an override. Returns 204 even if the override didn't exist —
    the operator's intent ('no override on this model') is satisfied either
    way, no need to surface the distinction."""
    workspace_id = str(kc.workspace_id)
    await db.execute(
        delete(QualityScoreOverride).where(
            QualityScoreOverride.workspace_id == workspace_id,
            QualityScoreOverride.model_id == model_id,
        )
    )
    await db.commit()
    await broadcast_metrics_cache_invalidation(workspace_id)
