"""Cross-worker cache invalidation bus (issue #53).

Transport is Redis; the testable core is message parsing/dispatch and the
no-Redis no-op path. Both are exercised without a real Redis.
"""

from __future__ import annotations

import pytest

from app import cache_invalidation_bus as bus


def test_apply_invalidation_message_routes_to_local_invalidators(monkeypatch):
    router_hits: list[bool] = []
    metrics_hits: list[str | None] = []

    from app import quality_scores, router_cache

    monkeypatch.setattr(router_cache, "invalidate_router",
                        lambda: router_hits.append(True))
    monkeypatch.setattr(quality_scores, "invalidate_metrics_cache",
                        lambda wid=None: metrics_hits.append(wid))

    bus._apply_invalidation_message_locally("router")
    bus._apply_invalidation_message_locally("metrics")
    bus._apply_invalidation_message_locally("metrics:ws-1")
    bus._apply_invalidation_message_locally("garbage")  # unknown → ignored

    assert router_hits == [True]
    assert metrics_hits == [None, "ws-1"]


@pytest.mark.asyncio
async def test_broadcast_is_noop_publish_without_redis(monkeypatch):
    """No REDIS_URL → local invalidation still runs, publish is skipped."""
    monkeypatch.setattr(bus, "_configured_redis_url", lambda: None)
    bus._redis_publisher_client = None
    bus._redis_publisher_initialized = False

    router_hits: list[bool] = []
    from app import router_cache

    monkeypatch.setattr(router_cache, "invalidate_router",
                        lambda: router_hits.append(True))

    await bus.broadcast_router_cache_invalidation()  # must not raise

    assert router_hits == [True]
    assert await bus._get_redis_publisher_client() is None
