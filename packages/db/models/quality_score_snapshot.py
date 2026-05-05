"""Persisted snapshot of the most recent Artificial Analysis fetch.

Survives process restart so the operator's daily AA quota (1000/day on the
free tier) isn't burned re-fetching the same data on every boot. One row
per (workspace_id, api_key_hash) — the key hash discriminates so that
rotating the AA key invalidates the previous snapshot rather than
silently serving data fetched under a different account.

Routing layer prefers in-process cache (fast, 1h TTL), then this snapshot
(survives restart), then a fresh AA fetch. On AA outage, this snapshot
extends the stale-while-revalidate window indefinitely — the cost-based
fallback is the last resort, not the first.

Freshness is tracked via `updated_at` (wall-clock, set by the DB on
write). `time.monotonic()` is per-process and has no meaning when read
from another process — it would always look fresh, defeating the TTL.
The routing layer converts `updated_at` → wall-clock age → comparison
when loading from DB.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base


class QualityScoreSnapshot(Base):
    __tablename__ = "quality_score_snapshots"

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), primary_key=True, nullable=False
    )
    # sha256(api_key)[:16] — rotating the AA key changes this and forces a
    # fresh fetch (a snapshot from key A shouldn't be served when running
    # under key B; their model coverage / scores might differ).
    api_key_hash: Mapped[str] = mapped_column(
        String(32), primary_key=True, nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # JSON-serialized {model_id: score}. `Text` rather than dialect-specific
    # `JSON` / `JSONB` so SQLite + Postgres + MySQL behave identically
    # without driver-specific wrangling. The map is small enough (~500
    # entries × ~30 bytes = ~15KB) that searchable JSON storage is overkill.
    scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    # Wall-clock timestamp of the last fetch. Used for cross-process
    # freshness checks (monotonic time would be meaningless across
    # restarts — see module docstring). DB-managed via `func.now()` so
    # we don't have to feed the column from app code.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
