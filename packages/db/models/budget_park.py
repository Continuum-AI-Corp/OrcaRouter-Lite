"""Unsettled budget obligations — delivered spend the ledger never recorded.

A settlement that gives up after every retry leaves a delivered cost with no
record anywhere: the log row and the charge are one transaction, so both roll
back and `spent_microcents` never moves. The obligation is parked here, one row
per settlement, so it outlives the process that lost it and is visible to every
worker behind the same database.

Rows are keyed by the settlement's `trace_id`, which makes every park write
idempotent: a commit that applied but whose ack was lost retries into the same
primary key instead of recording the obligation twice. A fold that bills a row
either deletes it or shrinks it to what the cap could not absorb, in the same
transaction that moves `spent_microcents`, so the obligation is never both
parked and billed, and never neither.
"""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base, TimestampMixin, UUIDMixin


class BudgetPark(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "budget_parks"

    trace_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    api_key_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    microcents: Mapped[int] = mapped_column(BigInteger, nullable=False)
