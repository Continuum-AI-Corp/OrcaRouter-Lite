"""Async SQLAlchemy engine factory.

SQLite is the default, Postgres opt-in via DATABASE_URL=postgresql+asyncpg://...
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def build_engine(database_url: str) -> AsyncEngine:
    """Build an async engine for the given URL.

    SQLite gets `connect_args={"check_same_thread": False, "timeout": 30.0}`,
    WAL mode, and busy_timeout=30000 to prevent database lock contention under load;
    Postgres uses defaults.
    """
    if database_url.startswith("sqlite"):
        engine = create_async_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30.0},
            future=True,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            raw_conn = getattr(dbapi_connection, "_conn", dbapi_connection)
            if hasattr(raw_conn, "cursor"):
                cursor = raw_conn.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                except Exception:
                    pass
                try:
                    cursor.execute("PRAGMA busy_timeout=30000;")
                except Exception:
                    pass
                try:
                    cursor.execute("PRAGMA synchronous=FULL;")
                except Exception:
                    pass
                cursor.close()

        return engine

    return create_async_engine(database_url, future=True, pool_pre_ping=True)


_engine: AsyncEngine | None = None


def get_engine(database_url: str) -> AsyncEngine:
    """Process-wide singleton."""
    global _engine
    if _engine is None:
        _engine = build_engine(database_url)
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
