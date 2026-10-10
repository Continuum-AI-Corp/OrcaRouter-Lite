"""Traces whose parked obligation has been folded into the spend counter.

A memory hold is process-local but the park ledger is shared: worker A can
hold trace T while worker B folds T's durable row and deletes it. Without a
durable record of that fold, A's next pre-check re-files the hold as a fresh
row and the same obligation is billed a second time. A tombstone row, written
in the same transaction that billed the park row, makes "already folded"
durable: re-filing a tombstoned trace drops the hold instead of re-inserting
it, and pending spend stops counting it.

One row per fully-folded trace. A trimmed row keeps its remainder under the
same trace and is not tombstoned — the remainder is still owed.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base, TimestampMixin, UUIDMixin


class BudgetFolded(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "budget_folded"

    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    api_key_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    microcents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Same resolution concern as BudgetPark.created_at: tombstones are only
    # ever read by trace_id, but keep the stamp precise anyway.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
