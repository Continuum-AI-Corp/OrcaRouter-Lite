"""Failing test demonstrating Issue #3: SQLite Database Lock Contention under concurrent write traffic.

When running SQLite with default engine settings (without WAL journal_mode and without connection busy timeouts),
concurrent write transactions (such as AuthMiddleware key updates and RequestLog writes) contend for the
exclusive SQLite database lock, causing `sqlite3.OperationalError: database is locked`.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from packages.auth.hashing import hash_api_key
from packages.db.engine import build_engine
from packages.db.models.api_key import ApiKey
from packages.db.models.base import Base


@pytest.mark.asyncio
async def test_sqlite_lock_contention_under_concurrent_writes():
    """Failing test demonstrating Issue #3:
    Under concurrent write transactions (e.g. auth key last_used updates and request logging),
    the default SQLite engine configuration (DELETE journal mode, no WAL mode or timeout tuning)
    results in database lock errors.
    """
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite+aiosqlite:///{db_path}"

    try:
        # Build engine using packages.db.engine.build_engine (with WAL mode and busy_timeout=30000)
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

        # Simulate 50 concurrent write operations running simultaneously
        async def _concurrent_write_operation(op_id: int):
            async with factory() as session:
                stmt = select(ApiKey).where(ApiKey.id == "key_concurrency_test")
                res = await session.execute(stmt)
                row = res.scalar_one_or_none()
                assert row is not None
                row.last_used_at = datetime.now(timezone.utc)
                # Small artificial delay within open transaction to simulate request processing
                await asyncio.sleep(0.02)
                await session.commit()

        results = await asyncio.gather(
            *[_concurrent_write_operation(i) for i in range(50)],
            return_exceptions=True,
        )

        errors = [r for r in results if isinstance(r, Exception)]

        assert len(errors) == 0, (
            f"Expected 0 database lock errors under concurrent load, but encountered {len(errors)} failures! "
            f"First error: {errors[0] if errors else 'None'}"
        )

        await engine.dispose()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass
        wal_path = f"{db_path}-wal"
        shm_path = f"{db_path}-shm"
        for extra in (wal_path, shm_path):
            if os.path.exists(extra):
                try:
                    os.unlink(extra)
                except OSError:
                    pass
