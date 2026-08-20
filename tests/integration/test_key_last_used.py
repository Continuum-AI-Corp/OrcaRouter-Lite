import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app
from app.seed import seed_initial_state
from packages.db import session as session_mod
from packages.db.models.api_key import ApiKey


@pytest.mark.asyncio
async def test_api_key_last_used_at_is_persisted(tmp_sqlite_url, monkeypatch):
    """Verify that last_used_at is committed to DB when an API key is used."""
    monkeypatch.setenv("DATABASE_URL", tmp_sqlite_url)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from packages.db.engine import build_engine
    from packages.db.models.base import Base

    engine = build_engine(tmp_sqlite_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    session_mod._session_factory = factory

    async with factory() as s:
        seed = await seed_initial_state(s)

    app = create_app()

    # 1. Verify initially last_used_at is None
    async with factory() as s:
        key_row = (await s.execute(select(ApiKey))).scalars().first()
        assert key_row.last_used_at is None, "Initially last_used_at should be None"

    # 2. Make an authenticated HTTP request using the key
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://t",
        headers={"Authorization": f"Bearer {seed.api_key}"},
    ) as client:
        response = await client.get("/v1/models")
        assert response.status_code == 200

    # 3. Query DB to check if last_used_at was updated and committed
    async with factory() as s:
        key_row = (await s.execute(select(ApiKey))).scalars().first()

    # If the bug exists (missing session.commit() in validate_api_key):
    # key_row.last_used_at is still None!
    # Expected correct behavior: key_row.last_used_at is NOT None
    assert key_row.last_used_at is not None, "ApiKey last_used_at was not committed to DB!"
