"""Artificial Analysis quality scores — used to rank models in the
`quality` routing strategy.

The strategy was historically implemented as "pick the most expensive
deployable model" — a fine proxy when newer flagships cost more than
older ones. Anthropic and OpenAI broke that assumption (Opus 4.7 is
3x cheaper than Opus 4 from May 2024 yet measurably stronger), so cost
no longer tracks capability. AA's Intelligence Index is a real
benchmark-aggregator score (MMLU-Pro, GPQA, MATH, HumanEval, etc.),
updated as new models ship and stable across providers.

Three-layer cache:
  1. In-process dict (1h TTL) — fast, dies with the process
  2. DB snapshot (`quality_score_snapshots` table) — survives restart
     so a typical `docker compose down/up` doesn't burn an AA fetch
  3. AA `/api/v2/data/llms/models` (free tier, 1000 req/day) — truth

On AA failure, we serve stale from the in-process layer first, then
the DB layer (no time bound — better to serve old scores than to fall
back to cost-based, which is known wrong). Rotating the AA key
invalidates DB rows via the `api_key_hash` column so a snapshot taken
under one account doesn't get served under another.

Attribution: when scores are surfaced (dashboard, header, debug log),
display "Powered by Artificial Analysis" linking to artificialanalysis.ai
per their free-tier terms.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from packages.db.models.quality_score_snapshot import QualityScoreSnapshot

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_CACHE_TTL_SECONDS = 60 * 60          # 1h
_FETCH_TIMEOUT_SECONDS = 10.0
_STALE_GRACE_SECONDS = 24 * 60 * 60   # 24h: keep serving last good value


@dataclass(frozen=True)
class QualityIndex:
    """One AA fetch result. `scores` is keyed by our canonical model IDs."""

    scores: dict[str, float]
    fetched_at: float                 # monotonic seconds
    source: str                       # "live" | "stale-cache" | "missing-key" | "error"
    raw_count: int                    # how many AA entries were considered
    matched_count: int                # how many mapped to a known catalog ID


# Process-wide cache, keyed by API key (so swapping the key in tests
# or at runtime doesn't return stale data from a different account).
_cache: dict[str, QualityIndex] = {}


# Strip parenthetical qualifiers like "(max)", "(xhigh)", "(high)",
# "(low)", "(Non-reasoning, high)" — these mark reasoning-effort variants
# of the same underlying model. We aggregate by taking MAX score.
_QUALIFIER_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _normalize_aa_id(aa_name: str) -> str:
    """Convert an AA display name to our canonical model id form.

    Examples:
      "Claude Opus 4.7 (max)"          -> "claude-opus-4-7"
      "GPT-5.5 (xhigh)"                -> "gpt-5-5"
      "Claude Sonnet 4.6 (max)"        -> "claude-sonnet-4-6"
      "Gemini 3.1 Pro Preview"         -> "gemini-3-1-pro-preview"
      "DeepSeek V4 Pro (Max)"          -> "deepseek-v4-pro"

    The output may not match a LiteLLM catalog id exactly; the lookup
    layer (`_match_catalog_id`) handles strip-prefix and family fallback.
    """
    s = _QUALIFIER_RE.sub("", aa_name).strip()
    s = s.lower()
    s = s.replace(" ", "-")
    s = s.replace(".", "-")
    return s


def _match_catalog_id(normalized: str, catalog_ids: set[str]) -> str | None:
    """Find a LiteLLM catalog id that matches a normalized AA name.

    Tries, in order:
      1. Exact match
      2. Match with provider prefix stripped (the catalog already
         strips prefixes at load, but be defensive)
      3. Family match: any catalog id that starts with `normalized + "-"`
         (covers the case where AA gives a base name and the catalog
         has dated/versioned variants like "claude-opus-4-7-20260416")

    Returns the first matching catalog id, or None.
    """
    if normalized in catalog_ids:
        return normalized
    bare = normalized.split("/", 1)[-1] if "/" in normalized else normalized
    if bare in catalog_ids:
        return bare
    # Family match — pick the longest suffix-extended id that starts with
    # our normalized base. Stable order via sort so test runs are reproducible.
    family_prefix = bare + "-"
    candidates = [c for c in catalog_ids if c.startswith(family_prefix)]
    if candidates:
        return sorted(candidates)[0]
    return None


def _build_score_map(aa_payload: list[dict[str, Any]], catalog_ids: set[str]) -> tuple[dict[str, float], int, int]:
    """Project AA's response into {our_catalog_id: max_score}.

    AA may include the same base model multiple times under different
    reasoning-effort qualifiers — we keep the highest score per
    canonical catalog id. Returns (scores, raw_count, matched_count).
    """
    accum: dict[str, float] = {}
    raw_count = 0
    matched_count = 0

    for entry in aa_payload:
        if not isinstance(entry, dict):
            continue
        raw_count += 1
        # AA exposes display names in the `name` field. Some entries may
        # also have a `slug` or `id`; prefer `name` since it matches the
        # leaderboard the operator sees.
        name = entry.get("name") or entry.get("slug") or entry.get("id")
        if not isinstance(name, str) or not name:
            continue
        evals = entry.get("evaluations") or {}
        score = evals.get("artificial_analysis_intelligence_index")
        if score is None or not isinstance(score, (int, float)):
            continue

        normalized = _normalize_aa_id(name)
        catalog_id = _match_catalog_id(normalized, catalog_ids)
        if catalog_id is None:
            continue

        prior = accum.get(catalog_id)
        if prior is None or score > prior:
            accum[catalog_id] = float(score)
            if prior is None:
                matched_count += 1

    return accum, raw_count, matched_count


class _AAFetchUnusable(Exception):
    """Raised when an AA fetch returns nothing usable — schema mismatch,
    empty data array, or all entries unmatched. Distinct from a transport
    error so the caller can route it through the same stale-fallback path
    instead of persisting an empty score map over a known-good snapshot.
    """


async def _fetch_remote(url: str, api_key: str, timeout: float = _FETCH_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    """Single AA request. Tests can mock httpx at the transport boundary.

    Returns the raw `data` array. Raises `_AAFetchUnusable` on schema
    mismatch (body isn't a list and isn't a `{data: list}` wrapper) so the
    caller falls back to stale data rather than persisting `{}` and
    poisoning the DB snapshot. Network/HTTP errors propagate as-is.
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url, headers={"x-api-key": api_key, "Accept": "application/json"})
        r.raise_for_status()
        body = r.json()
    if isinstance(body, dict):
        # AA wraps the list under "data" per their schema.
        data = body.get("data")
        if isinstance(data, list):
            return data
        # Some endpoints return the bare list at top level; accept both.
    if isinstance(body, list):
        return body
    raise _AAFetchUnusable(
        f"AA response shape not recognized (expected list or {{data: list}}, "
        f"got {type(body).__name__})"
    )


