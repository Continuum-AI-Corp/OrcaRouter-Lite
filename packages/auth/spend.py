"""Per-key lifetime spend tracking schema and accounting primitives for ``ApiKey.budget_limit_cents``.

This module holds the atomic charge primitives, the pre-check that reads them,
and the park ledger for settlements that could not be recorded.

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
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models.api_key import ApiKey
from packages.db.models.budget_park import BudgetPark
from packages.db.models.request_log import RequestLog

# Defined in `packages.db.units` so the boot repair that clamps a counter to the
# same cap scales by the identical number; re-exported here because this module
# is the documented home of the budget accounting primitives.
from packages.db.units import MICROCENTS_PER_CENT as MICROCENTS_PER_CENT

# A settlement that gives up after every retry leaves a delivered cost with no
# record anywhere: the log row and the charge are one transaction, so both roll
# back and the counter never moves. The obligation is parked — one row per
# settlement, keyed by its `trace_id` — and keeps counting against the cap until
# a budget pre-check folds it into `spent_microcents`.
#
# The park is a database table, not process memory, because the deployment
# stops its machine whenever it goes idle: an in-memory obligation is lost on
# the next cold start, which reopens the cap for exactly the key the failure
# was about to protect. `_unsettled` below is the hold for when even that write
# cannot be made. Preserve each settlement's trace_id so an already-charged
# settlement cannot cause another settlement to be discarded.
#
# One entry per key, not per settlement: a database outage that outlasts many
# requests would otherwise grow this without bound, since an entry only leaves
# when a fold commits and no fold can commit while the database is down.
_unsettled: dict[str, dict[str, int]] = {}


def _hold(api_key_id: str, trace_id: str, microcents: int) -> None:
    """Keep each unsettled obligation separately, keyed by its trace_id."""
    holds = _unsettled.setdefault(api_key_id, {})
    # A trace identifies one settlement. Repeated attempts for that trace
    # must not add the same obligation twice.
    holds[trace_id] = max(holds.get(trace_id, 0), microcents)


class _FoldConflict(Exception):
    """A concurrent worker folded the same park first; the loser retries later."""


async def _park_is_durable(
    *, trace_id: str, api_key_id: str, expected_microcents: int
) -> bool:
    """Whether the durable row covers the entire expected obligation."""
    from packages.db import session as session_mod

    factory = session_mod._session_factory
    if factory is None:
        return False
    try:
        async with factory() as s:
            amount = await s.scalar(
                select(BudgetPark.microcents).where(
                    BudgetPark.trace_id == trace_id,
                    BudgetPark.api_key_id == api_key_id,
                )
            )
            return (
                amount is not None
                and int(amount) >= expected_microcents
            )
    except Exception:
        return False


async def _insert_park(*, trace_id: str, api_key_id: str, microcents: int) -> bool:
    """Persist one parked obligation. Returns True when it is durable.

    Idempotent on `trace_id`: a commit that applied but whose ack was lost
    retries into the same primary key instead of recording the obligation a
    second time. On general failure, `_park_is_durable` is called to probe
    whether the write landed anyway. Returns False only when the obligation is
    genuinely not durable, leaving the caller to hold the amount in memory. A
    cancellation propagates with the memory copy still held.
    """
    from packages.db import session as session_mod

    factory = session_mod._session_factory
    if factory is None:
        return False
    try:
        async with factory() as s:
            try:
                s.add(
                    BudgetPark(
                        trace_id=trace_id, api_key_id=api_key_id, microcents=microcents,
                    )
                )
                await s.commit()
            except IntegrityError:
                # A row for this `trace_id` is already there — our own retried
                # write after an ack loss, or a concurrent give-up. A hold that
                # merged further settlements into this one now carries more
                # than the row does, so raise the row to it rather than
                # reporting success and dropping the difference. Never lowered:
                # the larger amount is the one the cap needs.
                await s.rollback()
                await s.execute(
                    update(BudgetPark)
                    .where(
                        BudgetPark.trace_id == trace_id,
                        BudgetPark.microcents < microcents,
                    )
                    .values(microcents=microcents)
                )
                await s.commit()
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        return await _park_is_durable(
            trace_id=trace_id,
            api_key_id=api_key_id,
            expected_microcents=microcents,
        )


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
    key = str(api_key_id)
    try:
        if await _insert_park(
            trace_id=trace_id, api_key_id=key, microcents=microcents
        ):
            return
    except asyncio.CancelledError:
        # `_insert_park` only raises the cancellation unwinding the caller —
        # and the amount still has to be held before it propagates.
        _hold(key, str(trace_id), microcents)
        raise
    _hold(key, str(trace_id), microcents)


async def pending_parked_spend(api_key_id: str) -> int | None:
    """The outstanding park for a key: durable rows plus whatever is memory-only.

    ``None`` means the durable ledger could not be read, which is a different
    answer from ``0``: the table is the only record of a park written by another
    worker, or by this one before it stopped, so folding a failed read into the
    total reopens the cap for exactly the key the park exists to hold shut. The
    memory half still counts on the way to a real durable read failing, because
    that half is what an outage is expected to lose and what recovers after it.
    """
    from packages.db import session as session_mod

    key = str(api_key_id)
    factory = session_mod._session_factory
    held = _unsettled.get(key, {})
    if factory is None:
        return sum(held.values())
    try:
        async with factory() as s:
            rows = (
                await s.execute(
                    select(BudgetPark.trace_id, BudgetPark.microcents).where(
                        BudgetPark.api_key_id == key
                    )
                )
            ).all()
    except Exception:
        return None
    # Subtract only the part of each hold already represented durably.
    # A matching trace alone does not prove the entire amount was persisted.
    durable_amounts = {
        trace_id: int(microcents) for trace_id, microcents in rows
    }
    stored = sum(durable_amounts.values())

    held_amount = sum(
        max(0, amount - durable_amounts.get(trace_id, 0))
        for trace_id, amount in held.items()
    )
    return stored + held_amount


async def settle_parked_spend(api_key_id: str, cap_microcents: int) -> int:
    """Fold a key's parked obligations into its recorded spend. Returns what moved.

    The park exists because a charge could not be recorded; leaving it parked
    forever would mean a key at its cap is rejected by an amount that never
    settles and never clears, so every pre-check tries to move it. Park rows are
    read oldest-`created_at` first and the remaining allowance is applied to them
    in that order; a park larger than the allowance bills what fits and is
    rewritten to its remainder, rather than staying parked whole. That keeps the
    invariant the fold exists to hold: either the queue is empty, or the counter
    sits exactly on the cap. Without it a key can be refused at a lifetime spend
    below its limit with a row that nothing will ever shrink, which is the state
    this function is supposed to drain. The remainder is still a real debt — the
    over-claim is the fail-closed policy — so it stays visible and keeps
    `is_exhausted` blocking; it is never written off, and it folds for free the
    moment the cap is raised.

    Two parks carrying the same `created_at` fall through to the `trace_id`
    tiebreak, and `trace_id` is a uuid4 — so for obligations stamped within the
    same clock tick the order is arbitrary rather than oldest-first. The
    accounting does not depend on which row wins: the parked total is conserved
    either way, the counter still reaches `min(cap, spent + debt)`, and only
    which row is trimmed differs.

    The charge and the row writes share one transaction with compare-and-swap
    guards on each: two workers folding the same park cannot double-bill it,
    because the loser's UPDATE or DELETE matches nothing and its next request
    folds what the winner left.
    """
    from packages.db import session as session_mod

    key = str(api_key_id)
    factory = session_mod._session_factory
    if factory is None:
        return 0
    # Re-file each obligation under its own trace. A single merged row would
    # let the fold mistake unrelated spend for an already-charged settlement.
    while (holds := _unsettled.get(key)):
        trace_id, amount = next(iter(holds.items()))
        # A cancellation here propagates with the hold still in place; a later
        # pre-check re-files it under the same trace_id.
        if not await _insert_park(
            trace_id=trace_id, api_key_id=key, microcents=amount
        ):
            break
        current = _unsettled.get(key)
        if current is not None and current.get(trace_id) == amount:
            current.pop(trace_id)
            if not current:
                _unsettled.pop(key, None)
        # If the amount grew during the write, leave it in place and retry.
    move = 0
    settling: list[tuple[str, int]] = []
    billed_amounts: dict[str, int] = {}
    trim: tuple[str, int, int] | None = None
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
                        # Oldest debt first. `created_at` is stamped
                        # Python-side with sub-second resolution, but two
                        # workers computing the same fold still have to agree on
                        # which row is the partial one, so `trace_id` breaks any
                        # tie rather than letting the order depend on a race.
                        .order_by(BudgetPark.created_at, BudgetPark.trace_id)
                    )
                ).all()
                # A log row and its budget charge are committed atomically.
                # If a commit acknowledgement was lost and the durability
                # probe also failed, the matching park is only a fallback
                # record; the request-log row proves the charge already landed.
                logged = set(
                    (
                        await s.scalars(
                            select(RequestLog.trace_id).where(
                                RequestLog.trace_id.in_(
                                    [trace_id for trace_id, _amount in rows]
                                )
                            )
                        )
                    ).all()
                ) if rows else set()
                already_charged = [
                    (trace_id, int(amount))
                    for trace_id, amount in rows
                    if trace_id in logged
                ]
                if already_charged:
                    billed_amounts.update({
                        trace_id: int(amount)
                        for trace_id, amount in rows
                        if trace_id in logged
                    })
                    for trace_id, amount in already_charged:
                        cleared = await s.execute(
                            delete(BudgetPark).where(
                                BudgetPark.trace_id == trace_id,
                                BudgetPark.api_key_id == key,
                                BudgetPark.microcents == amount,
                            )
                        )
                        if cleared.rowcount != 1:
                            raise _FoldConflict
                    rows = [row for row in rows if row[0] not in logged]
                room = cap_microcents - spent
                for trace_id, microcents in rows:
                    microcents = int(microcents)
                    if microcents <= room:
                        room -= microcents
                        move += microcents
                        settling.append((trace_id, microcents))
                        billed_amounts[trace_id] = microcents
                        continue
                    if room > 0:
                        trim = (trace_id, microcents, microcents - room)
                        move += room
                    break
                # Even with no spend to move, already-charged rows may have
                # been deleted and their corresponding holds need reconciliation.
                if move <= 0 and not already_charged:
                    return 0
                else:
                    charged = await s.execute(
                        update(ApiKey)
                        .where(ApiKey.id == key, ApiKey.spent_microcents == spent)
                        .values(spent_microcents=spent + move)
                    )
                    if charged.rowcount != 1:
                        raise _FoldConflict
                if settling:
                    for trace_id, amount in settling:
                        cleared = await s.execute(
                            delete(BudgetPark).where(
                                BudgetPark.trace_id == trace_id,
                                BudgetPark.api_key_id == key,
                                BudgetPark.microcents == amount,
                            )
                        )
                        if cleared.rowcount != 1:
                            raise _FoldConflict
                if trim is not None:
                    trace_id, whole, remainder = trim
                    trimmed = await s.execute(
                        update(BudgetPark)
                        .where(
                            BudgetPark.trace_id == trace_id,
                            BudgetPark.api_key_id == key,
                            BudgetPark.microcents == whole,
                        )
                        .values(microcents=remainder)
                    )
                    if trimmed.rowcount != 1:
                        raise _FoldConflict
    except _FoldConflict:
        return 0
    # Reconcile only the amount actually covered by committed rows. A hold
    # for another trace is never cleared just because one row was billed.
    holds = _unsettled.get(key)
    if holds:
        for trace_id, covered in billed_amounts.items():
            held_amount = holds.get(trace_id)
            if held_amount is None:
                continue
            holds.pop(trace_id)
            remainder = held_amount - covered
            if remainder > 0:
                # The original park was deleted. Give the remaining debt a
                # fresh identity so re-filing cannot collide with that row.
                holds[str(uuid.uuid4())] = remainder
        if not holds:
            _unsettled.pop(key, None)
    return move


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
    dispatch. A park ledger that cannot be read at all is answered as the cap
    rather than as no debt.
    """
    key = str(api_key_id)
    pending = await pending_parked_spend(key)
    if pending is None:
        # Unknown debt is answered as full debt, the way the durability probe
        # that wrote the park reads an unreadable database as "not settled".
        # The alternative is a key whose cap is held shut only by parked rows
        # dispatching freely while the ledger is down.
        return cap_microcents
    # The park ledger is read before the counter, and the counter on a fresh
    # snapshot: a fold both moves `spent_microcents` and empties the park
    # queue, so a counter read first can pair a pre-fold spend with a zero
    # pending — understating the spend by exactly the folded amount with no
    # evidence left to trigger the re-read. Parks-first keeps the evidence:
    # a fold racing these reads leaves `pending > 0`, which takes the
    # re-read below.
    try:
        await db.rollback()
    except Exception:
        pass
    spent = await read_spent(db, key)
    if pending:
        try:
            await settle_parked_spend(key, cap_microcents)
        except Exception:
            # The fold runs on sessions of its own, so there is nothing to
            # roll back here — and the re-read below still counts the park.
            pass
        spent = await read_spent(db, key)
        pending = await pending_parked_spend(key)
        if pending is None:
            return cap_microcents
    return spent + pending


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

    Both UPDATEs run with ``synchronize_session=False``: the session default
    evaluates the SET in Python against any identity-map copy of the row and
    marks it dirty, so a caller that loaded the key before this charge (same
    session, loaded by auth, then charged) would flush that stale computed value
    over the DB's atomic result —
    silently dropping a concurrent charge. The DB row stays the only source of
    truth; read the counter back with ``read_spent`` if you need it.
    """
    actual = actual_microcents or 0
    result = await db.execute(
        update(ApiKey)
        .where(ApiKey.id == api_key_id, ApiKey.spent_microcents + actual <= cap_microcents)
        .values(spent_microcents=ApiKey.spent_microcents + actual)
        .execution_options(synchronize_session=False)
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
        .execution_options(synchronize_session=False)
    )
    if commit:
        await db.commit()
    return False
