"""/v1beta — Gemini (Google AI Studio style) API ingress.

Endpoints:
  POST /v1beta/models/{model}:generateContent
  POST /v1beta/models/{model}:streamGenerateContent   (?alt=sse → SSE,
        otherwise the chunks are aggregated into one JSON array)
  GET  /v1beta/models            (catalog, Gemini list shape)
  GET  /v1beta/models/{model}

FastAPI path templates can't express the `:action` suffix, so a single
`{model_and_action}` segment is split on the last ':'. The `model` half
supports "auto" like every other ingress.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_key_context
from app.protocols import gemini as proto
from app.protocols.sse import aclose_quietly, iter_openai_frames
from app.routes.anthropic_compat import (
    _validation_message,
    forwarded_headers,
    parse_native_body,
)
from app.routes.chat import execute_chat
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext
from packages.litellm_adapter.catalog import CATALOG, CATALOG_BY_ID

logger = structlog.get_logger()
router = APIRouter(tags=["Gemini"])

_ACTIONS = ("generateContent", "streamGenerateContent")


def _model_entry(m) -> dict:
    return {
        "name": f"models/{m.id}",
        "displayName": m.id,
        "description": f"{m.provider} model served via OrcaRouter Lite",
        "supportedGenerationMethods": list(_ACTIONS),
    }


@router.get("/v1beta/models")
async def gemini_list_models(_kc: KeyContext = Depends(get_key_context)):
    return {"models": [_model_entry(m) for m in CATALOG]}


@router.get("/v1beta/models/{model_id}")
async def gemini_get_model(model_id: str, _kc: KeyContext = Depends(get_key_context)):
    m = CATALOG_BY_ID.get(model_id)
    if m is None:
        return proto.error_response(404, f"models/{model_id} is not found")
    return _model_entry(m)


@router.post("/v1beta/models/{model_and_action}")
async def gemini_generate(
    model_and_action: str,
    request: Request,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
):
    if ":" not in model_and_action:
        return proto.error_response(
            404, f"POST is not supported for models/{model_and_action}"
        )
    model, action = model_and_action.rsplit(":", 1)
    if action not in _ACTIONS:
        return proto.error_response(
            404, f"Unknown method '{action}' for models/{model}"
        )
    stream = action == "streamGenerateContent"
    alt_sse = request.query_params.get("alt", "").lower() == "sse"

    try:
        greq = await parse_native_body(request, proto.GeminiGenerateRequest)
        openai_body = ChatCompletionRequest.model_validate(
            proto.to_openai_request(greq, model=model, stream=stream)
        )
        inner = await execute_chat(openai_body, kc, db)
    except HTTPException as exc:
        return proto.error_response(exc.status_code, str(exc.detail))
    except ValidationError as exc:
        return proto.error_response(400, _validation_message(exc))
    except Exception as exc:  # defense-in-depth: never leak the OpenAI envelope
        logger.warning("gemini_compat_error", error=str(exc))
        return proto.error_response(500, "Internal server error")

    if not stream:
        payload = json.loads(bytes(inner.body))
        return JSONResponse(
            proto.to_gemini_response(payload), headers=forwarded_headers(inner)
        )

    chunks = proto.stream_chunks(iter_openai_frames(inner.body_iterator))
    if alt_sse:
        async def sse():
            try:
                async for chunk in chunks:
                    yield f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n"
            finally:
                await aclose_quietly(chunks)

        return StreamingResponse(
            sse(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                **forwarded_headers(inner),
            },
        )

    # No alt=sse: the REST default is a JSON array of chunks — aggregate.
    collected = [chunk async for chunk in chunks]
    for chunk in collected:
        err = chunk.get("error") if isinstance(chunk, dict) else None
        if err:
            # A mid-stream engine failure surfaces as an error chunk.
            # Nothing has been sent yet, so render the native non-200
            # envelope instead of burying the error in a 200 array.
            return proto.error_response(
                err.get("code") or 500,
                err.get("message") or "Upstream provider error",
            )
    return JSONResponse(collected, headers=forwarded_headers(inner))
