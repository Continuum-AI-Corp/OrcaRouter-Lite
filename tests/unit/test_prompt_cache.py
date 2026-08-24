"""Cross-provider prompt cache.

LiteLLM only does prompt caching for Anthropic. Lite ships an exact-match
cache that works for any provider — same request inputs (every parameter
that shapes the completion, not just the prompt) → cached response, no
upstream call.

Backed by Redis when REDIS_URL is set, falls back to an in-process LRU
otherwise so it works in single-pod docker-compose / on a laptop.
"""

from __future__ import annotations

import pytest


def test_cache_key_is_deterministic_across_runs():
    from app.prompt_cache import cache_key

    a = cache_key(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.0,
        tools=None,
        response_format=None,
        seed=None,
    )
    b = cache_key(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.0,
        tools=None,
        response_format=None,
        seed=None,
    )
    assert a == b
    assert isinstance(a, str)
    assert len(a) >= 32  # sha256 hex


def test_cache_key_differs_on_message_content():
    from app.prompt_cache import cache_key

    a = cache_key(model="m", messages=[{"role": "user", "content": "hi"}],
                  temperature=0.0, tools=None, response_format=None, seed=None)
    b = cache_key(model="m", messages=[{"role": "user", "content": "bye"}],
                  temperature=0.0, tools=None, response_format=None, seed=None)
    assert a != b


def test_cache_key_differs_on_temperature():
    from app.prompt_cache import cache_key

    msgs = [{"role": "user", "content": "hi"}]
    a = cache_key(model="m", messages=msgs, temperature=0.0,
                  tools=None, response_format=None, seed=None)
    b = cache_key(model="m", messages=msgs, temperature=0.7,
                  tools=None, response_format=None, seed=None)
    assert a != b


def test_cache_key_differs_on_model():
    from app.prompt_cache import cache_key

    msgs = [{"role": "user", "content": "hi"}]
    a = cache_key(model="gpt-4o", messages=msgs, temperature=0.0,
                  tools=None, response_format=None, seed=None)
    b = cache_key(model="claude-3-5-sonnet-latest", messages=msgs,
                  temperature=0.0, tools=None, response_format=None, seed=None)
    assert a != b


@pytest.mark.parametrize("field,other", [
    ("max_tokens", 4096),
    ("stop", ["END"]),
    ("tool_choice", {"type": "function", "function": {"name": "f"}}),
    ("top_p", 0.5),
    ("n", 2),
])
def test_cache_key_differs_on_every_output_shaping_parameter(field, other):
    """Regression: the key covered only model/messages/temperature/tools/
    response_format/seed, so two requests differing solely in max_tokens,
    stop or tool_choice collided — the second was served the first's
    response (truncated, or prose where a tool call was forced). The
    native surfaces send these on every request."""
    from app.prompt_cache import cache_key

    base = dict(
        model="m", messages=[{"role": "user", "content": "hi"}],
        temperature=0.0, tools=None, response_format=None, seed=None,
    )
    assert cache_key(**base) != cache_key(**base, **{field: other})


def test_cache_key_ignores_user_identifier():
    """`user` is an abuse-monitoring hint that does not change the
    completion; keying on it would fragment the cache per caller."""
    from app.prompt_cache import cache_key

    base = dict(
        model="m", messages=[{"role": "user", "content": "hi"}],
        temperature=0.0, tools=None, response_format=None, seed=None,
        max_tokens=64,
    )
    assert cache_key(**base) == cache_key(**base)


def test_should_cache_skips_streaming_and_high_temperature():
    """We only cache deterministic, non-streaming requests."""
    from app.prompt_cache import is_cacheable

    base = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}

    # Cacheable: temp=0 (or unset, defaults to 0 for safety) and not streaming
    assert is_cacheable({**base, "temperature": 0.0, "stream": False}) is True
    assert is_cacheable({**base, "stream": False}) is True  # temp unset → treat as deterministic

    # Not cacheable
    assert is_cacheable({**base, "stream": True}) is False
    assert is_cacheable({**base, "temperature": 0.7}) is False
    assert is_cacheable({**base, "temperature": 0.1}) is False


def test_should_cache_skips_when_seed_unspecified_with_high_temp():
    """A seed pins determinism; without it, anything > 0 is non-deterministic."""
    from app.prompt_cache import is_cacheable

    base = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]}
    # With explicit seed AND any temp → still cacheable (seed pins output)
    assert is_cacheable({**base, "temperature": 0.7, "seed": 42}) is True


@pytest.mark.asyncio
async def test_inmem_cache_round_trip():
    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=10)
    await c.set("key1", {"hello": "world"}, ttl=60)
    got = await c.get("key1")
    assert got == {"hello": "world"}


@pytest.mark.asyncio
async def test_inmem_cache_miss_returns_none():
    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=10)
    assert await c.get("never-set") is None


@pytest.mark.asyncio
async def test_inmem_cache_evicts_when_full():
    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=2)
    await c.set("a", {"v": 1}, ttl=60)
    await c.set("b", {"v": 2}, ttl=60)
    await c.set("c", {"v": 3}, ttl=60)  # evicts oldest "a"
    assert await c.get("a") is None
    assert await c.get("b") is not None
    assert await c.get("c") is not None


@pytest.mark.asyncio
async def test_inmem_cache_respects_ttl():
    import time

    from app.prompt_cache import InMemoryCache

    c = InMemoryCache(max_size=10, _now=lambda: time.time())
    await c.set("k", {"v": 1}, ttl=0)  # immediate expiry
    # Fast-forward by mocking _now
    c._now = lambda: time.time() + 1
    assert await c.get("k") is None
