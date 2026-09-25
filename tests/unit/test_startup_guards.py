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


async def test_audit_reports_undecryptable_rows_without_raising(guarded_db, caplog):
    """A rotated/corrupt ciphertext must be visible at startup, but must
    not refuse boot — the dashboard is how the operator re-saves keys."""
    import logging

    from packages.auth.encryption import encrypt_credential
    from packages.db.guards import audit_stored_provider_credentials
    from packages.db.models.provider_key import ProviderKey

    url, factory = guarded_db
    async with factory() as s:
        s.add(ProviderKey(
            provider="openai",
            encrypted_key=encrypt_credential("sk-good"),
            key_prefix="sk-good...xxxx",
        ))
        s.add(ProviderKey(
            provider="anthropic",
            encrypted_key=b"not-valid-aesgcm-ciphertext",
            key_prefix="sk-ant-...xxxx",
        ))
        await s.commit()

    caplog.set_level(logging.ERROR, logger="orca.credentials")
    audit = await audit_stored_provider_credentials(make_session=factory)
    assert audit.undecryptable == ("anthropic",)
    assert audit.reencrypted == ()
    assert "anthropic" in caplog.text
    assert "CREDENTIAL_ENCRYPTION_KEY" in caplog.text


async def test_audit_reencrypts_rows_sealed_with_previous_key(guarded_db, monkeypatch):
    """CREDENTIAL_ENCRYPTION_PREVIOUS_KEY is the documented migrate path:
    seal under key A, rotate Settings to key B + previous=A, audit must
    rewrite the row so it opens with B alone."""
    from app import config as cfg
    from packages.auth.encryption import decrypt_credential, encrypt_credential
    from packages.db.guards import audit_stored_provider_credentials
    from packages.db.models.provider_key import ProviderKey

    key_a = "aa" * 32
    key_b = "bb" * 32

    cfg.get_settings.cache_clear()
    s_a = cfg.Settings(_env_file=None, credential_encryption_key=key_a)
    monkeypatch.setattr(cfg, "get_settings", lambda: s_a)
    blob_a = encrypt_credential("sk-to-migrate")

    url, factory = guarded_db
    async with factory() as s:
        s.add(ProviderKey(
            provider="openai",
            encrypted_key=blob_a,
            key_prefix="sk-to-m...rate",
        ))
        await s.commit()

    s_b = cfg.Settings(
        _env_file=None,
        credential_encryption_key=key_b,
        credential_encryption_previous_key=key_a,
    )
    monkeypatch.setattr(cfg, "get_settings", lambda: s_b)

    audit = await audit_stored_provider_credentials(
        make_session=factory, previous_key=key_a,
    )
    assert audit.reencrypted == ("openai",)
    assert audit.undecryptable == ()

    from sqlalchemy import select

    async with factory() as s:
        row = (await s.execute(select(ProviderKey))).scalar_one()
        migrated = row.encrypted_key
    assert migrated != blob_a
    assert decrypt_credential(migrated) == "sk-to-migrate"

    # Previous key no longer required.
    s_b_only = cfg.Settings(_env_file=None, credential_encryption_key=key_b)
    monkeypatch.setattr(cfg, "get_settings", lambda: s_b_only)
    assert decrypt_credential(migrated) == "sk-to-migrate"


