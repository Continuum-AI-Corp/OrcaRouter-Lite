"""Native-protocol adapters (Anthropic Messages API, Gemini generateContent).

Each module translates its wire format to/from the internal OpenAI format
consumed by the shared chat engine (`app.routes.chat.execute_chat`). The
translators are pure functions / pure async transformers so they unit-test
without an app or mocks. Each module's docstring records its own mapping
decisions; the caller-visible limitations are listed in
integrations/claude-code.md and integrations/gemini-sdk.md.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException

logger = structlog.get_logger()

# The OpenAI wire format caps `stop` at 4; both native surfaces accept more.
_OPENAI_STOP_CAP = 4


def invalid_request(message: str) -> HTTPException:
    """A 400 in the engine's HTTPException form; each surface's route
    renders it in that surface's native error envelope."""
    return HTTPException(status_code=400, detail=message)


def require_text(value, *, field: str) -> str:
    """Coerce a wire `text` value: absent (None) is "", a string passes,
    anything else is a native 400. Left unchecked, a non-string either
    crashes the join that assembles the message (a 500 the SDKs retry) or
    reaches the upstream and comes back as a retryable error — for a
    request that can never succeed."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise invalid_request(f"{field} must be a string")
    return value


def clamp_stop_sequences(stop: list, *, event: str) -> list:
    """Truncate stop sequences to the OpenAI wire cap of 4 (documented
    limitation, warning logged) rather than reject a request that is valid
    on the native surface."""
    if len(stop) <= _OPENAI_STOP_CAP:
        return stop
    logger.warning(event, dropped=len(stop) - _OPENAI_STOP_CAP)
    return stop[:_OPENAI_STOP_CAP]
