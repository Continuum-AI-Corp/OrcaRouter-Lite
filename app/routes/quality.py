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
from app.auto_routing import (
    choose_auto_model,
    litellm_routing_strategy,
)
from app.deps import get_db, get_key_context
from app.quality_scores import (
    fetch_aa_index,
    load_overrides,
    resolve_quality_scores,
)
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
    """
    return {
        "source": idx.source,
        "raw_count": idx.raw_count,
        "matched_count": idx.matched_count,
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
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force a fresh fetch of the AA Intelligence Index.

    Bypasses the 1h cache TTL AND the DB snapshot freshness check.
    Counts against the AA daily request quota (1000/day on the free
    tier) — operators with an outage or a very stale snapshot can use
    this to get back online without waiting for natural expiry.
    On AA success, the new snapshot is also persisted to the DB so the
    next process restart inherits it.
    """
    aa = await fetch_aa_index(
        db=db, workspace_id=str(kc.workspace_id), force_refresh=True,
    )
    return {"aa_index": _serialize_aa_index(aa)}


@router.get("/auto-preview")
async def quality_auto_preview(
    needs: str | None = Query(
        None,
        description=(
            "Comma-separated capability requirements: 'tools', 'vision', "
            "'json_mode'. Empty for plain chat."
        ),
    ),
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Show what model `model='auto'` would resolve to right now under the
    workspace's active strategy.

    The dashboard re-fetches this on strategy change so the operator sees
    the routing decision change live, instead of having to fire a real
    chat completion to find out.
    """
    needs_set: set[str] = (
        {n.strip() for n in needs.split(",") if n.strip()} if needs else set()
    )

    client = await router_cache.get_router(db)
    raw_strategy = getattr(client, "strategy", None)
    strategy = (
        raw_strategy if isinstance(raw_strategy, str) and raw_strategy else "balanced"
    )
    raw_preferred = getattr(client, "preferred_models", None)
    preferred_models = raw_preferred if isinstance(raw_preferred, list) else []

    deployable: set[str] = {
        d.model_name for d in getattr(client, "_deployments", []) or []
    }

    quality_scores: dict[str, float] | None = None
    if strategy == "quality":
        quality_scores = await resolve_quality_scores(
            db=db, workspace_id=str(kc.workspace_id)
        )

    candidates = choose_auto_model(
        needs=needs_set,
        deployable=deployable,
        candidates=CATALOG,
        strategy=strategy,
        preferred_models=preferred_models,
        allowlist=kc.model_allowlist,
        quality_scores=quality_scores,
    )

    primary = candidates[0] if candidates else None
    primary_model = CATALOG_BY_ID.get(primary) if primary else None

    return {
        "strategy": strategy,
        "litellm_routing_strategy": litellm_routing_strategy(strategy),
        "needs": sorted(needs_set),
        "preferred_models": preferred_models,
        "deployable_count": len(deployable),
        "primary": primary,
        "primary_score": (
            quality_scores.get(primary) if (quality_scores and primary) else None
        ),
        "primary_blended_cost": (
            _blended_cost(primary_model) if primary_model else None
        ),
        "fallbacks": candidates[1:] if len(candidates) > 1 else [],
        "fallbacks_count": max(0, len(candidates) - 1),
        "scoring_source": (
            "quality_scores"
            if (strategy == "quality" and quality_scores)
            else (
                "cost-based-fallback"
                if strategy == "quality"
                else f"strategy:{strategy}"
            )
        ),
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
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
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
    return _serialize_override(row)


@router.delete("/overrides/{model_id}", status_code=204)
async def delete_override(
    model_id: str,
    kc: KeyContext = Depends(get_key_context),
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
