"""In-flight spend reservations for the budget cap.

The cap has to be checked before the upstream call, but the real cost
is only known after. So a request reserves its worst case up front and
the reservation is dropped once the spend is logged.

A new table (not a new column on api_keys) on purpose: `create_all`
creates missing tables on an existing database, but never adds columns
or indexes to one that's already there.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from packages.db.models.base import Base


class BudgetHold(Base):
    __tablename__ = "budget_holds"
    __table_args__ = (Index("ix_budget_holds_key_created", "api_key_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    api_key_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reserve_microcents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
