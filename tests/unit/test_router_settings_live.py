"""D7: the router's retry count and cooldown can be set in the desktop app
(no .env there) and take effect without a restart. Environment variables
still win, for servers."""

from __future__ import annotations

import asyncio

import pytest

from app import config, router_cache
from packages.desktop import budget, prefs


@pytest.fixture
def built(monkeypatch, isolated_env):
    """Record the knobs each router is built with instead of building one."""
    from packages.litellm_adapter import client as client_mod

    calls: list[dict] = []

    class _Recorder:
        def __init__(self, deployments, **kw):
            calls.append({**kw, "deployments": deployments})
            self._deployments = deployments
            self.strategy = kw.get("strategy")
            self.preferred_models = kw.get("preferred_models")

    monkeypatch.setattr(client_mod, "OrcaLiteLLMClient", _Recorder)
    monkeypatch.setenv("ORCA_DESKTOP_MODE", "1")
    monkeypatch.setenv("ORCA_NO_LOCAL_MODELS", "1")
    config.get_settings.cache_clear()
    router_cache.invalidate_router()
    prefs.note_settings_changed()
    yield calls
    config.get_settings.cache_clear()
    router_cache.invalidate_router()
    prefs.note_settings_changed()


async def _save(db_session, **desktop):
    from app.seed import seed_initial_state
    from packages.db.models.workspace import Workspace

    await seed_initial_state(db_session)
    ws = await db_session.get(Workspace, "default")
    ws.settings_json = {"desktop": desktop}
    await db_session.commit()
    budget.note_settings_changed()


async def test_stored_values_apply_and_changes_rebuild_the_router(built, db_session):
    await _save(db_session, router_num_retries=1, router_cooldown_seconds=7)
    first = await router_cache.get_router(db_session)
    assert (built[-1]["num_retries"], built[-1]["cooldown_time"]) == (1, 7.0)
    assert await router_cache.get_router(db_session) is first  # unchanged: cached

    await _save(db_session, router_num_retries=0, router_cooldown_seconds=0)
    second = await router_cache.get_router(db_session)
    assert second is not first
    assert (built[-1]["num_retries"], built[-1]["cooldown_time"]) == (0, 0.0)


async def test_unset_values_use_the_engine_defaults(built, db_session):
    await _save(db_session)
    await router_cache.get_router(db_session)
    s = config.get_settings()
    assert (built[-1]["num_retries"], built[-1]["cooldown_time"]) == (
        s.router_num_retries_default, float(s.router_cooldown_seconds))


async def test_environment_variables_win(built, db_session, monkeypatch):
    monkeypatch.setenv("ROUTER_NUM_RETRIES_DEFAULT", "3")
    monkeypatch.setenv("ROUTER_COOLDOWN_SECONDS", "11")
    config.get_settings.cache_clear()
    await _save(db_session, router_num_retries=1, router_cooldown_seconds=7)
    await router_cache.get_router(db_session)
    assert (built[-1]["num_retries"], built[-1]["cooldown_time"]) == (3, 11.0)


async def test_servers_never_read_desktop_settings(built, db_session, monkeypatch):
    monkeypatch.delenv("ORCA_DESKTOP_MODE")
    config.get_settings.cache_clear()
    await _save(db_session, router_num_retries=1, router_cooldown_seconds=7)
    await router_cache.get_router(db_session)
    s = config.get_settings()
    assert built[-1]["num_retries"] == s.router_num_retries_default


async def test_local_models_are_deployed_and_follow_discovery(built, db_session, monkeypatch):
    from packages.desktop import local_models as lm

    def _model(name, tools=True):
        return lm.LocalModel(id=f"ollama/{name}", runtime="ollama", name=name, api_base="http://127.0.0.1:11434",
                             context=8192, tools=tools, vision=False)

    found = [lm.Runtime("ollama", "Ollama", "127.0.0.1:11434", True, (_model("a"), _model("b", tools=False)))]

    async def _discover(**_kw):
        lm.remember(found)
        return found

    monkeypatch.delenv("ORCA_NO_LOCAL_MODELS")
    monkeypatch.setattr(lm, "discover", _discover)
    await _save(db_session)
    first = await router_cache.get_router(db_session)
    local = [d for d in built[-1]["deployments"] if d.provider == "local"]
    assert [d.model_name for d in local] == ["ollama/a"]  # default: models with tools
    assert await router_cache.get_router(db_session) is first

    await _save(db_session, local_models=["ollama/b"])  # the user's choice
    await router_cache.get_router(db_session)
    assert [d.model_name for d in built[-1]["deployments"] if d.provider == "local"] == ["ollama/b"]

    found = [lm.Runtime("ollama", "Ollama", "127.0.0.1:11434", False)]  # Ollama stopped
    # Once the cached result is stale, a request gets it at once and the
    # re-probe runs in the background; the next request sees Ollama gone.
    monkeypatch.setattr(lm, "_cache", (0.0, lm._cache[1]))
    await router_cache.get_router(db_session)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await router_cache.get_router(db_session)
    assert not [d for d in built[-1]["deployments"] if d.provider == "local"]


async def test_servers_never_look_for_local_models(built, db_session, monkeypatch):
    from packages.desktop import local_models as lm

    async def _discover(**_kw):
        raise AssertionError("no discovery outside the desktop app")

    monkeypatch.delenv("ORCA_NO_LOCAL_MODELS")
    monkeypatch.delenv("ORCA_DESKTOP_MODE")
    config.get_settings.cache_clear()
    monkeypatch.setattr(lm, "discover", _discover)
    await _save(db_session)
    await router_cache.get_router(db_session)


async def test_switching_hosted_models_rebuilds_with_paid_models(built, db_session, monkeypatch):
    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-x")
    config.get_settings.cache_clear()
    await _save(db_session)  # default: free
    await router_cache.get_router(db_session)
    assert "claude-sonnet-4.6" not in {d.model_name for d in built[-1]["deployments"]}
    assert "orcarouter/free" in {d.model_name for d in built[-1]["deployments"]}
    await _save(db_session, hosted_models="all")
    await router_cache.get_router(db_session)
    assert "claude-sonnet-4.6" in {d.model_name for d in built[-1]["deployments"]}