async def test_audit_does_not_reencrypt_onto_insecure_dev_key(
    guarded_db, monkeypatch, caplog,
):
    """CREDENTIAL_ENCRYPTION_KEY unset + PREVIOUS_KEY set must not migrate
    real ciphertext onto the publicly-known SHA-256 fallback — even when
    ORCA_ALLOW_INSECURE_DEV_KEY / allow_insecure_dev_key lets boot proceed.
    """
    import logging

    from sqlalchemy import select

    from app import config as cfg
    from packages.auth.encryption import (
        decrypt_credential,
        encrypt_credential,
        is_using_insecure_dev_key,
        materialize_encryption_key,
    )
    from packages.db.guards import audit_stored_provider_credentials
    from packages.db.models.provider_key import ProviderKey

    key_a = "aa" * 32

    cfg.get_settings.cache_clear()
    s_a = cfg.Settings(_env_file=None, credential_encryption_key=key_a)
    monkeypatch.setattr(cfg, "get_settings", lambda: s_a)
    blob_a = encrypt_credential("sk-production-secret")

    url, factory = guarded_db
    async with factory() as s:
        s.add(ProviderKey(
            provider="openai",
            encrypted_key=blob_a,
            key_prefix="sk-prod...xxxx",
        ))
        await s.commit()

    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    s_dev = cfg.Settings(
        _env_file=None,
        credential_encryption_key="",
        credential_encryption_previous_key=key_a,
        allow_insecure_dev_key=True,
    )
    monkeypatch.setattr(cfg, "get_settings", lambda: s_dev)
    assert is_using_insecure_dev_key()

    def _must_not_reseal(*_a, **_kw):
        raise AssertionError("audit resealed onto the insecure dev key")

    monkeypatch.setattr(
        "packages.auth.encryption.encrypt_credential", _must_not_reseal,
    )

    caplog.set_level(logging.ERROR, logger="orca.credentials")
    audit = await audit_stored_provider_credentials(
        make_session=factory, previous_key=key_a,
    )
    assert audit.reencrypted == ()
    assert audit.undecryptable == ("openai",)
    assert "reencrypt_skipped_insecure_dev_key" in caplog.text

    async with factory() as s:
        stored = (await s.execute(select(ProviderKey))).scalar_one()
    assert stored.encrypted_key == blob_a
    # Still opens with the real previous key, not the public fallback.
    assert decrypt_credential(
        stored.encrypted_key, key=materialize_encryption_key(key_a),
    ) == "sk-production-secret"


async def test_audit_does_not_reencrypt_when_key_resolution_fails(
    guarded_db, monkeypatch,
):
    """A failure while resolving the destination key must not reseal.

    ``is_using_insecure_dev_key`` fails open (returns False) so the boot
    guard keeps its existing contract. The audit fails closed instead:
    unknown destination, ciphertext unchanged.
    """
    from sqlalchemy import select

    from app import config as cfg
    from packages.auth.encryption import encrypt_credential
    from packages.db.guards import audit_stored_provider_credentials
    from packages.db.models.provider_key import ProviderKey

    key_a = "aa" * 32
    key_b = "bb" * 32
    cfg.get_settings.cache_clear()
    monkeypatch.setattr(
        cfg, "get_settings",
        lambda: cfg.Settings(_env_file=None, credential_encryption_key=key_a),
    )
    blob_a = encrypt_credential("sk-production-secret")

    _url, factory = guarded_db
    async with factory() as s:
        s.add(ProviderKey(
            provider="openai",
            encrypted_key=blob_a,
            key_prefix="sk-prod...xxxx",
        ))
        await s.commit()

    # Current key is a real key B, so the row is not "already current".
    # Destination resolution then fails and must not fall through to reseal.
    monkeypatch.setattr(
        cfg, "get_settings",
        lambda: cfg.Settings(_env_file=None, credential_encryption_key=key_b),
    )

    def _boom():
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(
        "packages.auth.encryption.resolve_encryption_key", _boom,
    )

    audit = await audit_stored_provider_credentials(
        make_session=factory, previous_key=key_a,
    )
    assert audit.reencrypted == ()
    assert audit.undecryptable == ("openai",)

    async with factory() as s:
        stored = (await s.execute(select(ProviderKey))).scalar_one()
    assert stored.encrypted_key == blob_a


async def test_audit_skips_deleted_rows(guarded_db):
    from packages.db.guards import audit_stored_provider_credentials
    from packages.db.models.provider_key import ProviderKey

    url, factory = guarded_db
    async with factory() as s:
        s.add(ProviderKey(
            provider="openai",
            encrypted_key=b"corrupt",
            key_prefix="sk-...",
            is_deleted=1,
        ))
        await s.commit()

    audit = await audit_stored_provider_credentials(make_session=factory)
    assert audit.undecryptable == ()
    assert audit.reencrypted == ()


