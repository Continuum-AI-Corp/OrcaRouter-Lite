"""Anthropic Messages API ↔ internal OpenAI format translation.

Pure functions + one pure async stream transformer. The caller-visible
limitations are listed in integrations/claude-code.md; the load-bearing
mapping decisions are:

- `thinking` (request param and history blocks) is DROPPED with a log
  warning, never rejected — Claude Code sends it whenever extended
  thinking is on, and a 400 would make the whole client unusable.
- `tool_result` blocks in a user message split into separate OpenAI
  `role: "tool"` messages (emitted first, matching OpenAI's requirement
  that tool results directly follow the assistant tool_calls turn).
- Anthropic has no 422: invalid requests are 400 `invalid_request_error`.
- Streaming relies on the engine's auto-injected
  `stream_options.include_usage`: the usage-bearing frame arrives AFTER
  the finish_reason frame, so `message_delta` (stop_reason + usage) is
  emitted at end-of-stream from recorded state.
- Streamed tool-call fragments are buffered per tool-call index and
  flushed as complete `tool_use` blocks at end-of-stream: OpenAI-format
  streams may interleave fragments of concurrent tool calls, while
  Anthropic content blocks are strictly sequential.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterable

import structlog
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.protocols import clamp_stop_sequences
from app.protocols.sse import finish_quietly

logger = structlog.get_logger()


# ── Request schema ─────────────────────────────────────────────────────

class AnthropicMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict]


class AnthropicMessagesRequest(BaseModel):
    """Wire schema for POST /v1/messages. Extra fields tolerated (the real
    API grows fields regularly; unknown ones are ignored, not rejected)."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[AnthropicMessage] = Field(min_length=1)
    # The real API rejects max_tokens < 1 with a 400. Enforce it here or
    # the upstream's own BadRequest comes back through the engine as a
    # retryable 500 api_error, which SDKs back off and retry forever for
    # a request that can never succeed.
    max_tokens: int = Field(gt=0)
    system: str | list[dict] | None = None
    tools: list[dict] | None = None
    tool_choice: dict | None = None
    # Ranges are the Anthropic API's own. Out-of-range values would be
    # rejected by the upstream as a BadRequest, which the engine reports
    # as a retryable 500 api_error — so bound them here, where the failure
    # is still an honest 400 invalid_request_error.
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=0)
    stop_sequences: list[str] | None = None
    stream: bool = False
    metadata: dict | None = None
    thinking: dict | None = None


# ── Request translation (Anthropic → OpenAI) ───────────────────────────

def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _system_text(system: str | list[dict]) -> str:
    """The `system` param is text-only per the Anthropic API (string or
    text blocks). Anything else — an image block a client tucked into a
    role:"system" message inside messages[], which this surface tolerates
    — has no OpenAI system-message equivalent, so it is dropped with a
    log rather than silently vanishing."""
    if isinstance(system, str):
        return system
    parts: list[str] = []
    dropped = 0
    for b in system:
        if isinstance(b, dict) and b.get("type") == "text":
            if b.get("text"):
                parts.append(b["text"])
        else:
            dropped += 1
    if dropped:
        logger.warning("anthropic_non_text_system_block_dropped", count=dropped)
    return "\n\n".join(parts)


def _image_part(block: dict) -> dict:
    source = block.get("source") or {}
    stype = source.get("type")
    if stype == "base64":
        media = source.get("media_type", "application/octet-stream")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{media};base64,{source.get('data', '')}"},
        }
    if stype == "url":
        return {"type": "image_url", "image_url": {"url": source.get("url", "")}}
    raise _invalid(f"Unsupported image source type: {stype!r}")


def _split_tool_result_content(content) -> tuple[str, list[dict]]:
    """Split tool_result.content into (text, image parts).

    tool_result.content is a string or a list of text/image blocks. An
    OpenAI `role: "tool"` message carries a plain string, so the text is
    flattened into it and any images are handed back for the caller to
    attach to the user message that follows the tool results — a tool
    returning a screenshot is the common case, and dropping it would
    silently compute the answer without context the caller supplied.
    """
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return str(content), []
    texts: list[str] = []
    images: list[dict] = []
    for b in content:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            if b.get("text"):
                texts.append(b["text"])
        elif b.get("type") == "image":
            images.append(_image_part(b))
    return "\n\n".join(texts), images


_DROPPED_BLOCK_TYPES = {"thinking", "redacted_thinking"}


