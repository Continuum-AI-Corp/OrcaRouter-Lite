"""Tests for GET /v1/hosted — the "Hosted fallback" status endpoint.

The dashboard's hosted CTA card calls this on mount to decide whether to
show the "Get free $5 credit" sign-up flow or the "Active" pill. If this
endpoint lies about state, the conversion funnel breaks.
"""

from __future__ import annotations

import pytest


async def _make_client(tmp_sqlite_url, monkeypatch, env_vars: dict | None = None):
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    for k, v in (env_vars or {}).items():
        monkeypatch.setenv(k, v)
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient
    return engine, factory, AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    )


@pytest.fixture
async def unconfigured_client(tmp_sqlite_url, monkeypatch):
    engine, factory, client = await _make_client(tmp_sqlite_url, monkeypatch)
    async with client as c:
        yield c
    await engine.dispose()
    from packages.db import session as session_mod
    session_mod._session_factory = None


@pytest.fixture
async def env_configured_client(tmp_sqlite_url, monkeypatch):
    engine, factory, client = await _make_client(
        tmp_sqlite_url, monkeypatch,
        {"ORCAROUTER_API_KEY": "sk-orca-from-env"},
    )
    async with client as c:
        yield c
    await engine.dispose()
    from packages.db import session as session_mod
    session_mod._session_factory = None


async def test_hosted_status_unconfigured_shows_signup_url(unconfigured_client):
    r = await unconfigured_client.get("/v1/hosted")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["source"] is None
    assert body["base_url"] == "https://api.orcarouter.ai/v1"
    # Sign-up URL points at the canonical /register page on orcarouter.ai
    # (not /signup or any third-party site). The dashboard's "Get free
    # credit" button opens this URL — getting it wrong sends users to a
    # 404 or worse.
    assert body["signup_url"] == "https://www.orcarouter.ai/register"
    assert body["provider_name"] == "orcarouter"


async def test_hosted_status_env_configured_reports_env_source(env_configured_client):
    r = await env_configured_client.get("/v1/hosted")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is True
    assert body["source"] == "env"


async def test_hosted_status_dashboard_configured_reports_dashboard_source(unconfigured_client):
    """Pasting the key via PUT /v1/providers/orcarouter must flip the status
    to configured + source=dashboard, not env."""
    put = await unconfigured_client.put(
        "/v1/providers/orcarouter",
        json={"api_key": "sk-orca-from-dashboard"},
    )
    assert put.status_code == 200, put.text

    r = await unconfigured_client.get("/v1/hosted")
    body = r.json()
    assert body["configured"] is True
    assert body["source"] == "dashboard"


async def test_hosted_status_dashboard_overrides_env(tmp_sqlite_url, monkeypatch):
    """When both env + DB are set, the source reports 'dashboard'
    (matches the precedence in build_deployments)."""
    engine, factory, client = await _make_client(
        tmp_sqlite_url, monkeypatch,
        {"ORCAROUTER_API_KEY": "sk-orca-from-env"},
    )
    async with client as c:
        await c.put(
            "/v1/providers/orcarouter",
            json={"api_key": "sk-orca-from-dashboard"},
        )
        r = await c.get("/v1/hosted")
        body = r.json()
        assert body["configured"] is True
        assert body["source"] == "dashboard"
    await engine.dispose()
    from packages.db import session as session_mod
    session_mod._session_factory = None


async def test_hosted_status_reports_unconfigured_when_db_row_undecryptable(tmp_sqlite_url, monkeypatch):
    """Codex P1: hosted_key_source previously trusted any enabled DB row,
    but build_deployments only deploys hosted when the key actually
    decrypts. Inject a corrupt encrypted_key directly and verify
    /v1/hosted reports unconfigured (not 'Active' lying to the user)."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    # Insert a corrupt orcarouter row directly — bypasses the encryption
    # path that PUT /v1/providers/orcarouter would use.
    from packages.db.models.provider_key import ProviderKey
    async with factory() as s:
        s.add(ProviderKey(
            provider="orcarouter",
            encrypted_key=b"definitely-not-a-valid-aesgcm-blob",
            key_prefix="sk-orca-...",
            label="default",
            is_enabled=True,
        ))
        await s.commit()

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        r = await c.get("/v1/hosted")
        body = r.json()
        assert body["configured"] is False, (
            "Undecryptable DB row must not flip /v1/hosted to configured — "
            "the router can't actually use it"
        )
        assert body["source"] is None

    await engine.dispose()
    session_mod._session_factory = None


async def test_hosted_status_falls_back_to_env_when_db_row_undecryptable(tmp_sqlite_url, monkeypatch):
    """If the dashboard-stored key is corrupt but ORCAROUTER_API_KEY is
    set, /v1/hosted should report source=env — matching what
    build_deployments will actually do."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)
    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-from-env-fallback")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db import session as session_mod
    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    from app.seed import seed_initial_state
    async with factory() as s:
        seed = await seed_initial_state(s)

    from packages.db.models.provider_key import ProviderKey
    async with factory() as s:
        s.add(ProviderKey(
            provider="orcarouter",
            encrypted_key=b"corrupt",
            key_prefix="sk-orca-...",
            label="default",
            is_enabled=True,
        ))
        await s.commit()

    from app.main import create_app
    app = create_app()
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        r = await c.get("/v1/hosted")
        body = r.json()
        assert body["configured"] is True
        assert body["source"] == "env"

    await engine.dispose()
    session_mod._session_factory = None


async def test_hosted_status_requires_auth(tmp_sqlite_url, monkeypatch):
    """Anonymous clients must not be able to enumerate hosted state."""
    engine, factory, client = await _make_client(tmp_sqlite_url, monkeypatch)
    async with client as c:
        c.headers.pop("Authorization", None)
        r = await c.get("/v1/hosted")
        assert r.status_code == 401
    await engine.dispose()
    from packages.db import session as session_mod
    session_mod._session_factory = None
