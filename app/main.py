"""FastAPI app factory for orcarouter-lite.

The lifespan handler runs migrations + seed once on startup. Tests skip
the full lifespan and pre-create tables themselves.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def _find_design_dir() -> str | None:
    """Locate the dashboard SPA. Three layouts have to work:

      * ``$ORCA_DESIGN_DIR``   — explicit override (custom build of the SPA)
      * ``app/design``         — installed wheel; pyproject force-includes the
                                 repo-root ``design/`` tree to this path
      * ``../design``          — repo checkout and the Docker image
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.environ.get("ORCA_DESIGN_DIR"),
        os.path.join(here, "design"),
        os.path.join(here, os.pardir, "design"),
    ):
        if candidate and os.path.isdir(candidate):
            return candidate
    return None


def _find_desktop_ui_dir() -> str | None:
    """Locate the Orca app's UI (desktop/ui in a checkout, app/desktop_ui in a wheel)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.environ.get("ORCA_DESKTOP_UI_DIR"),
        os.path.join(here, "desktop_ui"),
        os.path.join(here, os.pardir, "desktop", "ui"),
    ):
        if candidate and os.path.isfile(os.path.join(candidate, "panel.html")):
            return candidate
    return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    update_task: asyncio.Task | None = None

    from app.config import get_settings
    from packages.db import session as session_mod
    from packages.db.engine import dispose_engine, get_engine, redacted_url
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
    # Redact: on the documented Postgres path the raw URL carries the DB
    # password, and structured logs are retained by hosted aggregators.
    log.info("lite_starting", database_url=redacted_url(settings.database_url))

    engine = get_engine(settings.database_url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # create_all only makes missing tables, never alters existing ones. Bring
    # existing deployments (SQLite volume, Postgres) up to date with columns added
    # after their initial release so they don't 503 on the new ORM columns.
    from packages.db.migrate import ensure_budget_columns

    await ensure_budget_columns(engine)

    # Fail closed before any traffic can be served: refuse to boot when
    # provider credentials are (or would be) sealed with the publicly-known
    # dev encryption key. Runs after create_all so a fresh database's empty
    # provider_keys table counts as "no credentials at risk".
    from packages.db.guards import (
        assert_credential_encryption_ready,
        audit_stored_provider_credentials,
    )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    await assert_credential_encryption_ready(
        make_session=session_factory,
        database_url=settings.database_url,
        allow_insecure_dev_key=settings.allow_insecure_dev_key,
        engine=engine,
    )

    # Surface rotated/corrupt ciphertext instead of letting the router
    # silently drop those rows. Re-encrypts when the previous key is set.
    audit = await audit_stored_provider_credentials(
        make_session=session_factory,
        previous_key=settings.credential_encryption_previous_key,
    )
    if audit.reencrypted:
        log.warning("reencrypted_provider_keys", providers=list(audit.reencrypted))
    if audit.undecryptable:
        log.error(
            "undecryptable_provider_keys",
            providers=list(audit.undecryptable),
        )

    session_mod._session_factory = session_factory

    from app.seed import seed_initial_state

    async with session_mod._session_factory() as s:
        seed = await seed_initial_state(s)
        # The desktop app uses its own key (app.key); printing the seed admin
        # key would leave a working credential in the app's engine.log.
        if seed.created and seed.api_key and not settings.orca_desktop_mode:
            # No key material in the structured event: logs are retained by
            # aggregators. The print() below is the one-time delivery channel.
            log.info("seed_complete", workspace_id=seed.workspace_id)
            try:
                print(f"\n  ✓ orcarouter-lite ready. API key: {seed.api_key}\n")
            except UnicodeEncodeError:
                # Non-UTF-8 consoles (e.g. GBK-codepage Windows) can't
                # encode "✓" — the banner must never kill startup.
                print(f"\n  orcarouter-lite ready. API key: {seed.api_key}\n")

    if settings.orca_desktop_mode and settings.host not in LOOPBACK_HOSTS:
        log.error("desktop_mode_refused", host=settings.host, reason="desktop mode only runs on 127.0.0.1")
    elif settings.orca_desktop_mode:
        # The desktop app and `orca` CLI authenticate with a key kept in the
        # engine's home folder, so the user never copies one by hand.
        from pathlib import Path

        from packages.desktop.home import default_home, ensure_app_key

        desktop_home = Path(settings.orca_home).expanduser() if settings.orca_home else default_home()
        async with session_mod._session_factory() as s:
            await ensure_app_key(s, desktop_home)
        log.info("desktop_mode", home=str(desktop_home))

        from packages.desktop import updates

        if updates.UpdateChecker.enabled():
            update_task = asyncio.create_task(updates.CHECKER.run_forever(), name="orca-update-check")

    from app import cache_invalidation_bus

    await cache_invalidation_bus.start_invalidation_listener()

    log.info("lite_ready")
    yield

    log.info("lite_shutting_down")
    if update_task is not None:
        update_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await update_task
    await cache_invalidation_bus.stop_invalidation_listener()
    await dispose_engine()


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def create_app() -> FastAPI:
    from app.config import get_settings

    desktop = get_settings().orca_desktop_mode
    # The desktop engine serves pages that hold the app key, so it loads no
    # third-party scripts: the interactive docs (CDN assets) are off.
    docs = {} if not desktop else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(
        title="OrcaRouter Lite",
        description="Open Source. Single Tenant. Self-hosted LLM router with a managed safety net.",
        version="0.1.0",
        lifespan=lifespan,
        **docs,
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
        responses_compat,
        routing,
    )

    app.include_router(health.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(anthropic_compat.router)
    app.include_router(gemini_compat.router)
    app.include_router(responses_compat.router)
    app.include_router(analytics.router)
    app.include_router(models.router)
    app.include_router(keys.router)
    app.include_router(routing.router)
    app.include_router(hosted.router)
    app.include_router(quality.router)

    # The desktop API edits files in the user's home directory, so it only
    # exists when `orca up` started this engine on the user's own machine,
    # listening on loopback. Desktop mode on a network host mounts nothing.
    if desktop and get_settings().host in LOOPBACK_HOSTS:
        from app.routes import desktop as desktop_routes

        app.include_router(desktop_routes.router)
        app.include_router(desktop_routes.identity_router)

        ui_dir = _find_desktop_ui_dir()
        if ui_dir:
            from fastapi.staticfiles import StaticFiles

            app.mount("/desktop", StaticFiles(directory=ui_dir, html=True), name="desktop")

    # ── Static SPA (provider keys, routing, analytics, keys) ──
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    design_dir = _find_design_dir()
    if design_dir:
        app.mount("/static", StaticFiles(directory=design_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def root():
            index = os.path.join(design_dir, "index.html")
            if os.path.isfile(index):
                return FileResponse(index, media_type="text/html")
            return RedirectResponse("/health")

    return app


app = create_app()
