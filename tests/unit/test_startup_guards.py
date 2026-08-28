"""Tests for packages.db.guards.assert_credential_encryption_ready.

The guard must fail closed (RuntimeError) whenever the publicly-known dev
encryption key would protect real credentials — existing provider rows, or
any non-SQLite database — and allow fresh SQLite installs or explicit
opt-in.
"""

from __future__ import annotations

import pytest


def _allow_env(value: str) -> dict[str, str]:
    return {"ORCA_ALLOW_INSECURE_DEV_KEY": value}


@pytest.fixture
async def guarded_db(tmp_sqlite_url):
    """Engine + session factory over a fresh DB with tables created."""
    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    yield tmp_sqlite_url, async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


async def _add_provider_key(make_session) -> None:
    from packages.db.models.provider_key import ProviderKey

    async with make_session() as s:
        s.add(ProviderKey(provider="openai", encrypted_key=b"x" * 40, key_prefix="sk-...abcd"))
        await s.commit()


async def test_fresh_sqlite_without_keys_is_allowed(guarded_db, monkeypatch):
    from packages.db.guards import assert_credential_encryption_ready

    url, factory = guarded_db
    await assert_credential_encryption_ready(
        make_session=factory, database_url=url,
    )


async def test_existing_provider_keys_fail_closed(guarded_db):
    from packages.db.guards import assert_credential_encryption_ready

    url, factory = guarded_db
    await _add_provider_key(factory)

    with pytest.raises(RuntimeError, match="CREDENTIAL_ENCRYPTION_KEY"):
        await assert_credential_encryption_ready(
            make_session=factory, database_url=url,
        )


async def test_non_sqlite_requires_explicit_key_even_when_empty(guarded_db):
    from packages.db.guards import assert_credential_encryption_ready

    url, factory = guarded_db
    with pytest.raises(RuntimeError, match="non-SQLite"):
        await assert_credential_encryption_ready(
            make_session=factory,
            # storage stays on sqlite; only the *claimed* URL is postgres
            database_url="postgresql+asyncpg://user:pw@db.example/orca",
        )


async def test_opt_in_flag_bypasses_the_guard(guarded_db):
    from packages.db.guards import assert_credential_encryption_ready

    url, factory = guarded_db
    await _add_provider_key(factory)

    await assert_credential_encryption_ready(
        make_session=factory, database_url=url,
        os_environ=_allow_env("1"),
    )
    await assert_credential_encryption_ready(
        make_session=factory, database_url=url,
        allow_insecure_dev_key=True,
    )


async def test_guard_no_ops_when_real_key_configured(guarded_db, monkeypatch):
    """When Settings carries a real key, is_using_insecure_dev_key() is False
    and the guard returns immediately regardless of stored rows."""
    from app import config as cfg
    from packages.db.guards import assert_credential_encryption_ready

    cfg.get_settings.cache_clear()
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    real = cfg.Settings(_env_file=None, credential_encryption_key="11" * 32)
    monkeypatch.setattr(cfg, "get_settings", lambda: real)

    url, factory = guarded_db
    await _add_provider_key(factory)

    await assert_credential_encryption_ready(
        make_session=factory, database_url=url,
    )


async def test_guard_fails_closed_on_transient_db_error(guarded_db, monkeypatch):
    """A transient DB error (e.g. 'database is locked') must not be
    treated as 'table missing' — the guard must fail closed."""
    from packages.db.guards import assert_credential_encryption_ready

    url, factory = guarded_db

    async def _boom(*_a, **_kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("packages.db.guards._count_provider_keys", _boom)
    with pytest.raises(RuntimeError, match="database is locked"):
        await assert_credential_encryption_ready(
            make_session=factory, database_url=url,
        )


async def test_guard_allows_missing_table_on_fresh_sqlite(tmp_sqlite_url):
    """A fresh DB pre-migration where provider_keys doesn't exist counts
    as zero rows for sqlite (inspected via engine, not string matching)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.guards import assert_credential_encryption_ready

    engine = build_engine(tmp_sqlite_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    # No create_all — table genuinely missing.
    await assert_credential_encryption_ready(
        make_session=factory, database_url=tmp_sqlite_url, engine=engine,
    )
    await engine.dispose()