async def test_cas_reencrypt_skips_when_ciphertext_changed(guarded_db):
    """Optimistic guard: a PUT that rewrote encrypted_key between our
    snapshot and the UPDATE must win. rowcount==0, stored blob unchanged."""
    from sqlalchemy import select

    from packages.auth.encryption import encrypt_credential
    from packages.db.guards import _cas_reencrypt_provider_key
    from packages.db.models.provider_key import ProviderKey

    url, factory = guarded_db
    original = encrypt_credential("sk-old")
    newer = encrypt_credential("sk-from-put")
    stale_rewrite = encrypt_credential("sk-old")

    async with factory() as s:
        row = ProviderKey(
            provider="openai",
            encrypted_key=original,
            key_prefix="sk-old...xxxx",
        )
        s.add(row)
        await s.commit()
        row_id = row.id

    async with factory() as s:
        live = (await s.execute(select(ProviderKey))).scalar_one()
        live.encrypted_key = newer
        live.key_prefix = "sk-from-...put"
        await s.commit()

    async with factory() as s:
        wrote = await _cas_reencrypt_provider_key(
            s,
            row_id=row_id,
            observed_encrypted_key=original,
            new_encrypted_key=stale_rewrite,
        )
        await s.commit()

    assert wrote is False
    async with factory() as s:
        stored = (await s.execute(select(ProviderKey))).scalar_one()
    assert stored.encrypted_key == newer


async def test_audit_does_not_clobber_concurrent_provider_key_put(
    guarded_db, monkeypatch,
):
    """Rolling-restart race: audit SELECTs ciphertext sealed with the
    previous key, an operator PUT commits a new key, then the audit's
    write must not restore the old plaintext.

    Interleave the PUT after the snapshot session closes and before the
    per-row CAS transaction opens — the same gap a live PUT would hit.
    """
    from contextlib import asynccontextmanager

    from sqlalchemy import select

    from app import config as cfg
    from packages.auth.encryption import decrypt_credential, encrypt_credential
    from packages.db.guards import audit_stored_provider_credentials
    from packages.db.models.provider_key import ProviderKey

    key_a = "aa" * 32
    key_b = "bb" * 32

    cfg.get_settings.cache_clear()
    s_a = cfg.Settings(_env_file=None, credential_encryption_key=key_a)
    monkeypatch.setattr(cfg, "get_settings", lambda: s_a)
    blob_a = encrypt_credential("sk-to-migrate")

    url, factory = guarded_db
    async with factory() as s:
        s.add(ProviderKey(
            provider="openai",
            encrypted_key=blob_a,
            key_prefix="sk-to-m...rate",
        ))
        await s.commit()

    s_b = cfg.Settings(
        _env_file=None,
        credential_encryption_key=key_b,
        credential_encryption_previous_key=key_a,
    )
    monkeypatch.setattr(cfg, "get_settings", lambda: s_b)
    put_blob = encrypt_credential("sk-from-put")

    sessions = 0

    @asynccontextmanager
    async def racing_factory():
        nonlocal sessions
        sessions += 1
        async with factory() as session:
            yield session
        if sessions == 1:
            async with factory() as s:
                row = (await s.execute(select(ProviderKey))).scalar_one()
                row.encrypted_key = put_blob
                row.key_prefix = "sk-from-...put"
                await s.commit()

    audit = await audit_stored_provider_credentials(
        make_session=racing_factory, previous_key=key_a,
    )
    assert audit.reencrypted == ()
    assert audit.undecryptable == ()

    async with factory() as s:
        stored = (await s.execute(select(ProviderKey))).scalar_one()
    assert stored.encrypted_key == put_blob
    assert decrypt_credential(stored.encrypted_key) == "sk-from-put"


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
