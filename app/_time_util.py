"""Tiny helpers for serializing datetimes to ISO 8601 with explicit UTC.

Why this exists: the DB columns use `server_default=func.now()` which
yields naive UTC datetimes on SQLite (no tzinfo) and timezone-aware
UTC on Postgres. Calling `.isoformat()` directly emits a naive string
on SQLite (`2026-05-05T13:24:59`), and JavaScript's `new Date()`
parses that as **local time**, not UTC. Result: dashboards in any
non-UTC timezone show timestamps shifted by the TZ offset (e.g. CST
users saw "8h ago" on requests they made seconds earlier).

Always go through `iso_utc()` when serializing a datetime to JSON
that the frontend will render — it forces a `+00:00` suffix so JS
`new Date()` gets a timezone-anchored string.
"""

from __future__ import annotations

from datetime import datetime, timezone


def iso_utc(dt: datetime | None) -> str | None:
    """Serialize a UTC datetime as ISO 8601 with explicit `+00:00` suffix.

    Naive datetimes are assumed to be UTC (matches the DB convention
    from `server_default=func.now()`). Already-aware datetimes pass
    through unchanged. None → None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
