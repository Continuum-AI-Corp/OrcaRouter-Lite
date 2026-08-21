"""Per-key spend lookup used to enforce `ApiKey.budget_limit_cents`.

Semantics: `budget_limit_cents` is a lifetime cap on the key's billable
spend — request-log rows with `status_code < 400`. 1 cent = 10,000
microcents (1 USD = 1,000,000 microcents, matching chat.py's cost math).

Kept free of FastAPI imports so it stays unit-testable and reusable from
non-HTTP contexts (background jobs, CLI minting tools).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models.request_log import RequestLog

MICROCENTS_PER_CENT = 10_000


async def get_lifetime_spend_microcents(
    session: AsyncSession, api_key_id: str
) -> int:
    """Sum of billable (status < 400) spend ever recorded for this key."""
    stmt = select(func.coalesce(func.sum(RequestLog.cost_microcents), 0)).where(
        RequestLog.api_key_id == api_key_id,
        RequestLog.is_deleted == 0,
        RequestLog.status_code < 400,
    )
    return int((await session.execute(stmt)).scalar_one())


def budget_exceeded(spend_microcents: int, budget_limit_cents: int) -> bool:
    return spend_microcents >= budget_limit_cents * MICROCENTS_PER_CENT