def _api_key_hash(api_key: str) -> str:
    """sha256(key)[:16] — used as cache key in-memory and in the DB
    snapshot row. Same hash → same logical AA account; different hash →
    operator rotated keys, snapshots from before the rotation are stale
    by definition."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class _LoadedSnapshot:
    """A DB-loaded snapshot. Carries wall-clock age so the freshness
    check at the call site doesn't mix monotonic and wall-clock times."""
    scores: dict[str, float]
    source: str
    raw_count: int
    matched_count: int
    wall_age_seconds: float   # how long ago the row was written, per the DB clock


async def _load_db_snapshot(
    db: "AsyncSession", workspace_id: str, api_key_hash: str
) -> _LoadedSnapshot | None:
    """Read the most recent persisted snapshot for this workspace + key.

    Returns None on miss, JSON parse failure, or any DB error — callers
    treat absent snapshot as "fall through to AA fetch". We never let a
    DB hiccup take down quality routing.

    Wall-clock age is computed at load time using the DB's own `updated_at`
    column. We don't store `time.monotonic()` to the DB because the
    monotonic clock is per-process — a value saved by process A is
    meaningless when read by process B (would always look fresh, defeating
    the TTL).
    """
    from sqlalchemy import select
    try:
        row = (
            await db.execute(
                select(QualityScoreSnapshot).where(
                    QualityScoreSnapshot.workspace_id == workspace_id,
                    QualityScoreSnapshot.api_key_hash == api_key_hash,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        scores = json.loads(row.scores_json)
        if not isinstance(scores, dict):
            return None
        # Compute wall-clock age. `updated_at` is server-default `func.now()`
        # so it's UTC on both SQLite and Postgres; coerce naive (SQLite) to
        # UTC for consistent arithmetic.
        wall_now = datetime.now(timezone.utc)
        row_ts = row.updated_at
        if row_ts.tzinfo is None:
            row_ts = row_ts.replace(tzinfo=timezone.utc)
        age = max(0.0, (wall_now - row_ts).total_seconds())
        return _LoadedSnapshot(
            scores={k: float(v) for k, v in scores.items()},
            source=row.source,
            raw_count=int(row.raw_count),
            matched_count=int(row.matched_count),
            wall_age_seconds=age,
        )
    except Exception:
        return None


async def _save_db_snapshot(
    db: "AsyncSession", workspace_id: str, api_key_hash: str, idx: QualityIndex
) -> None:
    """Upsert the snapshot for this workspace + key. Never raises —
    persisting is best-effort; the in-process cache is still the
    authoritative source for the current request.

    Uses `session.merge()` for the upsert: portable across SQLite /
    Postgres / MySQL, race-safe under multi-worker fan-out (vs the
    select-then-insert pattern which would IntegrityError when two
    workers fetch AA simultaneously and both try to insert).
    """
    try:
        scores_json = json.dumps(idx.scores, separators=(",", ":"))
        # `merge` syncs a detached/new instance with whatever is in the DB,
        # keyed by primary key. Inserts when missing, updates when present.
        # Works identically across all SQLAlchemy-supported dialects.
        # `updated_at` is set by the DB's `onupdate=func.now()` trigger —
        # we don't pass it from app code, so the wall-clock timestamp
        # always comes from the same authoritative source (the DB).
        await db.merge(QualityScoreSnapshot(
            workspace_id=workspace_id,
            api_key_hash=api_key_hash,
            source=idx.source,
            raw_count=idx.raw_count,
            matched_count=idx.matched_count,
            scores_json=scores_json,
        ))
        await db.commit()
    except Exception:
        # Never let a write failure kill the request path. The in-process
        # cache still has the fresh value; we'll retry the persist on the
        # next refresh.
        try:
            await db.rollback()
        except Exception:
            pass


async def get_quality_index(
    *,
    catalog_ids: set[str],
    db: "AsyncSession | None" = None,
    workspace_id: str = "default",
    force_refresh: bool = False,
) -> QualityIndex:
    """Return the current AA score map for our catalog.

    Read order:
      1. In-process cache (1h TTL) — fastest, single-process scope.
      2. DB snapshot (`quality_score_snapshots`) — survives restart.
         Only consulted if `db` is supplied; tests of pure parsing logic
         pass `db=None` and skip this layer.
      3. AA `/api/v2/data/llms/models` — fresh truth, 1000 req/day quota.

    Write order on AA success: in-process cache + DB snapshot (best-effort).

    On AA failure: serve stale from in-process (within 24h grace), then
    from DB (no upper bound — old data is better than no data here).

    `catalog_ids` is the set of model ids we're willing to score —
    typically `set(CATALOG_BY_ID.keys())`. Pass it in (rather than
    importing) so tests can supply a synthetic catalog without dragging
    in litellm.
    """
    from app.config import get_settings

    s = get_settings()
    api_key = s.artificial_analysis_api_key
    if not api_key:
        return QualityIndex(scores={}, fetched_at=0.0, source="missing-key",
                             raw_count=0, matched_count=0)

    url = s.artificial_analysis_models_url
    key_hash = _api_key_hash(api_key)
    now = time.monotonic()

    # Layer 1: in-process cache.
    if not force_refresh:
        cached = _cache.get(key_hash)
        if cached is not None and (now - cached.fetched_at) < _CACHE_TTL_SECONDS:
            return cached

    # Layer 2: DB snapshot (only if db session provided). Freshness is
    # checked via wall-clock age (computed in `_load_db_snapshot` from
    # the DB's `updated_at`), not monotonic — see `_LoadedSnapshot`.
    db_snapshot: _LoadedSnapshot | None = None
    if db is not None:
        db_snapshot = await _load_db_snapshot(db, workspace_id, key_hash)
        if (
            not force_refresh
            and db_snapshot is not None
            and db_snapshot.wall_age_seconds < _CACHE_TTL_SECONDS
        ):
            # Promote DB row into in-process cache. The in-process layer
            # uses monotonic time, so set `fetched_at = now` (treats this
            # request as the start of a fresh in-process TTL window). Net
            # effect: cross-restart freshness can extend by up to 1h
            # beyond the original wall-clock TTL — acceptable in exchange
            # for a cold-start AA quota saved.
            promoted = QualityIndex(
                scores=db_snapshot.scores,
                fetched_at=now,
                source=db_snapshot.source,
                raw_count=db_snapshot.raw_count,
                matched_count=db_snapshot.matched_count,
            )
            _cache[key_hash] = promoted
            return promoted

    # Layer 3: fetch AA.
    try:
        raw = await _fetch_remote(url, api_key)
        if not raw:
            # Empty array from AA — almost always a transient outage or
            # a quota-exceeded response that still returned 200. Don't
            # let it overwrite a good DB snapshot with `{}`; route through
            # the stale-fallback path instead.
            raise _AAFetchUnusable("AA returned empty data array")
        scores, raw_count, matched_count = _build_score_map(raw, catalog_ids)
        if matched_count == 0:
            # AA gave us data but none of it mapped to our catalog. This
            # signals a normalization regression (AA renamed everything)
            # rather than a healthy fetch — persisting `{}` would silently
            # disable quality routing on the next restart. Fall back to
            # stale instead.
            raise _AAFetchUnusable(
                f"AA returned {raw_count} entries but 0 mapped to catalog"
            )
        idx = QualityIndex(
            scores=scores, fetched_at=now, source="live",
            raw_count=raw_count, matched_count=matched_count,
        )
        _cache[key_hash] = idx
        if db is not None:
            await _save_db_snapshot(db, workspace_id, key_hash, idx)
        return idx
    except Exception:
        # Stale fallbacks, in order of freshness.
        cached = _cache.get(key_hash)
        if cached is not None and (now - cached.fetched_at) < _STALE_GRACE_SECONDS:
            return QualityIndex(
                scores=cached.scores, fetched_at=cached.fetched_at,
                source="stale-cache",
                raw_count=cached.raw_count, matched_count=cached.matched_count,
            )
        if db_snapshot is not None:
            # DB row is older than the in-process TTL but we serve it
            # anyway — better than disabling quality routing entirely.
            # `source="stale-db"` lets the dashboard show the operator
            # they're on stale data; no upper bound on age here because
            # the alternative (cost-based) is known wrong, not just stale.
            return QualityIndex(
                scores=db_snapshot.scores,
                fetched_at=now,  # we just learned this from DB; re-anchor in-process
                source="stale-db",
                raw_count=db_snapshot.raw_count,
                matched_count=db_snapshot.matched_count,
            )
        return QualityIndex(scores={}, fetched_at=now, source="error",
                             raw_count=0, matched_count=0)


def reset_cache() -> None:
    """Clear the in-process cache. Call from test fixtures."""
    _cache.clear()
