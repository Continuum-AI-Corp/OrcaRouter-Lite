"""The desktop engine's home folder: secrets, environment and the app key."""

from __future__ import annotations

import json
import os
import stat

import pytest

from packages.desktop import home as dh


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_prepare_home_creates_private_folder_and_secrets(tmp_path):
    h = tmp_path / "orca"
    secrets = dh.prepare_home(h)
    assert _mode(h) == 0o700
    assert _mode(h / "secrets.json") == 0o600
    assert len(secrets["credential_encryption_key"]) == 64
    int(secrets["credential_encryption_key"], 16)  # hex
    assert len(secrets["api_key_pepper"]) >= 32


def test_prepare_home_is_stable_across_runs(tmp_path):
    h = tmp_path / "orca"
    assert dh.prepare_home(h) == dh.prepare_home(h)


def test_desktop_env_binds_to_loopback_and_uses_home_database(tmp_path):
    h = tmp_path / "orca"
    secrets = dh.prepare_home(h)
    env = dh.desktop_env(h, port=8765)
    assert env["ORCA_DESKTOP_MODE"] == "1"
    assert env["ORCA_HOME"] == str(h)
    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "8765"
    assert env["DATABASE_URL"] == f"sqlite+aiosqlite:///{h / 'orca.db'}"
    assert env["CREDENTIAL_ENCRYPTION_KEY"] == secrets["credential_encryption_key"]
    assert env["API_KEY_PEPPER"] == secrets["api_key_pepper"]


def test_engine_info_round_trip(tmp_path):
    h = tmp_path / "orca"
    dh.prepare_home(h)
    dh.write_engine_info(h, base_url="http://127.0.0.1:8765", pid=1234)
    info = dh.read_engine_info(h)
    assert info["base_url"] == "http://127.0.0.1:8765"
    assert info["pid"] == 1234
    assert _mode(h / "engine.json") == 0o600


def test_read_engine_info_missing_raises(tmp_path):
    with pytest.raises(dh.EngineNotRunning):
        dh.read_engine_info(tmp_path / "nope")


async def test_ensure_app_key_writes_a_working_key(tmp_path, db_session):
    from app.seed import seed_initial_state
    from packages.auth.key_validator import validate_api_key

    await seed_initial_state(db_session)
    h = tmp_path / "orca"
    dh.prepare_home(h)
    key = await dh.ensure_app_key(db_session, h)
    assert (h / "app.key").read_text().strip() == key
    assert _mode(h / "app.key") == 0o600
    kc = await validate_api_key(key, db_session)
    assert kc.name == "desktop-app"


async def test_ensure_app_key_reuses_a_valid_key(tmp_path, db_session):
    from app.seed import seed_initial_state

    await seed_initial_state(db_session)
    h = tmp_path / "orca"
    dh.prepare_home(h)
    first = await dh.ensure_app_key(db_session, h)
    assert await dh.ensure_app_key(db_session, h) == first


async def test_ensure_app_key_replaces_a_revoked_key(tmp_path, db_session):
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.seed import seed_initial_state
    from packages.auth.key_validator import AuthError, validate_api_key
    from packages.db.models.api_key import ApiKey

    await seed_initial_state(db_session)
    h = tmp_path / "orca"
    dh.prepare_home(h)
    first = await dh.ensure_app_key(db_session, h)
    row = (await db_session.execute(select(ApiKey).where(ApiKey.name == "desktop-app"))).scalar_one()
    row.revoked_at = datetime.now(timezone.utc)
    row.is_active = False
    await db_session.commit()

    second = await dh.ensure_app_key(db_session, h)
    assert second != first
    await validate_api_key(second, db_session)
    with pytest.raises(AuthError):
        await validate_api_key(first, db_session)


def test_engine_info_is_json(tmp_path):
    h = tmp_path / "orca"
    dh.prepare_home(h)
    dh.write_engine_info(h, base_url="http://127.0.0.1:1", pid=1)
    json.loads((h / "engine.json").read_text())
