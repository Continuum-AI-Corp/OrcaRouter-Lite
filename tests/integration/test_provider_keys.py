"""Provider keys CRUD — set/list/delete with at-rest encryption."""

import pytest


@pytest.fixture
async def authed_client(tmp_sqlite_url, monkeypatch, isolated_env):
    """A booted lite app + a TestClient with the seeded API key in its headers.

    `isolated_env` strips developer-set provider keys from the env so the
    "list returns empty" assertion isn't drowned out by .env-sourced rows
    (the list endpoint surfaces both DB and env-configured providers as
    of the env-key-visibility fix).
    """
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

    from app.main import create_app

    app = create_app()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as c:
        yield c

    await engine.dispose()
    session_mod._session_factory = None


async def test_list_returns_empty_initially(authed_client):
    r = await authed_client.get("/v1/providers")
    assert r.status_code == 200
    assert r.json() == {"providers": []}


async def test_set_provider_key_then_list(authed_client):
    r = await authed_client.put(
        "/v1/providers/openai",
        json={"api_key": "sk-test-12345"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "openai"
    assert r.json()["key_prefix"].startswith("sk-test-")
    # Plaintext must NOT round-trip through the response
    assert "sk-test-12345" not in r.text

    listing = await authed_client.get("/v1/providers")
    assert listing.status_code == 200
    rows = listing.json()["providers"]
    assert len(rows) == 1
    assert rows[0]["provider"] == "openai"
    assert rows[0]["is_enabled"] is True
    assert "encrypted_key" not in rows[0]
    assert "api_key" not in rows[0]


async def test_delete_provider_key(authed_client):
    await authed_client.put("/v1/providers/openai", json={"api_key": "sk-test"})

    r = await authed_client.delete("/v1/providers/openai")
    assert r.status_code == 204

    listing = await authed_client.get("/v1/providers")
    assert listing.json()["providers"] == []


async def test_delete_is_hard_delete_no_ghost_rows_left_in_db(
    authed_client, tmp_sqlite_url,
):
    """Pre-PR symptom: DELETE was a soft-delete (`is_deleted=1`). The
    next PUT for the same provider would query `is_deleted=0`, miss
    the tombstone, and INSERT a new row. After N PUT/DELETE cycles
    the table held N tombstones for ONE provider — single-tenant
    invariant ('1 row per provider') silently violated.

    Hard-delete fixes the leak: the table never grows past the actual
    in-use rows."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.provider_key import ProviderKey

    # Five PUT/DELETE cycles. Pre-fix this would leave 5 tombstones.
    for i in range(5):
        await authed_client.put(
            "/v1/providers/openai",
            json={"api_key": f"sk-cycle-{i}"},
        )
        await authed_client.delete("/v1/providers/openai")

    engine = build_engine(tmp_sqlite_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        all_rows = (await s.execute(select(ProviderKey))).scalars().all()
        openai_rows = [r for r in all_rows if r.provider == "openai"]
    await engine.dispose()

    assert len(openai_rows) == 0, (
        f"hard-delete must leave zero rows for the provider, got: "
        f"{[(r.provider, r.is_deleted) for r in openai_rows]}"
    )


async def test_put_after_legacy_soft_delete_ghost_wipes_it(
    authed_client, tmp_sqlite_url,
):
    """Migration aid: dev DBs created before this PR may carry
    `is_deleted=1` ghost rows. The PUT path must wipe them
    opportunistically — otherwise the table accumulates ghost rows
    on every set-key from the dashboard until the operator manually
    DELETEs from SQL."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.provider_key import ProviderKey

    # Plant a legacy soft-deleted ghost row directly via ORM (simulates
    # what an old dev DB looks like).
    engine = build_engine(tmp_sqlite_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(ProviderKey(
            provider="openai",
            encrypted_key=b"old-encrypted-blob",
            key_prefix="sk-ghost...old",
            is_enabled=False,
            is_deleted=1,
        ))
        await s.commit()

    # Operator sets a new key from the dashboard.
    r = await authed_client.put(
        "/v1/providers/openai",
        json={"api_key": "sk-new-key-after-ghost"},
    )
    assert r.status_code == 200

    # Ghost row should be gone — table holds exactly one openai row,
    # the freshly-set one.
    async with Session() as s:
        rows = (
            await s.execute(
                select(ProviderKey).where(ProviderKey.provider == "openai")
            )
        ).scalars().all()
    await engine.dispose()

    assert len(rows) == 1, (
        f"PUT must wipe legacy ghost rows, got {len(rows)} rows: "
        f"{[(r.key_prefix, r.is_deleted) for r in rows]}"
    )
    assert rows[0].is_deleted == 0
    assert rows[0].key_prefix.startswith("sk-new-")


async def test_overwrite_existing_key(authed_client):
    await authed_client.put("/v1/providers/openai", json={"api_key": "sk-old"})
    r = await authed_client.put("/v1/providers/openai", json={"api_key": "sk-new"})
    assert r.status_code == 200

    listing = await authed_client.get("/v1/providers")
    assert len(listing.json()["providers"]) == 1


async def test_provider_key_is_encrypted_at_rest(authed_client, tmp_sqlite_url):
    await authed_client.put("/v1/providers/openai", json={"api_key": "sk-secret-99"})

    # Read the raw row back through ORM and verify ciphertext != plaintext.
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.auth.encryption import decrypt_credential
    from packages.db.engine import build_engine
    from packages.db.models.provider_key import ProviderKey

    engine = build_engine(tmp_sqlite_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        rows = (await s.execute(select(ProviderKey))).scalars().all()

    assert len(rows) == 1
    blob = rows[0].encrypted_key
    assert isinstance(blob, bytes)
    assert b"sk-secret-99" not in blob
    assert decrypt_credential(blob) == "sk-secret-99"
    await engine.dispose()


# ── env-sourced provider visibility ───────────────────────────────────


async def test_list_surfaces_env_provider_keys_with_source_marker(
    authed_client, monkeypatch,
):
    """Operator who configured `OPENAI_API_KEY` in `.env` (the documented
    install path) must see "openai" in the dashboard providers list. Before
    this fix, the page showed empty even though chats were succeeding via
    the env key — confusing as hell."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-openai-12345")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    r = await authed_client.get("/v1/providers")
    assert r.status_code == 200
    rows = r.json()["providers"]
    openai_row = next((p for p in rows if p["provider"] == "openai"), None)
    assert openai_row is not None, (
        f"env-set OPENAI_API_KEY must appear in the list, got: {rows}"
    )
    assert openai_row["source"] == "env"
    assert openai_row["is_enabled"] is True
    # Plaintext must NOT round-trip through the response
    assert "sk-env-openai-12345" not in r.text
    # Mask preserves first/last hint so operator can identify which key
    assert openai_row["key_prefix"].startswith("sk-env-o")


async def test_db_key_takes_precedence_over_env_in_listing(
    authed_client, monkeypatch,
):
    """When the same provider has both an env var AND a DB row, the list
    should show the DB version (matches runtime resolver precedence at
    router_cache.py:58 `db_provider_keys.get(provider) or env_keys.get`).
    Showing both would suggest two simultaneous configurations exist; in
    reality only the DB one is used."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-version")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    await authed_client.put(
        "/v1/providers/openai",
        json={"api_key": "sk-db-version-overrides"},
    )

    r = await authed_client.get("/v1/providers")
    rows = r.json()["providers"]
    openai_rows = [p for p in rows if p["provider"] == "openai"]
    assert len(openai_rows) == 1, (
        f"db row must override env row, got duplicates: {openai_rows}"
    )
    assert openai_rows[0]["source"] == "db"
    assert openai_rows[0]["key_prefix"].startswith("sk-db-ve")


async def test_env_only_listing_when_no_db_rows(
    authed_client, monkeypatch,
):
    """Pure-env install (no dashboard PUTs ever): list still surfaces all
    configured providers."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-2")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    r = await authed_client.get("/v1/providers")
    providers = {p["provider"]: p for p in r.json()["providers"]}
    assert "openai" in providers and providers["openai"]["source"] == "env"
    assert "anthropic" in providers and providers["anthropic"]["source"] == "env"


async def test_delete_db_row_falls_back_to_env_value(
    authed_client, monkeypatch,
):
    """Operator workflow: env has a key, operator overrides via dashboard
    PUT, then later wants the env value back — DELETE the DB row and
    the listing should re-emerge with the env entry. Demonstrates the
    DB > env precedence layering works in both directions."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-baseline")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    # Step 1: env-only listing
    r = await authed_client.get("/v1/providers")
    rows = [p for p in r.json()["providers"] if p["provider"] == "openai"]
    assert len(rows) == 1
    assert rows[0]["source"] == "env"
    env_prefix = rows[0]["key_prefix"]

    # Step 2: operator PUTs a custom key — DB now wins
    await authed_client.put(
        "/v1/providers/openai",
        json={"api_key": "sk-db-custom-overrides-env"},
    )
    r = await authed_client.get("/v1/providers")
    rows = [p for p in r.json()["providers"] if p["provider"] == "openai"]
    assert len(rows) == 1
    assert rows[0]["source"] == "db"
    assert rows[0]["key_prefix"] != env_prefix

    # Step 3: operator deletes the DB row — env value re-emerges
    r = await authed_client.delete("/v1/providers/openai")
    assert r.status_code == 204

    r = await authed_client.get("/v1/providers")
    rows = [p for p in r.json()["providers"] if p["provider"] == "openai"]
    assert len(rows) == 1
    assert rows[0]["source"] == "env"
    assert rows[0]["key_prefix"] == env_prefix


async def test_delete_env_only_provider_returns_409_with_guidance(
    authed_client, monkeypatch,
):
    """Trying to DELETE a provider that exists ONLY in env (no DB row)
    must surface a 409 with actionable guidance — not a silent 204
    that misleads the operator into thinking the key is gone (the
    next page load would show it back, because env didn't change)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-only")
    from app import config as cfg
    cfg.get_settings.cache_clear()

    r = await authed_client.delete("/v1/providers/openai")
    assert r.status_code == 409
    # The app wraps HTTPException detail in `{error: {message, type}}` —
    # see middleware/error envelope.
    body = r.json()
    msg = body.get("error", {}).get("message") or body.get("detail") or ""
    assert "OPENAI_API_KEY" in msg, f"missing env var name in: {msg!r}"
    assert ".env" in msg, f"missing .env hint in: {msg!r}"


async def test_delete_unknown_provider_returns_404(authed_client):
    """No DB row, no env entry → straight 404 (not 409, the env-guidance
    path doesn't apply here)."""
    r = await authed_client.delete("/v1/providers/totally-fake-provider")
    assert r.status_code == 404
