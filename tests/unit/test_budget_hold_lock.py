"""Postgres has to be made to queue; sqlite does it on its own.

One INSERT..SELECT is only atomic where writers serialise. Postgres hands
every caller the same MVCC snapshot, so without a lock they'd all read
the same remaining budget and all pass the cap.
"""

from types import SimpleNamespace

import pytest

from app.routes.chat import _BudgetHold
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext

_LOCK = "pg_advisory_xact_lock"
_INSERT = "INSERT INTO budget_holds"


class _RecordingDB:
    """Stands in for AsyncSession. No server, just what would have run."""

    def __init__(self, dialect: str) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))

    @property
    def statements(self) -> list[str]:
        return [sql for sql, _ in self.calls]

    def get_bind(self):
        return self._bind

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        self.calls.append(("COMMIT", {}))


def _body() -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}]
    )


def _kc(key_id: str) -> KeyContext:
    return KeyContext(
        key_id=key_id, workspace_id="default", name="k", budget_limit_cents=100
    )


@pytest.mark.asyncio
async def test_postgres_locks_the_key_before_it_reads_the_budget():
    db = _RecordingDB("postgresql")
    await _BudgetHold(db).acquire(_kc("k1"), _body(), ["gpt-4o-mini"])

    lock = next(i for i, s in enumerate(db.statements) if _LOCK in s)
    insert = next(i for i, s in enumerate(db.statements) if _INSERT in s)
    commit = next(i for i, s in enumerate(db.statements) if s == "COMMIT")
    assert lock < insert < commit


@pytest.mark.asyncio
async def test_the_lock_is_per_key_not_global():
    """Two different keys must not queue behind each other."""
    db = _RecordingDB("postgresql")
    await _BudgetHold(db).acquire(_kc("k1"), _body(), ["gpt-4o-mini"])
    await _BudgetHold(db).acquire(_kc("k2"), _body(), ["gpt-4o-mini"])

    locks = [params["lock"] for sql, params in db.calls if _LOCK in sql]
    assert len(locks) == 2
    assert locks[0] != locks[1]


@pytest.mark.asyncio
async def test_sqlite_gets_no_lock():
    """sqlite serialises writers itself, so the insert alone is enough."""
    db = _RecordingDB("sqlite")
    await _BudgetHold(db).acquire(_kc("k1"), _body(), ["gpt-4o-mini"])
    assert not any(_LOCK in s for s in db.statements)
