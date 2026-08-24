"""POST /v1/messages — Anthropic Messages API ingress.

Thin adapter over the shared chat engine: validate + translate the native
request into the internal OpenAI format, run `execute_chat` (auth already
happened in middleware; allowlist / auto-routing / prompt cache /
RequestLog all live in the engine), then translate the result back.

Anthropic-protocol specifics handled here rather than globally:
  - request validation renders 400 `invalid_request_error` in the
    Anthropic envelope (the app-wide handlers speak OpenAI's envelope
    and use 422, which Anthropic clients don't expect)
  - engine HTTPExceptions are re-rendered in the Anthropic envelope
  - streaming re-frames the engine's `data:`-only SSE into Anthropic's
    `event: <name>\\ndata: {json}` events (no [DONE] sentinel)
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_key_context
from app.protocols import anthropic as proto
from app.protocols.sse import iter_openai_frames
from app.routes.chat import ERROR_TYPE_HEADER, execute_chat
from app.schemas import ChatCompletionRequest
from packages.auth.types import KeyContext

logger = structlog.get_logger()
router = APIRouter(tags=["Anthropic Messages"])

_FORWARDED_HEADERS = (
    "x-orca-cache",
    "x-orca-resolved-model",
    "x-orca-requested-model",
    "x-orca-routing-strategy",
)


def forwarded_headers(inner: Response) -> dict[str, str]:
    return {h: inner.headers[h] for h in _FORWARDED_HEADERS if h in inner.headers}


def _validation_message(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
    )


async def parse_native_body(request: Request, model_cls: type[BaseModel]) -> BaseModel:
    """Read + validate the native request body manually so validation
    failures render in the native envelope instead of the app-wide 422."""
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON") from None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=_validation_message(exc)) from None


@router.post("/v1/messages")
async def anthropic_messages(
    request: Request,
    kc: KeyContext = Depends(get_key_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        areq = await parse_native_body(request, proto.AnthropicMessagesRequest)
        openai_body = ChatCompletionRequest.model_validate(proto.to_openai_request(areq))
        inner = await execute_chat(openai_body, kc, db)
    except HTTPException as exc:
        # native_status: the engine relays its translated error type in a
        # header (e.g. model_not_found is 422 there, 404 not_found_error
        # on this surface).
        return proto.error_response(
            proto.native_status(
                exc.status_code, (exc.headers or {}).get(ERROR_TYPE_HEADER)
            ),
            str(exc.detail),
        )
    except ValidationError as exc:
        return proto.error_response(400, _validation_message(exc))
    except Exception as exc:  # defense-in-depth: never leak the OpenAI envelope
        logger.warning("anthropic_compat_error", error=str(exc))
        return proto.error_response(500, "Internal server error")

    if isinstance(inner, StreamingResponse):
        return StreamingResponse(
            proto.stream_events(iter_openai_frames(inner.body_iterator)),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                **forwarded_headers(inner),
            },
        )

    try:
        payload = json.loads(bytes(inner.body))
        return JSONResponse(
            proto.to_anthropic_response(payload),
            headers=forwarded_headers(inner),
        )
    except Exception as exc:  # defense-in-depth: never leak the OpenAI envelope
        logger.warning("anthropic_compat_error", error=str(exc))
        return proto.error_response(500, "Internal server error")


@router.post("/v1/messages/count_tokens")
async def anthropic_count_tokens(
    request: Request,
    kc: KeyContext = Depends(get_key_context),
):
    """Token estimate for the given request. Claude Code calls this for
    context tracking; an estimate is enough (`litellm.token_counter` when
    it knows the model, chars/4 otherwise)."""
    try:
        try:
            raw = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Request body is not valid JSON") from None
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")
        # Same schema as /v1/messages minus max_tokens/stream requirements.
        raw = {**raw, "max_tokens": raw.get("max_tokens") or 1}
        areq = proto.AnthropicMessagesRequest.model_validate(raw)
        openai_body = proto.to_openai_request(areq)
        return JSONResponse({"input_tokens": _count_input_tokens(openai_body)})
    except HTTPException as exc:
        return proto.error_response(exc.status_code, str(exc.detail))
    except ValidationError as exc:
        return proto.error_response(400, _validation_message(exc))
    except Exception as exc:  # defense-in-depth: never leak the OpenAI envelope
        logger.warning("anthropic_count_tokens_error", error=str(exc))
        return proto.error_response(500, "Internal server error")


def _count_input_tokens(openai_body: dict) -> int:
    try:
        import litellm

        return int(litellm.token_counter(
            model=openai_body["model"], messages=openai_body["messages"],
        ))
    except Exception:
        total_chars = sum(
            len(m["content"]) if isinstance(m.get("content"), str) else len(json.dumps(m.get("content") or ""))
            for m in openai_body["messages"]
        )
        return max(1, total_chars // 4)
