"""The give-up's durability gate (app/routes/chat.py::_give_up_settlement).

Parking is the last resort for a settlement the database never accepted: it
keeps a delivered response counting against the key's cap until a later
settlement can record it. But the final attempt has no retry left to run the
trace_id check, so it gives up on the exception alone — and an exception can
follow a commit that applied (ack lost, or a cancellation that landed after
it). Parking that cost again would bill one delivery twice.
"""

from __future__ import annotations

import asyncio

import pytest

from app.routes.chat import _give_up_settlement
from packages.auth.spend import unsettled_spend


class _Kc:
    """The three attributes the give-up reads off a KeyContext."""

    def __init__(self, key_id: str, *, cap: int = 10_000, carried: int = 0):
        self.key_id = key_id
        self._budget_cap = cap
        self._budget_carried = carried


def _failed(error: str = "connection dropped mid-ack") -> RuntimeError:
    return RuntimeError(error)


async def test_durable_settlement_is_not_parked_again():
    """The row is committed, so its charge already counts: park nothing."""
    kc = _Kc("durable-key", carried=700)

    async def persisted() -> bool:
        return True

    await _give_up_settlement(kc, 900, 3, _failed(), persisted)
    assert unsettled_spend(kc.key_id) == 0


async def test_lost_settlement_parks_its_cost_with_what_it_claimed():
    """Nothing is durable: the delivery and the claimed park stay on the cap."""
    kc = _Kc("lost-key", carried=700)

    async def persisted() -> bool:
        return False

    await _give_up_settlement(kc, 900, 3, _failed("database is locked"), persisted)
    assert unsettled_spend(kc.key_id) == 1_600


async def test_probe_cancelled_parks_before_propagating():
    """Torn down mid-read: the outcome is unknown, so park and re-raise.

    Dropping it here would be fail-open — the cancellation would take this
    request's cost and the parked spend travelling with it out with the
    coroutine.
    """
    kc = _Kc("cancelled-probe-key", carried=700)

    async def persisted() -> bool:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _give_up_settlement(kc, 900, 1, _failed(), persisted)
    assert unsettled_spend(kc.key_id) == 1_600
