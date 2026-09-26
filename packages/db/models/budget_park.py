"""Unsettled budget obligations — delivered spend the ledger never recorded.

A settlement that gives up after every retry leaves a delivered cost with no
record anywhere: the log row and the charge are one transaction, so both roll
back and `spent_microcents` never moves. The obligation is parked here, one row
per settlement, so it outlives the process that lost it and is visible to every
worker behind the same database.

Rows are keyed by the settlement's `trace_id`, which makes every park write
idempotent: a commit that applied but whose ack was lost retries into the same
primary key instead of recording the obligation twice, and a write that fails
outright is checked for having landed anyway before the process falls back to
holding it in memory. A fold that bills a row either deletes it or shrinks it to
what the cap could not absorb, in the same transaction that moves
`spent_microcents`, and it drops the writer's memory hold for any row it fully
billed.

What that leaves is a double charge needing three faults at once — the ack lost,
the durability probe failing alongside it, and another worker folding the row
before this one retries — at which point the extra charge lands on a key that had
already breached its cap. Closing that last window means a fold leaving a tombstone
behind instead of deleting, so a re-file always collides with something; that is a
second state the queue has to drain, and it is not worth its weight here.
"""

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base, TimestampMixin, UUIDMixin


class BudgetPark(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "budget_parks"

    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    api_key_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    microcents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Overrides TimestampMixin's column, whose `server_default=func.now()` is
    # CURRENT_TIMESTAMP: one second wide on SQLite, where a recovered outage
    # re-files a whole batch of obligations in a single pre-check and every row
    # in it ties. The fold bills oldest debt first, and two workers have to
    # agree on which row the partial one is, so the stamp needs enough
    # resolution to settle that on its own instead of falling through to the
    # `trace_id` tiebreak — which is a uuid4, and so picks at random.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
