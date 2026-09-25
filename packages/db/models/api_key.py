"""API key model — sk-orca-* keys for the local workspace."""

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class ApiKey(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "api_keys"

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    model_allowlist: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # BIGINT (not Integer): this is the cap input, scaled by MICROCENTS_PER_CENT
    # into microcents for every comparison against `spent_microcents` below, and
    # a 32-bit int4 would ceiling a lifetime budget near 214,748 dollars.
    budget_limit_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Running lifetime spend in microcents. `spend.charge_budget` is the only
    # writer: a single atomic UPDATE adds the actual cost and refuses to let the
    # counter exceed budget_limit_cents, so the cap holds even under concurrent
    # requests for the same key. This column is the state that protocol needs —
    # a caller enforces by checking `is_exhausted` before dispatch and charging
    # after, so the cap is only as live as the paths that route through it.
    spent_microcents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0", default=0
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
