"""Resolve effective quality + latency metrics: AA index + manual operator
overrides + a 60s in-process cache to keep balanced/fastest off the
DB-query hot path.

Routing layer (auto_routing.choose_auto_model) treats the merged maps
as authoritative. Manual overrides win unconditionally over AA quality
scores; operators use overrides when AA's coverage is missing or their
own evals disagree with AA's ranking. TPS / TTFT have no override
concept (they're benchmark medians, not opinions).

This module is the single seam where data sources meet — keep all
merge / precedence logic here so callers (chat.py, /v1/quality routes)
consume one consistent view.

In-process metrics cache: balanced is the default routing strategy, so
every `model="auto"` request walks this path. Without a cache, each
request would do a DB lookup for overrides even when the AA payload
itself is hot. We cache the merged ResolvedMetrics for 60 seconds keyed
by (workspace_id, AA-key-hash); override PUT/DELETE and quality refresh
routes invalidate the relevant entries so operator changes are visible
immediately, not after a TTL.

Multi-worker note: cache is module-local. On a single worker (the Lite
default) the mutation route dropping its own entry is enough. Under
multiple uvicorn workers / k8s replicas, cross-worker invalidation is
handled by app.cache_invalidation_bus (Redis pub/sub) when REDIS_URL is
set — mutation routes call broadcast_metrics_cache_invalidation() so
siblings drop their entries too instead of waiting out the TTL. Without
REDIS_URL a sibling still serves stale until its own TTL expires.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

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


@dataclass(frozen=True)
class ResolvedMetrics:
    """Effective metrics after merging AA + manual overrides.

    `quality_scores` carries the override-merged map (operator wins).
    TPS / TTFT are AA passthrough — there's no operator-override concept
    for benchmark latency medians.
    """
    quality_scores: dict[str, float]
    tps_scores: dict[str, float]
    ttft_scores: dict[str, float]


# Module-level cache, keyed by (workspace_id, aa_key_hash). 60s TTL.
# Mirrors the router_cache.py pattern (process-local, hot-path).
_metrics_cache: dict[tuple[str, str], tuple[ResolvedMetrics, float]] = {}
_METRICS_TTL = 60.0  # seconds


def _hash_aa_key(api_key: str) -> str:
    """sha256(key)[:16] — stable per-account identity. Empty string when
    no AA key configured (all unconfigured workspaces share that hash,
    which is fine because workspace_id is also part of the cache key)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


async def resolve_model_metrics(
    *,
    db: AsyncSession,
    workspace_id: str,
    force_refresh: bool = False,
) -> ResolvedMetrics:
    """Return the merged metrics for the given workspace.

    Cache hit: a single dict lookup, microseconds. Cache miss: at most
    one AA fetch (often itself cached at the AA layer) + one DB query
    for overrides. The downstream router calls this on every
    `model="auto"` request — the cache exists so default `balanced`
    routing doesn't re-query the DB once per request.

    Cache invalidation: see `invalidate_metrics_cache()`. Hooked from
    override PUT/DELETE and quality refresh routes so operator
    mutations are visible without waiting for TTL.
    """
    from app.config import get_settings

    aa_key_hash = _hash_aa_key(get_settings().artificial_analysis_api_key or "")
    cache_key = (workspace_id, aa_key_hash)
    if not force_refresh:
        cached = _metrics_cache.get(cache_key)
        if cached is not None and (time.monotonic() - cached[1]) < _METRICS_TTL:
            return cached[0]

    aa = await fetch_aa_index(
        db=db, workspace_id=workspace_id, force_refresh=force_refresh,
    )
    overrides = await load_overrides(db, workspace_id)
    quality = dict(aa.scores)
    quality.update(overrides)   # override 优先
    metrics = ResolvedMetrics(
        quality_scores=quality,
        tps_scores=dict(aa.tps_scores),
        ttft_scores=dict(aa.ttft_scores),
    )
    _metrics_cache[cache_key] = (metrics, time.monotonic())
    return metrics


def invalidate_metrics_cache(workspace_id: str | None = None) -> None:
    """Drop cache entries.

    `workspace_id=None` clears everything (use when AA fetch refreshes
    globally — a new fetch could change scores for any workspace's
    routing). Otherwise drops only entries for the given workspace
    across all AA-key-hashes (covers the case where the operator
    rotated the AA key without us noticing the hash change).
    """
    if workspace_id is None:
        _metrics_cache.clear()
        return
    for key in list(_metrics_cache):
        if key[0] == workspace_id:
            del _metrics_cache[key]


def reset_metrics_cache() -> None:
    """Clear the in-process metrics cache. Call from test fixtures."""
    _metrics_cache.clear()