def _translate_assistant_message(blocks: list[dict]) -> dict:
    texts: list[str] = []
    tool_calls: list[dict] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            texts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append({
                "id": block.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input") or {}),
                },
            })
        elif btype in _DROPPED_BLOCK_TYPES:
            continue
        else:
            raise _invalid(f"Unsupported content block type in assistant message: {btype!r}")
    out: dict = {"role": "assistant", "content": "".join(texts) or None}
    if tool_calls:
        out["tool_calls"] = tool_calls
    if out["content"] is None and not tool_calls:
        # Every block was dropped (thinking-only turn — Claude Code sends
        # these on extended-thinking/compacted histories). The engine's
        # `exclude_none` dump would strip the None and upstreams reject a
        # bare {"role": "assistant"}; keep the turn with empty content
        # rather than leaking dropped thinking text or losing the turn.
        out["content"] = ""
    return out


def _translate_user_message(blocks: list[dict]) -> list[dict]:
    """One Anthropic user message may carry tool_result blocks plus regular
    content. OpenAI needs the tool results as their own `role: "tool"`
    messages (first), then the remaining content as a user message —
    which is also where images returned by a tool end up, since an OpenAI
    tool message can only hold text."""
    tool_messages: list[dict] = []
    parts: list[dict] = []
    for block in blocks:
        btype = block.get("type")
        if btype == "tool_result":
            text, images = _split_tool_result_content(block.get("content"))
            tool_messages.append({
                "role": "tool",
                "tool_call_id": block.get("tool_use_id", ""),
                "content": text,
            })
            parts.extend(images)
        elif btype == "text":
            parts.append({"type": "text", "text": block.get("text", "")})
        elif btype == "image":
            parts.append(_image_part(block))
        elif btype in _DROPPED_BLOCK_TYPES:
            continue
        elif btype == "document":
            raise _invalid("'document' content blocks are not supported by this endpoint")
        else:
            raise _invalid(f"Unsupported content block type: {btype!r}")

    out = tool_messages
    if parts:
        if len(parts) == 1 and parts[0]["type"] == "text":
            out.append({"role": "user", "content": parts[0]["text"]})
        else:
            out.append({"role": "user", "content": parts})
    return out


def _translate_message(m: AnthropicMessage) -> list[dict]:
    if m.role == "system":
        # Spec-wise `system` is a top-level param, but real clients (Claude
        # Code 2.x internal requests) also put role:"system" entries inside
        # messages[]. OpenAI's format allows system messages there, so
        # translate instead of rejecting — a 400 here breaks Claude Code.
        text = m.content if isinstance(m.content, str) else _system_text(m.content)
        return [{"role": "system", "content": text}]
    if m.role not in ("user", "assistant"):
        raise _invalid(f"Unsupported message role: {m.role!r}")
    if isinstance(m.content, str):
        return [{"role": m.role, "content": m.content}]
    if m.role == "assistant":
        return [_translate_assistant_message(m.content)]
    return _translate_user_message(m.content)


_SERVER_TOOL_HINT = (
    "server-side tools (web search, computer use, ...) are not supported "
    "by this endpoint; only custom function tools are"
)


def _translate_tool(tool: dict) -> dict:
    ttype = tool.get("type")
    if ttype not in (None, "custom"):
        raise _invalid(f"Unsupported tool type {ttype!r}: {_SERVER_TOOL_HINT}")
    if not tool.get("name"):
        raise _invalid("Tool definition is missing 'name'")
    fn: dict = {
        "name": tool["name"],
        "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
    }
    if tool.get("description"):
        fn["description"] = tool["description"]
    return {"type": "function", "function": fn}


def _translate_tool_choice(tc: dict) -> str | dict:
    tctype = tc.get("type")
    if tctype == "auto":
        return "auto"
    if tctype == "any":
        return "required"
    if tctype == "none":
        return "none"
    if tctype == "tool":
        if not tc.get("name"):
            raise _invalid("tool_choice of type 'tool' requires 'name'")
        return {"type": "function", "function": {"name": tc["name"]}}
    raise _invalid(f"Unsupported tool_choice type: {tctype!r}")


def to_openai_request(req: AnthropicMessagesRequest) -> dict:
    """Translate a validated Anthropic Messages request into the internal
    OpenAI chat.completions dict consumed by the chat engine."""
    messages: list[dict] = []
    if req.system is not None:
        text = _system_text(req.system)
        if text:
            messages.append({"role": "system", "content": text})
    for m in req.messages:
        messages.extend(_translate_message(m))

    out: dict = {
        "model": req.model,
        "messages": messages,
        "max_tokens": req.max_tokens,
        "stream": req.stream,
    }
    if req.temperature is not None:
        out["temperature"] = req.temperature
    if req.top_p is not None:
        out["top_p"] = req.top_p
    if req.stop_sequences:
        out["stop"] = clamp_stop_sequences(
            req.stop_sequences, event="anthropic_stop_sequences_truncated"
        )
    if req.metadata and isinstance(req.metadata.get("user_id"), str):
        out["user"] = req.metadata["user_id"]
    if req.tools is not None:
        out["tools"] = [_translate_tool(t) for t in req.tools]
    if req.tool_choice is not None:
        out["tool_choice"] = _translate_tool_choice(req.tool_choice)
    if req.thinking is not None:
        # Claude Code sends this whenever extended thinking is on. There is
        # no internal-schema equivalent yet — drop it so the request still
        # works (documented limitation), never 400.
        logger.warning("anthropic_thinking_param_dropped")
    if req.top_k is not None:
        logger.info("anthropic_top_k_dropped")
    return out


