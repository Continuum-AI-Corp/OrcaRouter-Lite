"""Native-protocol adapters (Anthropic Messages API, Gemini generateContent).

Each module translates its wire format to/from the internal OpenAI format
consumed by the shared chat engine (`app.routes.chat.execute_chat`). The
translators are pure functions / pure async transformers so they unit-test
without an app or mocks. See PLAN-NATIVE-PROTOCOLS.md.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()

# The OpenAI wire format caps `stop` at 4; both native surfaces accept more.
_OPENAI_STOP_CAP = 4


def clamp_stop_sequences(stop: list, *, event: str) -> list:
    """Truncate stop sequences to the OpenAI wire cap of 4 (documented
    limitation, warning logged) rather than reject a request that is valid
    on the native surface."""
    if len(stop) <= _OPENAI_STOP_CAP:
        return stop
    logger.warning(event, dropped=len(stop) - _OPENAI_STOP_CAP)
    return stop[:_OPENAI_STOP_CAP]
