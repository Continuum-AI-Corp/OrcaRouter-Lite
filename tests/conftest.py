"""Shared test fixtures for orcarouter-lite."""

import os
import tempfile
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio


@pytest.fixture(autouse=True)
def _reset_module_state() -> Generator[None, None, None]:
    """Wipe module-level singletons between tests so cache state doesn't leak."""
    yield
    try:
        from app import prompt_cache
        prompt_cache.reset_backend()
    except Exception:
        pass
    try:
        from app import router_cache
        router_cache.invalidate_router()
    except Exception:
        pass
    try:
        from app import orcarouter_models
        orcarouter_models.reset_cache()
    except Exception:
        pass


@pytest.fixture
def isolated_env(monkeypatch) -> Generator[None, None, None]:
    """Strip every ORCA_*/OPENAI_*/ANTHROPIC_*/etc env var before a test."""
    drop = [
        k for k in os.environ
        if k.startswith(("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GROQ_",
                         "TOGETHER_", "FIREWORKS_", "ORCAROUTER_",
                         "DATABASE_", "REDIS_", "CREDENTIAL_", "API_KEY_"))
    ]
    for k in drop:
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture
def tmp_sqlite_url() -> Generator[str, None, None]:
    """Disposable SQLite URL pointing to a tempfile."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield f"sqlite+aiosqlite:///{path}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def db_session(tmp_sqlite_url) -> AsyncGenerator:
    """Initialised AsyncSession against a fresh SQLite DB with all tables created."""
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session

    await engine.dispose()
