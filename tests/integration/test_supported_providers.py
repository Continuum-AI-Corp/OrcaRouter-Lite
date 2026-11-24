"""GET /v1/providers/supported — one provider list for setup and the
dashboard, so the two can't drift apart again."""

from __future__ import annotations

import pytest

from tests.integration.test_desktop_api import _auth, _client, seeded  # noqa: F401  (fixtures)


@pytest.fixture
def providers_app(db_session, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", str(db_session.bind.url))
    from fastapi import FastAPI

    from app.middleware.auth import AuthMiddleware
    from app.routes import providers
    from tests.integration.test_desktop_api import _patch_sessions

    _patch_sessions(monkeypatch, db_session)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(providers.router)
    return app


ORDER = ["orcarouter", "anthropic", "openai", "google", "deepseek", "xai", "mistral", "groq", "together",
         "fireworks", "cohere", "moonshot", "qwen", "minimax", "zai", "openrouter"]


async def test_supported_providers_in_display_order(providers_app, seeded):
    root, restricted = seeded
    async with _client(providers_app) as c:
        r = await c.get("/v1/providers/supported", headers=_auth(restricted))  # any valid key
        unauth = await c.get("/v1/providers/supported")
    assert unauth.status_code == 401
    assert r.status_code == 200, r.text
    providers = r.json()["providers"]
    assert [p["id"] for p in providers] == ORDER
    by_id = {p["id"]: p for p in providers}
    for p in providers:
        assert {"id", "name", "key_hint", "env_var", "docs_url", "checkable", "new"} <= set(p)
    assert by_id["orcarouter"]["hosted"] is True
    assert by_id["moonshot"] == {**by_id["moonshot"], "name": "Moonshot (Kimi)", "env_var": "MOONSHOT_API_KEY",
                                 "new": True, "checkable": True}
    assert by_id["qwen"]["env_var"] == "DASHSCOPE_API_KEY"
    assert by_id["minimax"]["checkable"] is False
    assert {p["id"] for p in providers if p["new"]} == {"moonshot", "qwen", "minimax", "zai", "openrouter"}
    assert by_id["anthropic"]["key_hint"].startswith("sk-ant-")
