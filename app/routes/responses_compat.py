"""POST /v1/responses — OpenAI Responses API ingress (Codex CLI).

Thin adapter over the shared chat engine, mirroring the Anthropic and
Gemini ingresses: validate + translate the native request into the
internal chat format, run `execute_chat` (auth already happened in
middleware; allowlist / auto-routing / fallback / budgets / prompt cache /
RequestLog all live in the engine), then translate the result back.

Responses-specific handling:
  - request validation renders 400 `invalid_request_error` in the OpenAI
    envelope instead of the app-wide 422
  - engine HTTPExceptions are re-rendered in the same envelope, with the
    engine's error type mapped to OpenAI's status where they differ
  - streaming re-frames the engine's `data:`-only SSE into Responses
    `event: <type>\\ndata: {json}` events (no [DONE] sentinel), always
    terminated by response.completed or response.failed
"""

from __future__ import annotations

import functools
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_key_context
from app.protocols import responses as proto
from app.protocols.sse import OpenAIFrameStream
from app.routes.anthropic_compat import (
    _validation_message,
    forwarded_headers,
    guard_native_stream,
    parse_native_body,
)
from app.routes.chat import ERROR_TYPE_HEADER, execute_chat
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext

logger = structlog.get_logger()
router = APIRouter(tags=["OpenAI Responses"])


@router.post("/v1/responses")
async def create_response(
    request: Request,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        rreq = await parse_native_body(request, proto.ResponsesRequest)
        ctx = proto.ResponseContext.for_request(rreq)
        openai_body = ChatCompletionRequest.model_validate(proto.to_openai_request(rreq))
        # log_status: the RequestLog row records the status this surface
        # actually delivers (404 model_not_found, 403 operator-side), not
        # the engine's generic 422/503.
        inner = await execute_chat(openai_body, kc, db, log_status=proto.delivered_status)
    except HTTPException as exc:
        error_type = (exc.headers or {}).get(ERROR_TYPE_HEADER)
        return proto.error_response(
            proto.native_status(exc.status_code, error_type), str(exc.detail), code=error_type,
        )
    except ValidationError as exc:
        return proto.error_response(400, _validation_message(exc))
    except Exception as exc:  # defense-in-depth: never leak an unhandled 500
        logger.warning("responses_compat_error", error=str(exc))
        return proto.error_response(500, "Internal server error")

    if isinstance(inner, StreamingResponse):
        return StreamingResponse(
            guard_native_stream(
                proto.stream_events(OpenAIFrameStream(inner.body_iterator), ctx),
                functools.partial(proto.stream_error_event, ctx),
                event="responses_compat_stream_error",
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                **forwarded_headers(inner),
            },
        )

    try:
        payload = json.loads(bytes(inner.body))
        return JSONResponse(proto.to_responses_response(payload, ctx), headers=forwarded_headers(inner))
    except Exception as exc:  # defense-in-depth
        logger.warning("responses_compat_error", error=str(exc))
        return proto.error_response(500, "Internal server error")
