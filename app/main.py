"""FastAPI app factory for orcarouter-lite.

The lifespan handler runs migrations + seed once on startup. Tests skip
the full lifespan and pre-create tables themselves.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.config import get_settings
    from packages.db import session as session_mod
    from packages.db.engine import dispose_engine, get_engine
    from packages.db.models.base import Base

    settings = get_settings()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper())
        ),
    )
    log = structlog.get_logger()
    log.info("lite_starting", database_url=settings.database_url)

    engine = get_engine(settings.database_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Fail closed before any traffic can be served: refuse to boot when
    # provider credentials are (or would be) sealed with the publicly-known
    # dev encryption key. Runs after create_all so a fresh database's empty
    # provider_keys table counts as "no credentials at risk".
    from packages.db.guards import assert_credential_encryption_ready

    await assert_credential_encryption_ready(
        make_session=async_sessionmaker(engine, expire_on_commit=False),
        database_url=settings.database_url,
        allow_insecure_dev_key=settings.allow_insecure_dev_key,
    )

    session_mod._session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from app.seed import seed_initial_state

    async with session_mod._session_factory() as s:
        seed = await seed_initial_state(s)
        if seed.created and seed.api_key:
            log.info("seed_complete", api_key=seed.api_key)
            try:
                print(f"\n  ✓ orcarouter-lite ready. API key: {seed.api_key}\n")
            except UnicodeEncodeError:
                # Non-UTF-8 consoles (e.g. GBK-codepage Windows) can't
                # encode "✓" — the banner must never kill startup.
                print(f"\n  orcarouter-lite ready. API key: {seed.api_key}\n")

    from app import cache_invalidation_bus

    await cache_invalidation_bus.start_invalidation_listener()

    log.info("lite_ready")
    yield

    log.info("lite_shutting_down")
    await cache_invalidation_bus.stop_invalidation_listener()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="OrcaRouter Lite",
        description="Open Source. Single Tenant. Self-hosted LLM router with a managed safety net.",
        version="0.1.0",
        lifespan=lifespan,
    )

    def _native_error(request, status: int, message: str) -> JSONResponse | None:
        """The native surfaces promise their own error envelope on every
        non-200. Failures that never reach a route body — an unknown
        /v1beta path, a 405 on GET /v1/messages, a validation error on a
        native route — land in these app-wide handlers, so they must speak
        the caller's protocol too (same signals the auth middleware uses)."""
        from app.middleware.auth import protocol_for_scope

        protocol = protocol_for_scope(request.scope)
        if protocol == "anthropic":
            from app.protocols import anthropic as proto

            return proto.error_response(status, message)
        if protocol == "gemini":
            from app.protocols import gemini as proto

            return proto.error_response(status, message)
        return None

    # Registered on Starlette's base class: routing-level 404/405 are raised
    # as starlette.exceptions.HTTPException, which a handler keyed on the
    # FastAPI subclass never sees (they would fall to Starlette's bare
    # {"detail": ...} body — neither envelope).
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request, exc: StarletteHTTPException):
        native = _native_error(request, exc.status_code, str(exc.detail))
        if native is not None:
            return native
        type_map = {
            401: "auth_error",
            403: "forbidden",
            404: "not_found",
            422: "validation_error",
            429: "rate_limit_error",
            503: "upstream_error",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "message": exc.detail,
                    "type": type_map.get(exc.status_code, "server_error"),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def val_exc_handler(request, exc: RequestValidationError):
        msg = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        native = _native_error(request, 422, msg)
        if native is not None:
            return native
        return JSONResponse(
            status_code=422,
            content={"error": {"message": msg, "type": "validation_error"}},
        )

    @app.exception_handler(Exception)
    async def unhandled(request, exc: Exception):
        native = _native_error(request, 500, "Internal server error")
        if native is not None:
            return native
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": "Internal server error",
                    "type": "server_error",
                }
            },
        )

    from app.middleware.auth import AuthMiddleware

    app.add_middleware(AuthMiddleware)

    from app.routes import (
        analytics,
        anthropic_compat,
        chat,
        gemini_compat,
        health,
        hosted,
        keys,
        models,
        providers,
        quality,
        routing,
    )

    app.include_router(health.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(anthropic_compat.router)
    app.include_router(gemini_compat.router)
    app.include_router(analytics.router)
    app.include_router(models.router)
    app.include_router(keys.router)
    app.include_router(routing.router)
    app.include_router(hosted.router)
    app.include_router(quality.router)

    # ── Static SPA (provider keys, routing, analytics, keys) ──
    import os

    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    design_dir = os.path.join(os.path.dirname(__file__), "..", "design")
    if os.path.isdir(design_dir):
        app.mount("/static", StaticFiles(directory=design_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def root():
            index = os.path.join(design_dir, "index.html")
            if os.path.isfile(index):
                return FileResponse(index, media_type="text/html")
            return RedirectResponse("/health")

    return app


app = create_app()
