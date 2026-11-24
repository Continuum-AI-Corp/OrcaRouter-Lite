"""D7: the Artificial Analysis key (benchmark scores for the quality and
balanced strategies) can be saved in the desktop app, which has no .env.
It's stored encrypted like provider keys, never returned, and the
environment variable still wins for servers."""

from __future__ import annotations

import pytest

from tests.integration.test_desktop_api import (  # noqa: F401  (fixtures)
    _auth,
    _client,
    desktop_app,
    desktop_dirs,
    seeded,
)


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch):
    from app import benchmark_key, config

    monkeypatch.delenv("ARTIFICIAL_ANALYSIS_API_KEY", raising=False)
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    config.get_settings.cache_clear()
    benchmark_key.reset()
    yield
    config.get_settings.cache_clear()
    benchmark_key.reset()


async def test_save_show_and_clear(desktop_app, seeded, db_session):
    from packages.db.models.workspace import Workspace

    root, _ = seeded
    async with _client(desktop_app) as c:
        assert (await c.get("/v1/app/benchmark-key", headers=_auth(root))).json() == {
            "configured": False, "source": None, "hint": None}
        r = await c.put("/v1/app/benchmark-key", headers=_auth(root), json={"api_key": "aa-secret-0123456783f2"})
        assert r.status_code == 200, r.text
        assert r.json() == {"configured": True, "source": "app", "hint": "aa-…3f2"}
        assert "secret" not in r.text
        assert (await c.get("/v1/app/benchmark-key", headers=_auth(root))).json()["source"] == "app"
        ws = await db_session.get(Workspace, "default")
        await db_session.refresh(ws)
        assert "aa-secret-0123456783f2" not in str(ws.settings_json)  # encrypted at rest
        r = await c.put("/v1/app/benchmark-key", headers=_auth(root), json={"api_key": None})
        assert r.json() == {"configured": False, "source": None, "hint": None}


async def test_the_environment_wins(desktop_app, seeded, monkeypatch):
    from app import config

    root, _ = seeded
    async with _client(desktop_app) as c:
        await c.put("/v1/app/benchmark-key", headers=_auth(root), json={"api_key": "aa-from-app-0000aaa"})
        monkeypatch.setenv("ARTIFICIAL_ANALYSIS_API_KEY", "aa-from-env-0000bbb")
        config.get_settings.cache_clear()
        r = await c.get("/v1/app/benchmark-key", headers=_auth(root))
    assert r.json() == {"configured": True, "source": "env", "hint": "aa-…bbb"}


async def test_only_the_app_may_set_it(desktop_app, seeded):
    _, restricted = seeded
    async with _client(desktop_app) as c:
        r = await c.put("/v1/app/benchmark-key", headers=_auth(restricted), json={"api_key": "aa-x-12345678"})
    assert r.status_code == 403


async def test_the_quality_resolver_uses_the_saved_key(desktop_app, seeded, db_session, monkeypatch):
    from app import benchmark_key
    from app.quality_scores import fetch_aa_index
    from packages.litellm_adapter import quality_index

    used = []

    async def _fetch(url, api_key, timeout=10.0):
        used.append(api_key)
        return []

    monkeypatch.setattr(quality_index, "_fetch_remote", _fetch)
    root, _ = seeded
    async with _client(desktop_app) as c:
        await c.put("/v1/app/benchmark-key", headers=_auth(root), json={"api_key": "aa-saved-key-77777"})
    benchmark_key.reset()  # as after a restart: read back from the database
    await fetch_aa_index(db=db_session, workspace_id="default", force_refresh=True)
    assert used == ["aa-saved-key-77777"]
