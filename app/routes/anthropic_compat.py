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

import anyio
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_key_context
from app.protocols import anthropic as proto
from app.protocols.sse import OpenAIFrameStream, aclose_quietly
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


async def guard_native_stream(gen, render_error, *, event: str):
    """Wrap a native streaming body so a fault inside the adapter itself
    still speaks the native protocol: the app-wide handlers render the
    OpenAI envelope (or just reset the connection mid-stream), which the
    Anthropic / google-genai SDKs cannot parse. An adapter exception is
    logged and rendered as one in-stream native error frame; the response
    is already 200 by the time the body runs, so that is the only channel.
    Cancellation (client gone) passes straight through."""
    try:
        async for item in gen:
            yield item
    except Exception as exc:
        logger.warning(event, error=str(exc))
        yield render_error("Internal server error")
    finally:
        with anyio.CancelScope(shield=True):
            await aclose_quietly(gen)


def check_model_allowlist(model: str, kc: KeyContext) -> None:
    """The same first check execute_chat applies to every completion: a key
    with an allowlist may not touch models outside it. The count-token
    endpoints never reach the engine, so they enforce it themselves —
    otherwise a restricted key could probe denied models through them.
    "auto" is exempt exactly as in the engine (it is never a literal in an
    allowlist; the engine filters the resolved candidates instead)."""
    if model != "auto" and kc.model_allowlist is not None and model not in kc.model_allowlist:
        raise HTTPException(
            status_code=403,
            detail=f"Model '{model}' is not allowed for this API key",
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
        translated = proto.to_openai_request(areq)
        openai_body = ChatCompletionRequest.model_validate(translated)
        # log_status: the RequestLog row must record the status this
        # surface actually delivers (404 for model_not_found, 403 for the
        # operator-side conditions, 500 for a generic upstream failure),
        # not the engine's generic 422/503.
        inner = await execute_chat(openai_body, kc, db, log_status=proto.delivered_status)
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
        events = proto.stream_events(
            OpenAIFrameStream(inner.body_iterator),
            # The protocol reports the input count in message_start,
            # which is emitted before the engine knows it (its usage
            # frame lands at end-of-stream), so send the same estimate
            # /v1/messages/count_tokens would return. The exact count
            # follows in message_delta.usage.
            input_tokens=_count_input_tokens(translated),
        )
        return StreamingResponse(
            guard_native_stream(
                events, proto.stream_error_event, event="anthropic_compat_stream_error",
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
        check_model_allowlist(areq.model, kc)
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