# ── Response translation (OpenAI → Anthropic) ──────────────────────────

_STOP_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "content_filter": "refusal",
}


def _parse_json_object(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _message_id(raw: str | None) -> str:
    if raw and raw.startswith("msg_"):
        return raw
    return f"msg_{raw or uuid.uuid4().hex}"


def to_anthropic_response(resp: dict) -> dict:
    choices = resp.get("choices") or [{}]
    choice = choices[0] if choices else {}
    msg = choice.get("message") or {}

    content: list[dict] = []
    text = msg.get("content")
    if text:
        content.append({"type": "text", "text": text})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        content.append({
            "type": "tool_use",
            "id": tc.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
            "name": fn.get("name", ""),
            "input": _parse_json_object(fn.get("arguments")),
        })

    usage = resp.get("usage") or {}
    return {
        "id": _message_id(resp.get("id")),
        "type": "message",
        "role": "assistant",
        "model": resp.get("model", ""),
        "content": content,
        "stop_reason": _STOP_REASON_MAP.get(choice.get("finish_reason"), "end_turn"),
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0) or 0,
            "output_tokens": usage.get("completion_tokens", 0) or 0,
        },
    }


# ── Stream translation (OpenAI chunk frames → Anthropic SSE events) ────

def _ev(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


# Engine error types (packages/litellm_adapter/client.py _translate_error,
# reported on SSE error frames and via the x-orca-error-type header) → the
# HTTP status this surface reports them as. The Anthropic error *type* is
# then derived from the status through _STATUS_TO_ERROR_TYPE below, so the
# streaming and blocking paths cannot drift apart.
#
# Retryability is the load-bearing part. Anthropic SDKs back off and retry
# 429/500/529 but not 4xx, so a failure that can never succeed on retry
# has to land on a 4xx: a context overflow or a missing model must not
# read as a transient api_error. The two operator-side conditions —
# upstream_auth_error (OUR provider credential rejected) and
# no_providers_configured (no key set at all) — are permanent until the
# operator acts, so they map to 403 permission_error, matching the Gemini
# surface. Deliberately NOT 401 authentication_error: the caller's own key
# is fine.
_ENGINE_ERROR_STATUS = {
    "rate_limit_error": 429,
    "overloaded_error": 529,
    "context_length_exceeded": 400,
    "model_not_found": 404,
    "upstream_auth_error": 403,
    "no_providers_configured": 403,
}


def _anthropic_error_type(engine_type: str | None) -> str:
    status = _ENGINE_ERROR_STATUS.get(engine_type or "", 500)
    return _STATUS_TO_ERROR_TYPE.get(status, "api_error")


async def stream_events(
    frames: AsyncIterable[dict], *, input_tokens: int = 0,
) -> AsyncGenerator[str, None]:
    """Transform the engine's OpenAI chunk-dict stream into Anthropic SSE
    events. Stateful: tracks the open text block, the mapped stop_reason
    (arrives before usage), and the usage frame (arrives last). Tool-call
    fragments are buffered per index and flushed as complete tool_use
    blocks at end-of-stream — OpenAI-format streams may interleave
    fragments of concurrent calls, Anthropic blocks are strictly
    sequential, so per-fragment emission would scatter one call's JSON
    across several nameless blocks.

    `input_tokens` is the caller's prompt-size estimate, reported in
    message_start where the protocol puts it (SDKs read the input count
    from there). The engine only knows the true count at end-of-stream —
    its usage frame arrives after the last content — so the exact value
    additionally goes out in message_delta.usage, which SDKs that merge
    both events pick up."""
    started = False
    text_open = False
    block_index = -1
    tool_buf: dict[int, dict] = {}  # tool_calls[].index → {id, name, args}
    stop_reason: str | None = None
    usage: dict = {}

    def _start_event(frame: dict) -> str:
        return _ev("message_start", {
            "type": "message_start",
            "message": {
                "id": _message_id(frame.get("id")),
                "type": "message",
                "role": "assistant",
                "model": frame.get("model", ""),
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": input_tokens, "output_tokens": 0},
            },
        })

    def _block_stop() -> str:
        return _ev("content_block_stop", {"type": "content_block_stop", "index": block_index})

    try:
        async for frame in frames:
            if "error" in frame and "choices" not in frame:
                err = frame.get("error") or {}
                etype = err.get("type")
                yield _ev("error", {
                    "type": "error",
                    "error": {
                        "type": _anthropic_error_type(etype),
                        "message": err.get("message", "Upstream provider error"),
                    },
                })
                # Read on to the [DONE] the engine sends after its error
                # frame, so `finish()` below drains it to a normal
                # completion and it logs 503 + the real error type.
                # Returning here without that would leave it suspended and
                # `finish()` would close it, mislogging a 499 disconnect.
                async for _ in frames:
                    pass
                return

            if not started:
                started = True
                yield _start_event(frame)

            choices = frame.get("choices") or []
            choice = choices[0] if choices else {}
            delta = choice.get("delta") or {}

            text = delta.get("content")
            if text:
                if not text_open:
                    text_open = True
                    block_index += 1
                    yield _ev("content_block_start", {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {"type": "text", "text": ""},
                    })
                yield _ev("content_block_delta", {
                    "type": "content_block_delta",
                    "index": block_index,
                    "delta": {"type": "text_delta", "text": text},
                })

            for tcd in delta.get("tool_calls") or []:
                slot = tool_buf.setdefault(
                    tcd.get("index", 0), {"id": "", "name": "", "args": ""}
                )
                if tcd.get("id"):
                    slot["id"] = tcd["id"]
                fn = tcd.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]

            if choice.get("finish_reason"):
                stop_reason = _STOP_REASON_MAP.get(choice["finish_reason"], "end_turn")
                if text_open:
                    yield _block_stop()
                    text_open = False

            if frame.get("usage"):
                usage = frame["usage"]

        # Normal end of stream ([DONE] consumed by the frame source).
        if not started:
            yield _start_event({})
        if text_open:
            yield _block_stop()
        for _, slot in sorted(tool_buf.items()):
            block_index += 1
            yield _ev("content_block_start", {
                "type": "content_block_start",
                "index": block_index,
                "content_block": {
                    "type": "tool_use",
                    "id": slot["id"] or f"toolu_{uuid.uuid4().hex[:24]}",
                    "name": slot["name"],
                    "input": {},
                },
            })
            if slot["args"]:
                yield _ev("content_block_delta", {
                    "type": "content_block_delta",
                    "index": block_index,
                    "delta": {"type": "input_json_delta", "partial_json": slot["args"]},
                })
            yield _block_stop()
        delta_usage: dict = {"output_tokens": usage.get("completion_tokens", 0) or 0}
        if usage.get("prompt_tokens"):
            delta_usage["input_tokens"] = usage["prompt_tokens"]
        yield _ev("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason or "end_turn", "stop_sequence": None},
            "usage": delta_usage,
        })
        yield _ev("message_stop", {"type": "message_stop"})
    finally:
        # Last, deliberately: this drains the engine to completion (or
        # forwards a close), which runs its RequestLog commit. Doing it
        # here rather than mid-transform keeps that DB write behind the
        # terminal events above, so the client always has message_stop
        # before the writeback happens. See OpenAIFrameStream.
        await finish_quietly(frames)


# ── Error envelope ──────────────────────────────────────────────────────

_STATUS_TO_ERROR_TYPE = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    413: "request_too_large",
    429: "rate_limit_error",
    500: "api_error",
    529: "overloaded_error",
}


def native_status(status: int, error_type: str | None) -> int:
    """Correct the engine's generic HTTP status using its translated
    error_type (relayed via the x-orca-error-type header) where the plain
    status would misrepresent the failure on this surface — e.g. the
    engine uses 422 for model_not_found but Anthropic's contract is 404
    not_found_error. Reads _ENGINE_ERROR_STATUS, the same table the
    streaming path derives its error type from, so the two cannot drift."""
    return _ENGINE_ERROR_STATUS.get(error_type or "", status)


def error_response(status: int, message: str) -> JSONResponse:
    """Render an error in the Anthropic envelope. The API has no 422 (bad
    requests are 400) and we collapse 5xx upstream failures to 500."""
    if status == 422:
        status = 400
    if status >= 500 and status != 529:
        status = 500
    return JSONResponse(
        status_code=status,
        content={
            "type": "error",
            "error": {
                "type": _STATUS_TO_ERROR_TYPE.get(status, "api_error"),
                "message": message,
            },
        },
    )
