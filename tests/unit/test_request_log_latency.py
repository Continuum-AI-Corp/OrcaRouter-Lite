"""_build_log_row latency resolution.

Streaming and cache-hit paths emit synthetic _orca_meta without (or with a
literal-zero) latency; the row must then carry the measured wall-clock time.
Adapter-supplied non-stream meta keeps precedence.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.routes.chat import _build_log_row

_KC = SimpleNamespace(workspace_id="default", key_id="k-1")
_BODY = SimpleNamespace(stream=False)


def _row(meta: dict | None, *, stream: bool = False):
    response = {"model": "m", "usage": {}}
    if meta is not None:
        response["_orca_meta"] = meta
    return _build_log_row(
        body=SimpleNamespace(stream=stream),
        kc=_KC,
        response=response,
        status_code=200,
        error_type=None,
        started_perf=0.0,
        strategy="balanced",
        requested_model="m",
        actual_resolved="m",
    )


async def test_adapter_supplied_latency_wins():
    row = await _row({"provider": "openai", "latency_ms": 4321})
    assert row.latency_ms == 4321


async def test_zero_latency_falls_back_to_measured():
    # The streaming aggregator emits a literal 0 — it must not win.
    row = await _row({"provider": "openai", "latency_ms": 0})
    assert row.latency_ms > 0


async def test_missing_latency_key_uses_measured():
    row = await _row({"provider": "openai"})
    assert row.latency_ms > 0


async def test_no_meta_at_all_uses_measured():
    assert (await _row(None)).latency_ms > 0


async def test_streaming_synthetic_meta_logs_real_latency():
    """Regression: the exact shape produced by the SSE _finalize() path."""
    row = await _row({"provider": "unknown", "latency_ms": 0}, stream=True)
    assert row.latency_ms > 0
