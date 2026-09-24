"""Per-key lifetime spend tracking that enforces ``ApiKey.budget_limit_cents``.

The cap is a hard lifetime limit on the key's total spend, in microcents
(1 cent = 10_000 microcents; 1 USD = 1_000_000 microcents, matching chat.py's
cost math).

Actual cost is only known after the upstream call returns, so enforcement is a
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

# A settlement that gives up after every retry leaves a delivered cost with no
# record anywhere: the log row and the charge are one transaction, so both
# rolled back and the counter never moved. The amount is parked here, keyed by
# api key -> (counter value it is pending against, microcents), and keeps
# counting against the cap until a settlement that absorbs it becomes durable.
# Process-local by design: the failure it covers is a write outage, which the
# same process is still living through.
_unsettled: dict[str, tuple[int, int]] = {}


def record_unsettled_spend(
    api_key_id: str, *, recorded_microcents: int, microcents: int
) -> None:
    """Keep a settlement that gave up counting against the key's cap."""
    if microcents <= 0:
        return
    key = str(api_key_id)
    parked = _unsettled.get(key)
    _unsettled[key] = (
        min(recorded_microcents, parked[0]) if parked else recorded_microcents,
        (parked[1] if parked else 0) + microcents,
    )


def unsettled_spend(api_key_id: str) -> int:
    """Spend delivered for this key but not yet made durable."""
    parked = _unsettled.get(str(api_key_id))
    return parked[1] if parked else 0


async def read_spent(db: AsyncSession, api_key_id: str) -> int:
    """Return the key's currently-recorded lifetime spend in microcents."""
    spent = (
        await db.execute(select(ApiKey.spent_microcents).where(ApiKey.id == api_key_id))
    ).scalar_one_or_none()
    return int(spent or 0)


async def is_exhausted(db: AsyncSession, api_key_id: str, cap_microcents: int) -> bool:
    """Fast pre-check: has the key already reached its lifetime cap?

    Includes spend whose settlement gave up, so a write outage cannot be used as
    a window of free requests. Parked amounts are dropped once the counter has
    moved past where they were parked: ``charge_budget`` is the only writer, so
    it moved with them inside it.
    """
    key = str(api_key_id)
    spent = await read_spent(db, key)
    parked = _unsettled.get(key)
    if parked is None:
        return spent >= cap_microcents
    if spent > parked[0]:
        del _unsettled[key]
        return spent >= cap_microcents
    return spent + parked[1] >= cap_microcents


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

    Anything parked by a give-up settlement is added to this charge, so that
    undeliverable cost becomes durable together with it.
    """
    actual = (actual_microcents or 0) + unsettled_spend(api_key_id)
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
