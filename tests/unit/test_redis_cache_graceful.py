"""Regression: RedisCache must degrade gracefully on connection failure.

When Redis is unreachable, get() must return None (cache miss) and set()
must be a no-op. Neither should raise an exception that propagates to
the request handler — the cache is an optimization, not a correctness
requirement."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.prompt_cache import RedisCache


@pytest.mark.asyncio
async def test_redis_get_returns_none_on_connection_error():
    cache = RedisCache.__new__(RedisCache)
    cache._client = AsyncMock()
    cache._client.get = AsyncMock(side_effect=ConnectionError("Redis down"))

    result = await cache.get("test-key")
    assert result is None


@pytest.mark.asyncio
async def test_redis_set_noop_on_connection_error():
    cache = RedisCache.__new__(RedisCache)
    cache._client = AsyncMock()
    cache._client.set = AsyncMock(side_effect=ConnectionError("Redis down"))

    # Must not raise
    await cache.set("test-key", {"model": "gpt-4o"}, ttl=60)
    cache._client.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_get_returns_none_on_timeout():
    cache = RedisCache.__new__(RedisCache)
    cache._client = AsyncMock()
    cache._client.get = AsyncMock(side_effect=TimeoutError("Redis timeout"))

    result = await cache.get("test-key")
    assert result is None
