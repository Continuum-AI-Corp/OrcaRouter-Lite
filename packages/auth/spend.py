"""Per-key spend tracking used to enforce ``ApiKey.budget_limit_cents``.

The budget is a *lifetime* cap on the key's total spend in microcents
(1 cent = 10_000 microcents; 1 USD = 1_000_000 microcents, matching
chat.py's cost math).

Enforcement is atomic and database-level, so the cap holds even when many
requests for the same key arrive concurrently **and** across processes (not
just within one event loop):

* ``claim_budget`` reserves the *remaining* budget at request start via a single
  conditional ``UPDATE`` that moves the key's counter up to the cap. Any other
  request for the same key then observes a full counter and is rejected.
* The exact cost of a request is only known after the upstream response/stream
  completes, so ``settle_budget`` reconciles the provisional claim with the
  actual cost.
* If a request errors before it can be charged, the claim is left in place
  (fail-closed: the key simply can't be used again until the operator
  intervenes). It can never *under*-charge the operator, which is the property
  that matters for a money limiter.

Kept free of FastAPI imports so it stays unit-testable and reusable from
non-HTTP contexts (background jobs, CLI minting tools).
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


async def claim_budget(db: AsyncSession, api_key_id: str, cap_microcents: int) -> int | None:
    """Reserve the remaining budget for ``api_key_id``.

    Returns the amount claimed (== remaining budget) if the request may proceed,
    or ``None`` if the cap is already reached. The claim moves the key's spend
    counter up to the cap *and commits*, so any concurrent request for the same
    key observes a full counter and is rejected. The optimistic
    ``WHERE spent_microcents == spent`` guard means that if two requests race,
    exactly one wins the claim; the loser sees 0 affected rows and is rejected
    (never over-charged).
    """
    spent = await read_spent(db, api_key_id)
    if spent >= cap_microcents:
        return None
    remaining = cap_microcents - spent
    result = await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id, ApiKey.spent_microcents == spent)
        .values(spent_microcents=cap_microcents)
    )
    if result.rowcount == 0:
        return None
    await db.commit()
    return remaining


async def settle_budget(
    db: AsyncSession, api_key_id: str, claimed_microcents: int, actual_microcents: int
) -> None:
    """Reconcile a prior claim with the actual cost.

    After a successful request the key's spend becomes ``old + actual``
    regardless of how much was provisionally claimed, so the counter stays
    accurate for the next request.
    """
    await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id)
        .values(
            spent_microcents=ApiKey.spent_microcents
            - claimed_microcents
            + (actual_microcents or 0)
        )
    )
    await db.commit()
