"""Latency aggregation must handle rows where provider attribution failed.

When the LiteLLM adapter fails before routing (e.g. no providers
configured, DNS failure), the request_log row still gets written but
with provider=NULL. The latency_by_provider endpoint must not emit
null keys in its response — the dashboard frontend renders them as
"null" in the provider list, which is confusing and breaks sorting.

The fix groups null-provider rows under "unknown" so the aggregation
always produces clean string keys.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


from app.routes.analytics import latency_by_provider


@pytest.mark.asyncio
async def test_latency_null_provider_mapped_to_unknown():
    db = MagicMock()
    # The query returns (provider, latency_ms) tuples
    fake_rows = [
        ("openai", 120),
        (None, 200),
        ("anthropic", 80),
        (None, 300),
    ]

    result_mock = MagicMock()
    result_mock.all.return_value = fake_rows
    db.execute = AsyncMock(return_value=result_mock)

    kc = MagicMock()
    kc.workspace_id = "default"

    result = await latency_by_provider(days=7, _kc=kc, db=db)

    providers = {r["provider"] for r in result["by_provider"]}
    assert None not in providers
    assert "unknown" in providers
    assert "openai" in providers
    assert "anthropic" in providers

    unknown_row = next(r for r in result["by_provider"] if r["provider"] == "unknown")
    assert unknown_row["request_count"] == 2


@pytest.mark.asyncio
async def test_latency_all_providers_present():
    db = MagicMock()
    fake_rows = [
        ("openai", 100),
        ("anthropic", 90),
    ]

    result_mock = MagicMock()
    result_mock.all.return_value = fake_rows
    db.execute = AsyncMock(return_value=result_mock)

    kc = MagicMock()
    result = await latency_by_provider(days=7, _kc=kc, db=db)

    providers = {r["provider"] for r in result["by_provider"]}
    assert providers == {"openai", "anthropic"}


@pytest.mark.asyncio
async def test_latency_empty_rows():
    db = MagicMock()
    result_mock = MagicMock()
    result_mock.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    kc = MagicMock()
    result = await latency_by_provider(days=7, _kc=kc, db=db)

    assert result["by_provider"] == []


@pytest.mark.asyncio
async def test_latency_percentiles_with_null_provider():
    db = MagicMock()
    fake_rows = [
        (None, 100),
        (None, 200),
        (None, 300),
    ]

    result_mock = MagicMock()
    result_mock.all.return_value = fake_rows
    db.execute = AsyncMock(return_value=result_mock)

    kc = MagicMock()
    result = await latency_by_provider(days=7, _kc=kc, db=db)

    assert len(result["by_provider"]) == 1
    row = result["by_provider"][0]
    assert row["provider"] == "unknown"
    assert row["request_count"] == 3
    assert row["p50_ms"] == 200
    assert row["p99_ms"] == 300
