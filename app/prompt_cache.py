"""Cross-provider prompt cache.

LiteLLM only does prompt caching for Anthropic. This module ships an
exact-match cache that works for any provider — same request inputs →
cached response, no upstream call. "Same inputs" means every parameter
that shapes the completion (see `cache_key`), not just the prompt.

Two backends, picked at startup:
  - Redis (when REDIS_URL is set) — survives restarts, works across pods.
  - InMemoryCache LRU — single-pod default; no infra deps.

Cache hits are surfaced via the `x-orca-cache: HIT` response header AND
the `cached: true` field on the returned dict. Misses get
`x-orca-cache: MISS`.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Protocol

_DEFAULT_TTL_SECONDS = 3600  # 1 hour


def cache_key(
    *,
    model: str,
    messages: list[dict],
    temperature: float | None,
    tools: list[dict] | None,
    response_format: dict | None,
    seed: int | None,
    max_tokens: int | None = None,
    stop: str | list[str] | None = None,
    tool_choice: str | dict | None = None,
    top_p: float | None = None,
    n: int | None = None,
    presence_penalty: float | None = None,
    frequency_penalty: float | None = None,
    logit_bias: dict[int, float] | None = None,
) -> str:
    """Deterministic SHA-256 key over every input that shapes the output.

    All the output-shaping parameters belong here, not just the prompt:
    two requests that differ only in `max_tokens` (64 vs 4096), `stop`, or
    `tool_choice` (auto vs a forced function) produce genuinely different
    completions, so sharing one cache entry between them would serve a
    truncated answer, or prose where the caller demanded a tool call. The
    native Anthropic surface sends `max_tokens` on every request and both
    native surfaces pass stop/tool_choice through, so a narrower key is
    reachable in normal use.

    The payload carries `"v": 2` so pre-v2 entries (six fields, omitted
    temperature coerced to 0.0) can never match.

    `user` is deliberately excluded: it is an abuse-monitoring hint that
    does not change the completion, and keying on it would fragment the
    cache per caller for no correctness gain.
    """
    payload = {
        # v2: original key hashed only six fields, so e.g. max_tokens=16
        # collided with max_tokens=4000. The version field keeps those
        # entries from ever matching this key space.
        "v": 2,
        "model": model,
        "messages": messages,
        # Keyed on the true wire value: an ABSENT temperature is not the
        # same computation as an explicit 0. Both are cacheable when a
        # seed pins them, but the upstream defaults an absent one to 1.0
        # (a seeded sample) while 0 is the greedy argmax — normalizing
        # None to 0.0 here would serve one caller the other's response.
        "temperature": temperature,
        "tools": tools or None,
        "response_format": response_format or None,
        "seed": seed,
        "max_tokens": max_tokens,
        # Normalize stop to a list: "stop": "foo" and "stop": ["foo"]
        # produce the same upstream behavior, so they must share a cache
        # entry. Without this, a string-vs-list difference fragments the
        # cache for semantically identical requests.
        "stop": [stop] if isinstance(stop, str) else stop,
        "tool_choice": tool_choice,
        "top_p": top_p,
        "n": n,
        # Both shift the logits before decoding, so they change the output
        # even at temperature 0 — exactly when a request is cacheable.
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "logit_bias": logit_bias,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def is_cacheable(body: dict) -> bool:
    """A request is cacheable iff its output is deterministic.

    - Streaming responses are skipped (caching SSE chunks correctly is more
      trouble than it's worth for v1).
    - With an explicit seed, any sampling params are fine — the seed pins
      the output.
    - Otherwise temperature must be EXPLICITLY zero AND top_p must not
      narrow the distribution. An OMITTED temperature means the provider
      default (1.0 — maximally non-deterministic), never cacheable. A
      narrowed top_p samples from a truncated distribution even at
      temperature 0, so it is also not cacheable without a seed.
    """
    if body.get("stream"):
        return False
    if body.get("seed") is not None:
        return True
    if body.get("temperature") != 0:
        return False
    top_p = body.get("top_p")
    if top_p is not None and top_p != 1:
        return False
    return True


# ── Backends ──────────────────────────────────────────────────────────


class CacheBackend(Protocol):
    async def get(self, key: str) -> dict | None: ...
    async def set(self, key: str, value: dict, ttl: int) -> None: ...


class InMemoryCache:
    """Simple LRU with TTL — fine for single-pod docker-compose."""

    def __init__(self, max_size: int = 1000, _now=None):
        self._max = max_size
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        # Indirection so tests can advance time without sleeping.
        self._now = _now or time.time

    async def get(self, key: str) -> dict | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._now() >= expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: dict, ttl: int) -> None:
        self._store[key] = (self._now() + ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)


class RedisCache:
    """Redis-backed cache; activated when REDIS_URL is set.

    Connection errors are caught and logged — a Redis outage degrades to
    cache misses rather than crashing every request. The cache is an
    optimization, not a correctness requirement; the upstream call still
    succeeds when Redis is down."""

    def __init__(self, url: str):
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> dict | None:
        try:
            raw = await self._client.get(f"orca:cache:{key}")
        except Exception:
            # Redis down — degrade to cache miss. The caller will hit the
            # upstream and (on success) repopulate via set().
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set(self, key: str, value: dict, ttl: int) -> None:
        try:
            await self._client.set(
                f"orca:cache:{key}",
                json.dumps(value, separators=(",", ":")),
                ex=ttl,
            )
        except Exception:
            # Redis down — skip the write. The next request will hit the
            # upstream again and retry the cache write.
            pass


# ── Module singleton ──────────────────────────────────────────────────

_backend: CacheBackend | None = None


def get_backend() -> CacheBackend:
    """Resolve the cache backend lazily on first call."""
    global _backend
    if _backend is not None:
        return _backend

    from app.config import get_settings

    settings = get_settings()
    if settings.redis_url:
        try:
            _backend = RedisCache(settings.redis_url)
            return _backend
        except Exception:
            pass
    _backend = InMemoryCache(max_size=1000)
    return _backend


def reset_backend() -> None:
    """Force re-resolution on next get_backend() — for tests."""
    global _backend
    _backend = None
