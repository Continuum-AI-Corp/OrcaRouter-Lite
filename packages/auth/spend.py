"""Per-key lifetime spend tracking schema and accounting primitives for ``ApiKey.budget_limit_cents``.

This module provides the accounting schema foundation and atomic charge primitives
(part 1 of the 4-part budget subsystem; request-path enforcement is wired in #161).

The cap is a hard lifetime limit on the key's total spend, in microcents
(1 cent = 10_000 microcents; 1 USD = 1_000_000 microcents, matching chat.py's
cost math). `ApiKey.budget_limit_cents` is stored in cents, so every
`cap_microcents` argument below must be that column scaled by MICROCENTS_PER_CENT
(passing raw cents asks whether the key has spent a ten-thousandth of its budget).

Actual cost is only known after the upstream call returns, so accounting is a
single atomic ``UPDATE`` that adds the real cost and refuses to let the counter
exceed the cap::

    UPDATE api_keys SET spent_microcents = spent_microcents + :actual
    WHERE id = :id AND spent_microcents + :actual <= :cap

Concurrent requests for the same key each add their own cost atomically; only a
request whose *own* cost alone would breach the remaining budget matches zero
rows. In that case the counter is clamped to ``cap`` so the key is correctly
maxed out and the next request is rejected — fail-closed, never over-recorded.

This avoids both failure modes of a pre-claim design: it never records spend
past the cap (no over-spend), and it does not reserve the whole remaining budget
up front (so a key's requests are not serialized behind a single in-flight one).

Kept free of FastAPI imports so it stays unit-testable and reusable from
non-HTTP paths (background jobs, CLI minting tools).
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models.api_key import ApiKey

MICROCENTS_PER_CENT = 10_000


async def read_spent(db: AsyncSession, api_key_id: str) -> int:
    """Return the key's currently-recorded lifetime spend in microcents."""
    spent = (
        await db.execute(select(ApiKey.spent_microcents).where(ApiKey.id == api_key_id))
    ).scalar_one_or_none()
    return int(spent or 0)


async def budget_precheck(db: AsyncSession, api_key_id: str, cap_microcents: int) -> int:
    """The key's spend as of this pre-check, in microcents.

    One read behind both halves of the caller's decision: whether to reject the
    request, and what allowance is left for a cost that is not known yet.
    ``cap_microcents`` is ``ApiKey.budget_limit_cents`` scaled by
    ``MICROCENTS_PER_CENT``, not the column itself. It is unused here and
    becomes load-bearing the moment this function has a parked obligation to
    fold before it answers; keeping it in the signature is what lets the caller
    hold on to a single pre-check call instead of reading the counter twice.
    """
    return await read_spent(db, api_key_id)


async def is_exhausted(db: AsyncSession, api_key_id: str, cap_microcents: int) -> bool:
    """Fast pre-check: has the key already reached its lifetime cap?

    ``cap_microcents`` is ``ApiKey.budget_limit_cents`` scaled by
    ``MICROCENTS_PER_CENT``, not the column itself — passing the raw cents value
    asks whether the key has spent a ten-thousandth of its budget.
    """
    return await budget_precheck(db, api_key_id, cap_microcents) >= cap_microcents


async def charge_budget(
    db: AsyncSession,
    api_key_id: str,
    cap_microcents: int,
    actual_microcents: int,
    *,
    commit: bool = True,
) -> bool:
    """Atomically record ``actual_microcents`` of spend, never exceeding ``cap``.

    Returns ``True`` if the cost fit under the cap (the counter advanced by
    ``actual``), or ``False`` if the request alone would have breached the cap —
    in which case the counter is clamped to ``cap`` so the key is maxed out and
    blocked going forward. The boundary request may already have been served
    upstream; it cannot be un-spent, but we never record more than the cap and we
    stop the next one. Fail-closed.

    When ``commit`` is False the UPDATEs are executed but not committed, so the
    caller can commit them in the same transaction as the request-log write
    (atomic log + charge — no window where the log lands but the charge is lost).
    """
    actual = actual_microcents or 0
    result = await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id, ApiKey.spent_microcents + actual <= cap_microcents)
        .values(spent_microcents=ApiKey.spent_microcents + actual)
    )
    if result.rowcount:
        if commit:
            await db.commit()
        return True
    # Would have exceeded the cap: clamp so the counter never overshoots and the
    # key is correctly reported as exhausted thereafter.
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id, ApiKey.spent_microcents < cap_microcents)
        .values(spent_microcents=cap_microcents)
    )
    if commit:
        await db.commit()
    return False
