"""GET /v1/models — model listing.

One path, two protocols. The OpenAI envelope is the default; a request
carrying `anthropic-version` (which the official Anthropic SDK and Claude
Code always send, and no OpenAI client sends) gets the Anthropic envelope
instead, so `client.models.list()` works against the same base URL the
native /v1/messages surface lives on. The Gemini surface has its own
listing at GET /v1beta/models.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from app.deps import get_key_context
from packages.auth.types import KeyContext
from packages.litellm_adapter.catalog import CATALOG

router = APIRouter(prefix="/v1", tags=["models"])

# Anthropic's ModelInfo.created_at is an RFC 3339 release date. We don't
# track release dates, and the API documents the epoch as the value to
# use when the date is unknown.
_UNKNOWN_RELEASE = "1970-01-01T00:00:00Z"


def _anthropic_listing() -> dict:
    data = [
        {
            "type": "model",
            "id": m.id,
            "display_name": m.id,
            "created_at": _UNKNOWN_RELEASE,
        }
        for m in CATALOG
    ]
    return {
        "data": data,
        # The whole catalog is returned in one page, so pagination is a
        # constant: nothing follows this page.
        "has_more": False,
        "first_id": data[0]["id"] if data else None,
        "last_id": data[-1]["id"] if data else None,
    }


@router.get("/models")
async def list_models(
    request: Request, _kc: KeyContext = Depends(get_key_context),
) -> dict:
    if "anthropic-version" in request.headers:
        return _anthropic_listing()

    now = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": m.id,
                "object": "model",
                "created": now,
                "owned_by": m.provider,
                "permission": [],
            }
            for m in CATALOG
        ],
    }
