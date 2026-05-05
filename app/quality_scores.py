"""Resolve effective quality scores: AA index + manual operator overrides.

Routing layer (auto_routing.choose_auto_model) treats the merged dict as
authoritative. Manual overrides win unconditionally over AA scores;
operators use overrides when AA's coverage is missing or their own evals
disagree with AA's ranking.

This module is the single seam where the two data sources meet — keep
all merge / precedence logic here so callers (chat.py, /v1/quality
routes) consume one consistent view.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models.quality_score_override import QualityScoreOverride
from packages.litellm_adapter.catalog import CATALOG_BY_ID
from packages.litellm_adapter.quality_index import QualityIndex, get_quality_index


async def load_overrides(db: AsyncSession, workspace_id: str) -> dict[str, float]:
    """Return {model_id: score} for all manual overrides in a workspace.

    Empty dict when no overrides exist (no AA key needed for this path —
    overrides work standalone if the operator wants to bypass AA entirely).
    """
    stmt = select(QualityScoreOverride).where(
        QualityScoreOverride.workspace_id == workspace_id
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {row.model_id: float(row.score) for row in rows}


async def fetch_aa_index(
    *,
    db: AsyncSession | None = None,
    workspace_id: str = "default",
    force_refresh: bool = False,
) -> QualityIndex:
    """Thin wrapper that supplies the catalog id set to the fetcher.

    Kept here (not directly imported in chat.py) so callers don't have
    to know about CATALOG_BY_ID — separation of concerns.

    Pass `db` to opt in to DB-backed snapshot persistence (recommended
    for any real request flow); omit for unit tests of pure parsing.
    """
    return await get_quality_index(
        catalog_ids=set(CATALOG_BY_ID.keys()),
        db=db,
        workspace_id=workspace_id,
        force_refresh=force_refresh,
    )


async def resolve_quality_scores(
    *, db: AsyncSession, workspace_id: str, force_refresh_aa: bool = False
) -> dict[str, float]:
    """Build the final {model_id: score} map used by the quality strategy.

    Precedence: manual overrides > AA Intelligence Index > unscored.
    Unscored models don't appear in the dict (the resolver treats absent
    keys as score 0.0, putting them at the bottom of the quality ranking).
    """
    aa = await fetch_aa_index(
        db=db, workspace_id=workspace_id, force_refresh=force_refresh_aa,
    )
    overrides = await load_overrides(db, workspace_id)
    # Start from AA, then let overrides take precedence.
    merged = dict(aa.scores)
    merged.update(overrides)
    return merged
