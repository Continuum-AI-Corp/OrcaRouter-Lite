"""Cross-worker cache invalidation over Redis pub/sub (issue #53).

The Lite default (1 uvicorn worker) keeps the router client + metrics
caches process-local, and a mutation route dropping its own cache is
enough. Under multiple workers / k8s replicas each process has its own
RAM heap, so a mutation only invalidates the worker that served the
request — siblings keep serving a stale router client (e.g. an old
provider key) or stale metrics until their own TTL / a restart.

When ``REDIS_URL`` is set, every mutation route broadcasts a plain-string
invalidation message on one channel and a per-worker background listener
applies it locally. No Redis configured → every broadcast is a no-op and
behavior is exactly the single-worker path. This module is transport
only: it reuses the existing local ``invalidate_*()`` functions.

Deliberately one channel + string messages, no generic bus. Add a message
schema / more targets only when a third cache needs invalidating.
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog

_INVALIDATION_CHANNEL = "orca:invalidate"
_ROUTER_CACHE_MESSAGE = "router"
_METRICS_CACHE_MESSAGE = "metrics"

log = structlog.get_logger()

_redis_publisher_client = None  # lazily-created redis client for PUBLISH
_redis_publisher_initialized = False
_invalidation_listener_task: asyncio.Task | None = None
_invalidation_listener_connection = None


def _configured_redis_url() -> str | None:
    from app.config import get_settings

    return get_settings().redis_url


# ── Broadcast (mutation side: drop locally + tell sibling workers) ─────────


async def broadcast_router_cache_invalidation() -> None:
    """Drop this worker's router cache and tell sibling workers to do the same."""
    from app import router_cache

    router_cache.invalidate_router()
    await _publish_invalidation_message(_ROUTER_CACHE_MESSAGE)


async def broadcast_metrics_cache_invalidation(workspace_id: str | None = None) -> None:
    """Drop this worker's metrics cache and tell sibling workers to do the same.

    ``workspace_id=None`` clears every workspace (mirrors
    ``invalidate_metrics_cache``).
    """
    from app.quality_scores import invalidate_metrics_cache

    invalidate_metrics_cache(workspace_id)
    await _publish_invalidation_message(
        _METRICS_CACHE_MESSAGE
        if workspace_id is None
        else f"{_METRICS_CACHE_MESSAGE}:{workspace_id}"
    )


# ── Publisher ─────────────────────────────────────────────────────────────


async def _get_redis_publisher_client():
    global _redis_publisher_client, _redis_publisher_initialized
    if _redis_publisher_initialized:
        return _redis_publisher_client
    _redis_publisher_initialized = True
    redis_url = _configured_redis_url()
    if not redis_url:
        return None
    try:
        import redis.asyncio as aioredis

        # Tight timeouts: publish runs inside mutation requests, and an
        # unreachable Redis must degrade to a logged warning, not stall
        # the request for the OS TCP timeout.
        _redis_publisher_client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
    except Exception as exc:  # redis extra not installed / bad url
        log.warning("invalidation_publisher_unavailable", error=str(exc))
        _redis_publisher_client = None
    return _redis_publisher_client


async def _publish_invalidation_message(message: str) -> None:
    client = await _get_redis_publisher_client()
    if client is None:
        return
    try:
        await client.publish(_INVALIDATION_CHANNEL, message)
    except Exception as exc:  # never fail a mutation on a bus hiccup
        log.warning("invalidation_publish_failed", error=str(exc), message=message)


# ── Listener (subscriber side: local invalidation only, never re-publish) ──


def _apply_invalidation_message_locally(message: str) -> None:
    """Apply a received invalidation message to this worker's local caches."""
    from app import router_cache
    from app.quality_scores import invalidate_metrics_cache

    if message == _ROUTER_CACHE_MESSAGE:
        router_cache.invalidate_router()
    elif message == _METRICS_CACHE_MESSAGE:
        invalidate_metrics_cache(None)
    elif message.startswith(_METRICS_CACHE_MESSAGE + ":"):
        invalidate_metrics_cache(message.split(":", 1)[1])
    else:
        log.warning("invalidation_unknown_message", message=message)


async def _subscribe_and_apply_invalidations(redis_url: str) -> None:
    import redis.asyncio as aioredis

    global _invalidation_listener_connection
    backoff = 1.0
    while True:
        try:
            # No socket_timeout here: the pubsub read blocks while the
            # channel is idle, and a read timeout would churn the loop.
            _invalidation_listener_connection = aioredis.from_url(
                redis_url, decode_responses=True, socket_connect_timeout=5
            )
            pubsub = _invalidation_listener_connection.pubsub()
            await pubsub.subscribe(_INVALIDATION_CHANNEL)
            log.info("invalidation_listener_ready", channel=_INVALIDATION_CHANNEL)
            backoff = 1.0
            async for msg in pubsub.listen():
                if msg.get("type") == "message":
                    _apply_invalidation_message_locally(msg["data"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A dropped connection must not silently strand this worker on
            # stale caches — reconnect, backing off so a long Redis outage
            # doesn't spam a warning per second.
            log.warning("invalidation_listener_error", error=str(exc),
                        retry_in_s=backoff)
            if _invalidation_listener_connection is not None:
                with contextlib.suppress(Exception):
                    await _invalidation_listener_connection.aclose()
                _invalidation_listener_connection = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def start_invalidation_listener() -> None:
    """Spawn the per-worker background listener. No-op without REDIS_URL."""
    global _invalidation_listener_task
    redis_url = _configured_redis_url()
    if not redis_url or _invalidation_listener_task is not None:
        return
    try:
        import redis.asyncio  # noqa: F401 — fail fast if the extra is missing
    except Exception as exc:
        log.warning("invalidation_listener_unavailable", error=str(exc))
        return
    _invalidation_listener_task = asyncio.create_task(
        _subscribe_and_apply_invalidations(redis_url)
    )


async def stop_invalidation_listener() -> None:
    """Cancel the listener and close both connections (lifespan shutdown)."""
    global _invalidation_listener_task, _invalidation_listener_connection
    global _redis_publisher_client, _redis_publisher_initialized
    if _invalidation_listener_task is not None:
        _invalidation_listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _invalidation_listener_task
        _invalidation_listener_task = None
    if _invalidation_listener_connection is not None:
        with contextlib.suppress(Exception):
            await _invalidation_listener_connection.aclose()
        _invalidation_listener_connection = None
    if _redis_publisher_client is not None:
        with contextlib.suppress(Exception):
            await _redis_publisher_client.aclose()
    _redis_publisher_client = None
    _redis_publisher_initialized = False
