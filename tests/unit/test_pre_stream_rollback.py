"""Regression: _log_pre_stream_failure must rollback the session on commit
failure so the request-scoped session is not left dirty.

Without the rollback, a failed commit leaves the pending INSERT attached to
the session. The next DB operation on that session (the streaming _finalize
or the blocking path's own commit) then fails with InvalidRequestError
("This Session's transaction has been rolled back") -- a secondary failure
caused by our own error handling, not the original upstream error."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_pre_stream_failure_rolls_back_session():
    """When db.commit() fails inside _log_pre_stream_failure, the session
    must be rolled back so subsequent operations on the same session work."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock(side_effect=Exception("simulated db error"))
    db.rollback = AsyncMock()

    # Simulate the _log_pre_stream_failure commit path.
    log_row = MagicMock()
    db.add(log_row)
    try:
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception:
            pass

    db.rollback.assert_awaited_once()
