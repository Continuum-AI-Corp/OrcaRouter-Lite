"""Tests for iso_utc — the helper that fixes naive-ISO timezone bugs."""

from __future__ import annotations

from datetime import datetime, timezone

from app._time_util import iso_utc


def test_iso_utc_none_returns_none():
    assert iso_utc(None) is None


def test_iso_utc_naive_datetime_treated_as_utc():
    """SQLite's `server_default=func.now()` yields naive datetimes —
    we assume UTC (matches DB convention) and add the offset suffix.
    Without this, JS `new Date()` on the dashboard would interpret
    the string as local time and shift by the user's TZ offset."""
    dt = datetime(2026, 5, 5, 13, 24, 59)  # naive
    out = iso_utc(dt)
    assert out is not None
    assert out.endswith("+00:00"), f"missing UTC suffix: {out!r}"
    assert "2026-05-05T13:24:59" in out


def test_iso_utc_aware_datetime_passthrough():
    """Postgres timestamptz columns return aware datetimes — leave
    them alone, just emit canonical ISO with the existing offset."""
    dt = datetime(2026, 5, 5, 13, 24, 59, tzinfo=timezone.utc)
    out = iso_utc(dt)
    assert out is not None
    assert out.endswith("+00:00")
    assert "2026-05-05T13:24:59" in out


def test_iso_utc_round_trip_parses_as_utc_in_python():
    """The output must round-trip back to the same UTC instant. JS
    `new Date(s).getTime()` should produce the same epoch ms as
    Python's `datetime.fromisoformat(s).timestamp() * 1000` — that's
    only true if the offset is explicit."""
    original = datetime(2026, 5, 5, 13, 24, 59, tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(iso_utc(original))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed == original
