"""Per-key spend lookup used to enforce `ApiKey.budget_limit_cents`.

Semantics: `budget_limit_cents` is a lifetime cap on the key's total
spend — sum of `cost_microcents` for all non-deleted request-log rows.
1 cent = 10,000 microcents (1 USD = 1,000,000 microcents, matching
chat.py's cost math).

Rows are counted regardless of HTTP status because the streaming path
records billable token usage even when the final status is 499 (client
disconnect, chat.py:596) or 503 (mid-stream upstream failure,
chat.py:646); filtering on `status_code < 400` would exclude those and
make the cap bypassable by closing the stream early after reading the
usage chunk.

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
    """Sum of all non-deleted spend ever recorded for this key.

    Counts every row with `cost_microcents` regardless of `status_code`
    so that streaming disconnect (499) and mid-stream upstream failure
    (503) costs — which already incurred provider billing — are not
    excluded from the budget. Failed requests with zero cost contribute
    nothing to the sum regardless.
    """
    stmt = select(func.coalesce(func.sum(RequestLog.cost_microcents), 0)).where(
        RequestLog.api_key_id == api_key_id,
        RequestLog.is_deleted == 0,
    )
    return int((await session.execute(stmt)).scalar_one())


def budget_exceeded(spend_microcents: int, budget_limit_cents: int) -> bool:
    return spend_microcents >= budget_limit_cents * MICROCENTS_PER_CENT
