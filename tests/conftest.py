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
    try:
        from packages.litellm_adapter import quality_index
        quality_index.reset_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_orcarouter_remote(request, monkeypatch):
    """Block real HTTP fetches from orcarouter.ai during tests so the suite
    is deterministic regardless of CI runner network conditions.

    Tests that exercise the real fetch path (redirects, transport
    behavior) opt out with `@pytest.mark.real_remote`. Tests that mock
    `_fetch_remote` themselves win automatically because monkeypatch
    applies setattrs in order (last write wins).

    Without this, `/v1/analytics/unreachable` integration tests would
    occasionally surface live orcarouter.ai/models data and assertions
    like 'claude in unreachable list' would flap based on what the page
    returned that minute."""
    if request.node.get_closest_marker("real_remote"):
        return
    try:
        from app import orcarouter_models
    except Exception:
        return

    async def _no_network(url: str, timeout: float = 5.0) -> list[str]:
        raise RuntimeError(
            "test isolation: real _fetch_remote disabled — "
            "monkeypatch it or mark the test with @pytest.mark.real_remote"
        )

    monkeypatch.setattr(orcarouter_models, "_fetch_remote", _no_network)


@pytest.fixture
def isolated_env(monkeypatch) -> Generator[None, None, None]:
    """Strip every ORCA_*/OPENAI_*/ANTHROPIC_*/etc env var before a test.

    Also blocks pydantic-settings from re-reading them out of `.env`
    on the next `Settings()` instantiation. Without this guard, tests
    asserting "no providers configured" silently pull whatever is in
    the developer's local `.env` (which usually has real keys for
    manual testing) and flake under those configurations.
    """
    drop = [
        k for k in os.environ
        if k.startswith(("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GROQ_",
                         "TOGETHER_", "FIREWORKS_", "ORCAROUTER_",
                         "DATABASE_", "REDIS_", "CREDENTIAL_", "API_KEY_"))
    ]
    for k in drop:
        monkeypatch.delenv(k, raising=False)

    # Stop pydantic-settings from re-reading `.env` and undoing the
    # delenv work above. The class-level model_config dict is shared
    # across every Settings() call, so monkeypatch.setitem (which
    # restores on teardown) is the right scope.
    try:
        from app.config import Settings
        monkeypatch.setitem(Settings.model_config, "env_file", None)
    except Exception:
        pass

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
