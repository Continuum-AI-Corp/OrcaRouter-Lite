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

import asyncio

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models.api_key import ApiKey
from packages.db.models.budget_park import BudgetPark

MICROCENTS_PER_CENT = 10_000

# A settlement that gives up after every retry leaves a delivered cost with no
# record anywhere: the log row and the charge are one transaction, so both roll
# back and the counter never moves. The obligation is parked here — one row per
# settlement, keyed by its `trace_id` — and keeps counting against the cap until
# a budget pre-check folds it into `spent_microcents`.
#
# The park is a database table, not process memory, because the deployment
# stops its machine whenever it goes idle: an in-memory obligation is lost on
# the next cold start, which reopens the cap for exactly the key the failure
# was about to protect. `_unsettled` below only holds an amount while the
# database itself is unreachable — the same outage that caused the park — and a
# later pre-check re-files it once a write goes through again.
_unsettled: dict[tuple[str, str], int] = {}


class _FoldConflict(Exception):
    """A concurrent worker folded the same park first; the loser retries later."""


async def _insert_park(*, trace_id: str, api_key_id: str, microcents: int) -> bool:
    """Persist one parked obligation. Returns True when it is durable.

    Idempotent on `trace_id`: a commit that applied but whose ack was lost
    retries into the same primary key instead of recording the obligation a
    second time. Returns False when the database is unavailable (or this is a
    unit test with no session factory), leaving the caller to hold the amount
    in memory. A cancellation propagates with the memory copy still held.
    """
    from packages.db import session as session_mod

    factory = session_mod._session_factory
    if factory is None:
        return False
    try:
        async with factory() as s:
            s.add(
                BudgetPark(
                    trace_id=trace_id, api_key_id=api_key_id, microcents=microcents,
                )
            )
            await s.commit()
        return True
    except IntegrityError:
        # The obligation is already parked — either by our own retried write
        # after an ack loss, or by a concurrent give-up for the same trace.
        # Either way there is exactly one durable copy, so report success.
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        return False


async def record_unsettled_spend(
    *, trace_id: str, api_key_id: str, microcents: int
) -> None:
    """Keep a settlement that gave up counting against the key's cap.

    The caller is unwinding a failure, so this never loses the amount: a park
    that cannot be written durably is held in memory under its `trace_id` for
    the next pre-check to re-file, and a cancellation holds it before
    propagating rather than taking the obligation with it.
    """
    if microcents <= 0 or not trace_id or not api_key_id:
        return
    key = (str(api_key_id), str(trace_id))
    try:
        if await _insert_park(
            trace_id=key[1], api_key_id=key[0], microcents=microcents
        ):
            return
    except asyncio.CancelledError:
        # `_insert_park` only raises the cancellation unwinding the caller —
        # and the amount still has to be held before it propagates.
        _unsettled[key] = microcents
        raise
    _unsettled[key] = microcents


async def pending_parked_spend(api_key_id: str) -> int:
    """The outstanding park for a key: durable rows plus whatever is memory-only."""
    from packages.db import session as session_mod

    key = str(api_key_id)
    total = sum(
        amount for (held_key, _trace), amount in _unsettled.items() if held_key == key
    )
    factory = session_mod._session_factory
    if factory is None:
        return total
    try:
        async with factory() as s:
            stored = (
                await s.execute(
                    select(func.sum(BudgetPark.microcents)).where(
                        BudgetPark.api_key_id == key
                    )
                )
            ).scalar()
        total += int(stored or 0)
    except Exception:
        pass
    return total


