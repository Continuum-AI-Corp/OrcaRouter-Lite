"""Regression test: SQLite must survive concurrent write traffic without lock errors.

With WAL journal mode and a bounded busy_timeout (set in `build_engine`), concurrent
writers serialize on the write lock instead of raising `sqlite3.OperationalError:
database is locked`. This test fails if either pragma is not applied.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.auth.hashing import hash_api_key
from packages.db.engine import SQLITE_BUSY_TIMEOUT_MS, build_engine
from packages.db.models.api_key import ApiKey
from packages.db.models.base import Base


@pytest.mark.asyncio
async def test_sqlite_lock_contention_under_concurrent_writes():
    """Concurrent single-row writes must complete with zero lock errors.

    The workload intentionally has NO per-operation retry: if WAL / busy_timeout
    were not applied, the collisions would surface as OperationalErrors and this
    test would fail. That is the point — it must be discriminating.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite+aiosqlite:///{db_path}"

    try:
        engine = build_engine(db_url)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)

        raw_key = "sk-orca-test123456789012345678901234"
        key_hash = hash_api_key(raw_key)

        async with factory() as s:
            s.add(
                ApiKey(
                    id="key_concurrency_test",
                    workspace_id="default",
                    name="test-key",
                    key_hash=key_hash,
                    key_prefix="sk-orca-....1234",
                    is_active=True,
                )
            )
            await s.commit()

        # The engine must have actually applied the durability pragmas.
        async with engine.connect() as conn:
            mode = (await conn.execute(text("PRAGMA journal_mode;"))).scalar()
            assert str(mode).lower() == "wal", f"Expected WAL journal mode, got {mode}"
            busy = (await conn.execute(text("PRAGMA busy_timeout;"))).scalar()
            assert int(busy) == SQLITE_BUSY_TIMEOUT_MS, (
                f"Expected busy_timeout={SQLITE_BUSY_TIMEOUT_MS}, got {busy}"
            )

        async def _concurrent_write(op_id: int) -> None:
            async with factory() as session:
                row = (
                    await session.execute(select(ApiKey).where(ApiKey.id == "key_concurrency_test"))
                ).scalar_one_or_none()
                assert row is not None
                row.last_used_at = datetime.now(timezone.utc)
                await session.commit()

        results = await asyncio.gather(
            *[_concurrent_write(i) for i in range(50)],
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 0, (
            f"Expected 0 database lock errors under concurrent load, but encountered "
            f"{len(errors)} failures! First error: {errors[0] if errors else 'None'}"
        )

        await engine.dispose()
    finally:
        for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass
