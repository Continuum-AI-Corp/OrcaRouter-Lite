"""Manual overrides for the AA-driven quality routing scores.

The dashboard's Quality page lets the operator pin a custom score for any
catalog model — useful when AA's benchmark coverage is missing or stale,
or when the operator's own evals disagree with AA's ranking. The routing
layer treats overrides as authoritative: manual > AA > unscored.

One row per (workspace_id, model_id). Lite is single-workspace today, but
the composite key keeps the table forward-compatible with multi-workspace
deployments.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base


class QualityScoreOverride(Base):
    __tablename__ = "quality_score_overrides"

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), primary_key=True, nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(200), primary_key=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # Free-form note from the operator explaining why they overrode the score.
    # Surfaced in the dashboard so future-you remembers what past-you was thinking.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