async def settle_parked_spend(api_key_id: str, cap_microcents: int) -> int:
    """Fold a key's parked obligations into its recorded spend. Returns what moved.

    The park exists because a charge could not be recorded; leaving it parked
    forever would mean a key at its cap is rejected by an amount that never
    settles and never clears, so every pre-dispatch check tries to move it.
    Only whole obligations that fit under the remaining allowance move, so the
    counter still cannot overshoot the cap; a park larger than the remainder
    stays parked in full — that over-claim is the fail-closed policy, and it
    stays visible as a row rather than being written off.

    The charge and the row deletions share one transaction with
    compare-and-swap guards: two workers folding the same park cannot
    double-bill it, because the loser's UPDATE or DELETE matches nothing and
    its next request folds what the winner left.
    """
    from packages.db import session as session_mod

    key = str(api_key_id)
    factory = session_mod._session_factory
    if factory is None:
        return 0
    for (held_key, trace_id), amount in list(_unsettled.items()):
        if held_key != key:
            continue
        # A cancellation here propagates with the entry still held; a later
        # pre-check re-files it, and the `trace_id` key keeps the retry from
        # duplicating it.
        if await _insert_park(
            trace_id=trace_id, api_key_id=key, microcents=amount
        ):
            _unsettled.pop((held_key, trace_id), None)
    try:
        async with factory() as s:
            async with s.begin():
                spent = (
                    await s.execute(
                        select(ApiKey.spent_microcents).where(ApiKey.id == key)
                    )
                ).scalar_one_or_none()
                if spent is None:
                    return 0
                spent = int(spent)
                rows = (
                    await s.execute(
                        select(BudgetPark.trace_id, BudgetPark.microcents)
                        .where(BudgetPark.api_key_id == key)
                        .order_by(BudgetPark.created_at)
                    )
                ).all()
                move = 0
                settling: list[str] = []
                for trace_id, microcents in rows:
                    microcents = int(microcents)
                    if spent + move + microcents <= cap_microcents:
                        move += microcents
                        settling.append(trace_id)
                    else:
                        break
                if move <= 0:
                    return 0
                charged = await s.execute(
                    update(ApiKey)
                    .where(ApiKey.id == key, ApiKey.spent_microcents == spent)
                    .values(spent_microcents=spent + move)
                )
                if charged.rowcount != 1:
                    raise _FoldConflict
                cleared = await s.execute(
                    delete(BudgetPark).where(BudgetPark.trace_id.in_(settling))
                )
                if cleared.rowcount != len(settling):
                    raise _FoldConflict
                return move
    except _FoldConflict:
        return 0


async def read_spent(db: AsyncSession, api_key_id: str) -> int:
    """Return the key's currently-recorded lifetime spend in microcents."""
    spent = (
        await db.execute(select(ApiKey.spent_microcents).where(ApiKey.id == api_key_id))
    ).scalar_one_or_none()
    return int(spent or 0)


async def budget_precheck(db: AsyncSession, api_key_id: str, cap_microcents: int) -> int:
    """The key's spend as of this pre-check, in microcents.

    One read behind both halves of the caller's decision: whether to reject the
    request, and what allowance is left for a cost that is not known yet. It
    folds a parked obligation into the counter before answering, so a write
    outage is neither a window of free requests nor a park that can never clear,
    and the result adds whatever is still pending rather than reading only the
    counter: when the fold could not commit, the obligation still has to block
    dispatch.

    ``cap_microcents`` is ``ApiKey.budget_limit_cents`` scaled by
    ``MICROCENTS_PER_CENT``, not the column itself — passing the raw cents value
    asks whether the key has spent a ten-thousandth of its budget.
    """
    key = str(api_key_id)
    spent = await read_spent(db, key)
    pending = await pending_parked_spend(key)
    if pending:
        try:
            await settle_parked_spend(key, cap_microcents)
        except Exception:
            # The fold runs on sessions of its own, so there is nothing to
            # roll back here — and the re-read below still counts the park.
            pass
        spent = await read_spent(db, key)
        pending = await pending_parked_spend(key)
    return spent + pending


async def is_exhausted(db: AsyncSession, api_key_id: str, cap_microcents: int) -> bool:
    """Fast pre-check: has the key already reached its lifetime cap?"""
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
