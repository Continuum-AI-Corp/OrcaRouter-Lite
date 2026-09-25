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
# back and the counter never moves. The obligation is parked — one row per
# settlement, keyed by its `trace_id` — and keeps counting against the cap until
# a budget pre-check folds it into `spent_microcents`.
#
# The park is a database table, not process memory, because the deployment
# stops its machine whenever it goes idle: an in-memory obligation is lost on
# the next cold start, which reopens the cap for exactly the key the failure
# was about to protect. `_unsettled` below is the hold for when even that write
# cannot be made — it maps `(api_key_id, trace_id)` to the amount, and a later
# pre-check re-files it once a write goes through again.
_unsettled: dict[tuple[str, str], int] = {}


class _FoldConflict(Exception):
    """A concurrent worker folded the same park first; the loser retries later."""


async def _park_is_durable(trace_id: str) -> bool:
    """Whether a park row for this `trace_id` is committed.

    A commit that applied but whose ack never came back raises exactly like a
    failure, and holding a memory copy beside the durable row puts one
    obligation in both ledgers — the double-bill the `trace_id` key exists to
    absorb. It reads on a fresh session because the failed one is closed by the
    time this runs, and answers False when it cannot read at all: with the
    database truly unreachable the memory hold is all that keeps the cap honest.
    """
    from packages.db import session as session_mod

    factory = session_mod._session_factory
    if factory is None:
        return False
    try:
        async with factory() as s:
            return (
                await s.scalar(
                    select(BudgetPark.trace_id).where(BudgetPark.trace_id == trace_id)
                )
            ) is not None
    except Exception:
        return False


async def _insert_park(*, trace_id: str, api_key_id: str, microcents: int) -> bool:
    """Persist one parked obligation. Returns True when it is durable.

    Idempotent on `trace_id`: a commit that applied but whose ack was lost
    retries into the same primary key instead of recording the obligation a
    second time — and when the retry does not reach the server to be told that,
    the probe below asks the database directly rather than reporting a write that
    landed as one that did not. Returns False only when the obligation is
    genuinely not durable, leaving the caller to hold the amount in memory. A
    cancellation propagates with the memory copy still held.
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
        return await _park_is_durable(trace_id)


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
    except Exception:
        return None
    return total + int(stored or 0)


async def settle_parked_spend(api_key_id: str, cap_microcents: int) -> int:
    """Fold a key's parked obligations into its recorded spend. Returns what moved.

    The park exists because a charge could not be recorded; leaving it parked
    forever would mean a key at its cap is rejected by an amount that never
    settles and never clears, so every pre-check tries to move it. The
    remaining allowance is applied oldest-obligation-first and a park larger
    than it bills what fits and is rewritten to its remainder, rather than
    staying parked whole. That keeps the invariant the fold exists to hold:
    either the queue is empty, or the counter sits exactly on the cap. Without
    it a key can be refused at a lifetime spend below its limit with a row that
    nothing will ever shrink, which is the state this function is supposed to
    drain. The remainder is still a real debt — the over-claim is the
    fail-closed policy — so it stays visible and keeps `is_exhausted` blocking;
    it is never written off, and it folds for free the moment the cap is raised.

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
    move = 0
    settling: list[str] = []
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
                room = cap_microcents - spent
                for trace_id, microcents in rows:
                    microcents = int(microcents)
                    if microcents <= room:
                        room -= microcents
                        move += microcents
                        settling.append(trace_id)
                        continue
                    if room > 0:
                        trim = (trace_id, microcents, microcents - room)
                        move += room
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
                if settling:
                    cleared = await s.execute(
                        delete(BudgetPark).where(BudgetPark.trace_id.in_(settling))
                    )
                    if cleared.rowcount != len(settling):
                        raise _FoldConflict
                if trim is not None:
                    trace_id, whole, remainder = trim
                    trimmed = await s.execute(
                        update(BudgetPark)
                        .where(
                            BudgetPark.trace_id == trace_id,
                            BudgetPark.microcents == whole,
                        )
                        .values(microcents=remainder)
                    )
                    if trimmed.rowcount != 1:
                        raise _FoldConflict
    except _FoldConflict:
        return 0
    # Past the commit, so everything in `settling` is billed and gone from the
    # table. A memory hold for one of those rows is now worse than stale: the
    # next pre-check re-files it as a brand-new park — the `trace_id` no longer
    # collides, this transaction deleted the row — and the same delivery is
    # charged twice against a cap that has no idea it moved. Only `settling`:
    # a trimmed row is still owed, and the hold on it has to stay.
    for _settled in settling:
        _unsettled.pop((key, _settled), None)
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

    ``cap_microcents`` is ``ApiKey.budget_limit_cents`` scaled by
    ``MICROCENTS_PER_CENT``, not the column itself — passing the raw cents value
    asks whether the key has spent a ten-thousandth of its budget.
    """
    key = str(api_key_id)
    spent = await read_spent(db, key)
    pending = await pending_parked_spend(key)
    if pending is None:
        # Unknown debt is answered as full debt, the way the durability probe
        # that wrote the park reads an unreadable database as "not settled".
        # The alternative is a key whose cap is held shut only by parked rows
        # dispatching freely while the ledger is down.
        return cap_microcents
    if pending:
        try:
            await settle_parked_spend(key, cap_microcents)
        except Exception:
            # The fold runs on sessions of its own, so there is nothing to
            # roll back here — and the re-read below still counts the park.
            pass
        # End db's read transaction so its SQLite/Postgres snapshot doesn't stay
        # pinned to the pre-fold spend counter, then re-read on a fresh snapshot.
        try:
            await db.rollback()
        except Exception:
            pass
        spent = await read_spent(db, key)
        pending = await pending_parked_spend(key)
        if pending is None:
            return cap_microcents
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
