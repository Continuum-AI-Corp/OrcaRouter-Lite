"""Async SQLAlchemy engine factory.

SQLite is the default, Postgres opt-in via DATABASE_URL=postgresql+asyncpg://...
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def redacted_url(database_url: str) -> str:
    """URL safe for logging: password replaced, garbage input never echoed.

    Uses SQLAlchemy's own renderer so every driver scheme is handled the
    same way (`postgresql+asyncpg://user:***@host/db`). Unparseable input
    degrades to a fixed placeholder instead of being reflected back into
    logs.
    """
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable-database-url>"


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
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                pass
            try:
                cursor.execute("PRAGMA busy_timeout=30000;")
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
