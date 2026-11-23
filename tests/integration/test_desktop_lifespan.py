"""Desktop-mode startup writes the app key the Orca app and CLI use."""

from __future__ import annotations

import pytest


@pytest.fixture
def desktop_env(tmp_path, monkeypatch, isolated_env):
    from app import config

    home = tmp_path / "orca"
    from packages.desktop import home as dh

    for k, v in dh.desktop_env(home, port=8765).items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    yield home
    config.get_settings.cache_clear()


async def test_desktop_startup_writes_a_working_app_key(desktop_env):
    from app.main import create_app, lifespan
    from packages.auth.key_validator import validate_api_key
    from packages.db import session as session_mod

    app = create_app()
    async with lifespan(app):
        key = (desktop_env / "app.key").read_text().strip()
        async with session_mod._session_factory() as s:
            kc = await validate_api_key(key, s)
    assert kc.name == "desktop-app"


async def test_server_startup_outside_desktop_mode_writes_no_app_key(tmp_path, monkeypatch, isolated_env):
    from app import config
    from app.main import create_app, lifespan

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
    monkeypatch.setenv("ORCA_HOME", str(tmp_path / "orca"))
    monkeypatch.delenv("ORCA_DESKTOP_MODE", raising=False)
    config.get_settings.cache_clear()
    try:
        async with lifespan(create_app()):
            pass
    finally:
        config.get_settings.cache_clear()
    assert not (tmp_path / "orca" / "app.key").exists()


def test_orca_console_script_is_registered():
    import tomllib
    from pathlib import Path

    data = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["orca"] == "app.orca_cli:entrypoint"
