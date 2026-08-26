"""Unit tests for packages.auth.spend — lifetime spend aggregation."""

import pytest

from packages.auth.spend import (
    MICROCENTS_PER_CENT,
    budget_exceeded,
    get_lifetime_spend_microcents,
)


@pytest.fixture
async def seeded_log(db_session):
    """Two keys with a mix of billable / streaming-failure / soft-deleted rows."""
    from packages.db.models.api_key import ApiKey
    from packages.db.models.request_log import RequestLog

    k1 = ApiKey(workspace_id="default", name="a", key_hash="h-a", key_prefix="p-a")
    k2 = ApiKey(workspace_id="default", name="b", key_hash="h-b", key_prefix="p-b")
    db_session.add_all([k1, k2])
    await db_session.flush()

    rows = [
        RequestLog(
            workspace_id="default", api_key_id=k1.id, model_requested="m",
            model_resolved="m", provider="openai", input_tokens=1, output_tokens=1,
            cost_microcents=1000, status_code=200, routing_strategy="balanced", latency_ms=10, trace_id="t-1",
        ),
        RequestLog(
            workspace_id="default", api_key_id=k1.id, model_requested="m",
            model_resolved="m", provider="openai", input_tokens=1, output_tokens=1,
            cost_microcents=500, status_code=200, routing_strategy="balanced", latency_ms=10, trace_id="t-1",
        ),
        # Streaming failures ARE billable when they carry cost — the
        # provider billed tokens even though the final status is 503
        # (mid-stream upstream failure) or 499 (client disconnect).
        # Filtering on status_code < 400 would exclude these and make the
        # budget bypassable, so they must be counted.
        RequestLog(
            workspace_id="default", api_key_id=k1.id, model_requested="m",
            model_resolved="m", provider="openai", input_tokens=9, output_tokens=9,
            cost_microcents=999_999, status_code=503, routing_strategy="balanced", latency_ms=10, trace_id="t-3",
        ),
        # soft-deleted rows must never count, even with non-zero cost
        RequestLog(
            workspace_id="default", api_key_id=k1.id, model_requested="m",
            model_resolved="m", provider="openai", input_tokens=1, output_tokens=1,
            cost_microcents=12345, status_code=200, routing_strategy="balanced", latency_ms=10, trace_id="t-5",
            is_deleted=1,
        ),
        # another key's spend must not leak in
        RequestLog(
            workspace_id="default", api_key_id=k2.id, model_requested="m",
            model_resolved="m", provider="openai", input_tokens=2, output_tokens=2,
            cost_microcents=777_777, status_code=200, routing_strategy="balanced", latency_ms=10, trace_id="t-4",
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return k1, k2


async def test_spend_sums_only_billable_rows_for_the_key(db_session, seeded_log):
    k1, _k2 = seeded_log
    spend = await get_lifetime_spend_microcents(db_session, k1.id)
    # 1000 + 500 + 999_999 (503 failure with cost is now counted) = 1,001,499;
    # soft-deleted 12345 is excluded.
    assert spend == 1_001_499


async def test_spend_counts_stream_disconnect_and_mid_stream_failure(db_session, seeded_log):
    """Regression for P1: 499/503 streaming costs must count toward budget."""
    from packages.db.models.request_log import RequestLog

    k1, _k2 = seeded_log
    # Add explicit 499 disconnect row with cost
    db_session.add(
        RequestLog(
            workspace_id="default", api_key_id=k1.id, model_requested="m",
            model_resolved="m", provider="openai", input_tokens=2, output_tokens=2,
            cost_microcents=42_000, status_code=499, routing_strategy="balanced", latency_ms=10, trace_id="t-6",
        )
    )
    await db_session.commit()
    spend = await get_lifetime_spend_microcents(db_session, k1.id)
    assert spend == 1_001_499 + 42_000


async def test_empty_history_is_zero(db_session, seeded_log):
    _k1, k2 = seeded_log
    from packages.db.models.api_key import ApiKey

    fresh = ApiKey(workspace_id="default", name="c", key_hash="h-c", key_prefix="p-c")
    db_session.add(fresh)
    await db_session.commit()
    assert await get_lifetime_spend_microcents(db_session, fresh.id) == 0


def test_budget_exceeded_boundary():
    assert budget_exceeded(10_000 - 1, 1) is False  # just under 1 cent
    assert budget_exceeded(10_000, 1) is True       # exactly at the cap blocks
    assert budget_exceeded(0, 1) is False


def test_microcent_conversion_constant():
    assert MICROCENTS_PER_CENT == 10_000
