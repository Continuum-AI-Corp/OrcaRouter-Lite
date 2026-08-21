"""Both last-resort error paths must emit a structured-log event.

Before the fix, the catch-all 500 handler and the auth middleware's
generic-exception 503 branch discarded the exception silently, making
production incidents undebuggable.
"""

from __future__ import annotations

import structlog
import structlog.testing


async def test_unhandled_exception_handler_returns_envelope_and_logs():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.main import unhandled_exception_handler

    app = FastAPI()
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    # ServerErrorMiddleware sends the handler's response and then re-raises
    # to the transport by design, so the client must not re-raise either.
    with structlog.testing.capture_logs() as cap:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/boom")

    assert r.status_code == 500
    assert r.json()["error"] == {"message": "Internal server error", "type": "server_error"}

    events = [e for e in cap if e.get("event") == "unhandled_exception"]
    assert events, "expected an unhandled_exception log event"
    assert events[0]["path"].endswith("/boom")
    assert events[0].get("exc_info") is not None


async def test_auth_middleware_db_failure_returns_503_and_logs(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.middleware.auth import AuthMiddleware
    from packages.db import session as session_mod

    class _ExplodingFactory:
        async def __aenter__(self):
            raise ConnectionError("db gone")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(session_mod, "_session_factory", lambda: _ExplodingFactory())

    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/v1/anything")
    async def anything():
        return {"ok": True}

    with structlog.testing.capture_logs() as cap:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://t",
            headers={"Authorization": "Bearer sk-orca-somekey"},
        ) as c:
            r = await c.get("/v1/anything")

    assert r.status_code == 503
    assert r.json()["error"]["type"] == "server_error"

    events = [e for e in cap if e.get("event") == "auth_middleware_error"]
    assert events, "expected auth_middleware_error to be logged"
