"""Gemini (Google AI Studio) API ↔ internal OpenAI format translation.

Pure functions + one pure async stream transformer. The caller-visible
limitations are listed in integrations/gemini-sdk.md; the load-bearing
mapping decisions are:

- Wire fields are accepted in BOTH camelCase (REST / google-genai SDK)
  and snake_case (some client serializations).
- Function-declaration schemas arrive with UPPERCASE proto type enums
  ("OBJECT", "STRING", ...) — normalized recursively to lowercase
  JSON-Schema types before they hit the engine.
- Gemini has no tool-call ids: history `functionCall` parts get synthetic
  `call_<n>` ids and `functionResponse` parts pair to the earliest
  unmatched call with the same name (the positional semantics Gemini
  itself uses).
- Streaming never emits a partial functionCall: tool-call argument
  fragments are buffered and flushed as one complete part before the
  final finishReason/usageMetadata chunk.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterable

import structlog
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.protocols import clamp_stop_sequences
from app.protocols.anthropic import _parse_json_object
from app.protocols.sse import finish_quietly

logger = structlog.get_logger()


# ── Request schema ─────────────────────────────────────────────────────

class GeminiGenerateRequest(BaseModel):
    """Wire schema for :generateContent / :streamGenerateContent.
    Field aliases accept the camelCase REST forms; `populate_by_name`
    accepts the snake_case forms too. Extra fields tolerated."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    contents: str | dict | list[dict]
    system_instruction: str | dict | None = Field(default=None, alias="systemInstruction")
    tools: list[dict] | None = None
    tool_config: dict | None = Field(default=None, alias="toolConfig")
    generation_config: dict | None = Field(default=None, alias="generationConfig")
    safety_settings: list[dict] | None = Field(default=None, alias="safetySettings")
    cached_content: str | None = Field(default=None, alias="cachedContent")


def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _alias(d: dict, camel: str, snake: str, default=None):
    if camel in d:
        return d[camel]
    return d.get(snake, default)


# ── Request translation (Gemini → OpenAI) ──────────────────────────────

def normalize_gemini_schema(node):
    """Lowercase Gemini's proto type enums ("OBJECT", "STRING", ...) into
    JSON-Schema types, recursively. Property names are dict KEYS, so a
    property literally named "type" is untouched (its value is a schema
    dict, and only string values under a "type" key are lowered)."""
    if isinstance(node, list):
        return [normalize_gemini_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "type" and isinstance(v, str):
            out[k] = v.lower()
        elif k == "type" and isinstance(v, list):
            out[k] = [x.lower() if isinstance(x, str) else normalize_gemini_schema(x) for x in v]
        else:
            out[k] = normalize_gemini_schema(v)
    return out


_UNSUPPORTED_TOOL_KEYS = (
    ("googleSearch", "google_search"),
    ("googleSearchRetrieval", "google_search_retrieval"),
    ("codeExecution", "code_execution"),
    ("urlContext", "url_context"),
)

# Part keys that only carry thinking metadata (a part made of nothing but
# these has no translatable payload).
_THOUGHT_PART_KEYS = {"thought", "thoughtSignature", "thought_signature"}


def _translate_tools(tools: list[dict]) -> list[dict]:
    out: list[dict] = []
    for tool in tools:
        for camel, snake in _UNSUPPORTED_TOOL_KEYS:
            if camel in tool or snake in tool:
                raise _invalid(
                    f"Tool '{camel}' is not supported by this endpoint; "
                    "only functionDeclarations are"
                )
        decls = _alias(tool, "functionDeclarations", "function_declarations") or []
        for decl in decls:
            if not decl.get("name"):
                raise _invalid("functionDeclaration is missing 'name'")
            params = _alias(decl, "parameters", "parameters") \
                or _alias(decl, "parametersJsonSchema", "parameters_json_schema")
            fn: dict = {
                "name": decl["name"],
                "parameters": normalize_gemini_schema(params)
                if params else {"type": "object", "properties": {}},
            }
            if decl.get("description"):
                fn["description"] = decl["description"]
            out.append({"type": "function", "function": fn})
    return out


def _translate_tool_config(tc: dict) -> tuple[str | dict | None, list[str] | None]:
    """Returns (tool_choice, allowed_function_names).

    `allowed` is non-None only for mode ANY with MULTIPLE names: OpenAI's
    "required" means "must call SOME tool", so the caller must also
    constrain the tools list to the allowed subset — otherwise the model
    may call a function the Gemini caller explicitly excluded. The
    single-name case needs no filtering (a specific-function tool_choice
    already pins the call)."""
    fcc = _alias(tc, "functionCallingConfig", "function_calling_config")
    if not isinstance(fcc, dict):
        return None, None
    # tool_config is free-form in the wire schema — validate the field
    # types here so malformed input renders as a native 400, not a 500.
    mode_raw = fcc.get("mode")
    if mode_raw is not None and not isinstance(mode_raw, str):
        raise _invalid("functionCallingConfig.mode must be a string")
    mode = (mode_raw or "").upper()
    if mode in ("", "MODE_UNSPECIFIED", "AUTO", "VALIDATED"):
        return "auto", None
    if mode == "NONE":
        return "none", None
    if mode == "ANY":
        allowed = _alias(fcc, "allowedFunctionNames", "allowed_function_names") or []
        if not isinstance(allowed, list) or not all(isinstance(n, str) for n in allowed):
            raise _invalid("functionCallingConfig.allowedFunctionNames must be a list of strings")
        if len(allowed) == 1:
            return {"type": "function", "function": {"name": allowed[0]}}, None
        if allowed:
            return "required", allowed
        return "required", None
    raise _invalid(f"Unsupported functionCallingConfig mode: {mode!r}")


def _system_text(si: str | dict) -> str:
    if isinstance(si, str):
        return si
    parts = si.get("parts") or []
    if isinstance(parts, dict):
        parts = [parts]
    return "\n\n".join(
        p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")
    )


class _CallIdAllocator:
    """Synthesize OpenAI tool_call ids for Gemini's id-less function calls,
    pairing functionResponse parts to the earliest unmatched call by name."""

    def __init__(self):
        self._seq = 0
        self._pending: dict[str, deque[str]] = {}

    def new_call(self, name: str) -> str:
        self._seq += 1
        call_id = f"call_{self._seq}"
        self._pending.setdefault(name, deque()).append(call_id)
        return call_id

    def match_response(self, name: str) -> str:
        queue = self._pending.get(name)
        if queue:
            return queue.popleft()
        # Lenient fallback: an orphan functionResponse still translates,
        # the upstream will surface any mismatch itself.
        logger.warning("gemini_function_response_unmatched", name=name)
        return f"call_{name}"


def _translate_content(content: dict, ids: _CallIdAllocator) -> list[dict]:
    role = content.get("role") or "user"
    if role not in ("user", "model"):
        raise _invalid(f"Unsupported content role: {role!r}")
    is_model = role == "model"

    texts: list[str] = []
    parts_out: list[dict] = []
    tool_calls: list[dict] = []
    tool_messages: list[dict] = []

    raw_parts = content.get("parts") or []
    if isinstance(raw_parts, dict):
        raw_parts = [raw_parts]
    for part in raw_parts:
        if not isinstance(part, dict):
            raise _invalid("Content part must be an object")
        if part.get("thought") or (part and not (set(part) - _THOUGHT_PART_KEYS)):
            # Thought(-summary)/signature parts mirror Anthropic thinking
            # blocks: no internal equivalent — drop, never reject. Parts
            # that carry a real payload NEXT TO a signature (e.g. a
            # functionCall with thoughtSignature) are not dropped.
            # debug, not warning: agentic clients resend full history every
            # request, so a per-part warning would grow O(n²) over a session.
            logger.debug("gemini_thought_part_dropped")
            continue
        if "text" in part:
            texts.append(part.get("text") or "")
            parts_out.append({"type": "text", "text": part.get("text") or ""})
        elif "inlineData" in part or "inline_data" in part:
            blob = _alias(part, "inlineData", "inline_data") or {}
            mime = _alias(blob, "mimeType", "mime_type") or "application/octet-stream"
            parts_out.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{blob.get('data', '')}"},
            })
        elif "functionCall" in part or "function_call" in part:
            fc = _alias(part, "functionCall", "function_call") or {}
            name = fc.get("name", "")
            tool_calls.append({
                "id": ids.new_call(name),
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(fc.get("args") or {})},
            })
        elif "functionResponse" in part or "function_response" in part:
            fr = _alias(part, "functionResponse", "function_response") or {}
            name = fr.get("name", "")
            tool_messages.append({
                "role": "tool",
                "tool_call_id": ids.match_response(name),
                "content": json.dumps(fr.get("response") or {}),
            })
        elif "fileData" in part or "file_data" in part:
            raise _invalid("fileData parts (Files API) are not supported by this endpoint")
        else:
            raise _invalid(f"Unsupported content part keys: {sorted(part.keys())!r}")

    if is_model:
        out: dict = {"role": "assistant", "content": "".join(texts) or None}
        if tool_calls:
            out["tool_calls"] = tool_calls
        if out["content"] is None and not tool_calls:
            # Same guard as the Anthropic sibling: a model turn with no
            # representable parts (empty parts echoed back in history,
            # thought-only turns) must keep content "" — the engine's
            # exclude_none dump would otherwise send a bare
            # {"role": "assistant"}, which upstreams reject.
            out["content"] = ""
        return [out]

    out_messages = tool_messages
    if parts_out:
        if len(parts_out) == 1 and parts_out[0]["type"] == "text":
            out_messages.append({"role": "user", "content": parts_out[0]["text"]})
        else:
            out_messages.append({"role": "user", "content": parts_out})
    return out_messages


# generationConfig is free-form on the wire, so its numbers are validated
# here against the API's documented ranges. Out-of-range values are
# rejected by the upstream as a BadRequest, which the engine reports as a
# retryable 500 INTERNAL / 503 UNAVAILABLE — SDKs then back off and retry
# forever a request that can never succeed. Catching them here keeps the
# failure an honest native 400.

def _bounded_number(value, *, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(f"{field} must be a number between {low} and {high}")
    # NaN/inf fail the comparison and land in the same 400.
    if not low <= value <= high:
        raise _invalid(f"{field} must be between {low} and {high}")
    return value


def _positive_int(value, *, field: str) -> int:
    """A budget < 1 can never succeed upstream. JSON numbers may decode as
    an integral float (100.0), which is accepted and narrowed."""
    if isinstance(value, bool):
        ok = False
    elif isinstance(value, int):
        ok = value >= 1
    elif isinstance(value, float):
        ok = value.is_integer() and value >= 1
    else:
        ok = False
    if not ok:
        raise _invalid(f"{field} must be an integer >= 1")
    return int(value)


def _apply_generation_config(gc: dict, out: dict) -> None:
    temperature = gc.get("temperature")
    if temperature is not None:
        out["temperature"] = _bounded_number(
            temperature, field="temperature", low=0.0, high=2.0
        )
    top_p = _alias(gc, "topP", "top_p")
    if top_p is not None:
        out["top_p"] = _bounded_number(top_p, field="topP", low=0.0, high=1.0)
    max_tokens = _alias(gc, "maxOutputTokens", "max_output_tokens")
    if max_tokens is not None:
        out["max_tokens"] = _positive_int(max_tokens, field="maxOutputTokens")
    stop = _alias(gc, "stopSequences", "stop_sequences")
    if stop:
        if isinstance(stop, list):
            stop = clamp_stop_sequences(
                stop, event="gemini_stop_sequences_truncated"
            )
        out["stop"] = stop
    seed = gc.get("seed")
    if seed is not None:
        out["seed"] = seed
    n = _alias(gc, "candidateCount", "candidate_count")
    if n is not None and n != 1:
        raise _invalid("candidateCount > 1 is not supported by this endpoint")
    mime = _alias(gc, "responseMimeType", "response_mime_type")
    if mime not in (None, "", "text/plain", "application/json"):
        raise _invalid(f"Unsupported responseMimeType: {mime!r}")
    if mime == "application/json":
        out["response_format"] = {"type": "json_object"}
        if _alias(gc, "responseSchema", "response_schema") is not None \
                or _alias(gc, "responseJsonSchema", "response_json_schema") is not None:
            # v1: json mode is honored, the schema constraint itself is not.
            logger.warning("gemini_response_schema_dropped")
    if _alias(gc, "topK", "top_k") is not None:
        logger.info("gemini_top_k_dropped")
    if _alias(gc, "thinkingConfig", "thinking_config") is not None:
        logger.warning("gemini_thinking_config_dropped")


def to_openai_request(req: GeminiGenerateRequest, *, model: str, stream: bool) -> dict:
    """Translate a validated Gemini request into the internal OpenAI
    chat.completions dict consumed by the chat engine. `model` comes from
    the URL path, `stream` from the :streamGenerateContent action."""
    if req.cached_content:
        raise _invalid("cachedContent is not supported by this endpoint")
    if req.safety_settings:
        logger.warning("gemini_safety_settings_dropped")

    contents = req.contents
    if isinstance(contents, str):
        contents = [{"role": "user", "parts": [{"text": contents}]}]
    elif isinstance(contents, dict):
        contents = [contents]

    ids = _CallIdAllocator()
    messages: list[dict] = []
    if req.system_instruction is not None:
        text = _system_text(req.system_instruction)
        if text:
            messages.append({"role": "system", "content": text})
    for content in contents:
        if not isinstance(content, dict):
            raise _invalid("Each entry in 'contents' must be a Content object")
        messages.extend(_translate_content(content, ids))
    if not messages:
        raise _invalid("'contents' produced no messages")

    out: dict = {"model": model, "messages": messages, "stream": stream}
    if req.tools:
        tools = _translate_tools(req.tools)
        if tools:
            out["tools"] = tools
    if req.tool_config:
        tc, allowed = _translate_tool_config(req.tool_config)
        if allowed is not None:
            # ANY + multiple allowedFunctionNames: Google's contract is
            # "must call one of THESE"; OpenAI's "required" alone is only
            # "must call some tool", so restrict the declared tools to the
            # allowed subset (undeclared allowed names are ignored, matching
            # this module's lenient stance elsewhere).
            allowed_set = set(allowed)
            subset = [
                t for t in out.get("tools") or []
                if t["function"]["name"] in allowed_set
            ]
            if not subset:
                raise _invalid(
                    "allowedFunctionNames does not match any declared functionDeclaration"
                )
            out["tools"] = subset
        if tc is not None:
            out["tool_choice"] = tc
    if req.generation_config:
        _apply_generation_config(req.generation_config, out)
    return out


# ── Response translation (OpenAI → Gemini) ─────────────────────────────

_FINISH_REASON_MAP = {
    "stop": "STOP",
    "length": "MAX_TOKENS",
    "content_filter": "SAFETY",
    "tool_calls": "STOP",
    "function_call": "STOP",
}


def _usage_metadata(usage: dict) -> dict:
    prompt = usage.get("prompt_tokens", 0) or 0
    completion = usage.get("completion_tokens", 0) or 0
    return {
        "promptTokenCount": prompt,
        "candidatesTokenCount": completion,
        "totalTokenCount": usage.get("total_tokens") or (prompt + completion),
    }


def to_gemini_response(resp: dict) -> dict:
    choices = resp.get("choices") or [{}]
    choice = choices[0] if choices else {}
    msg = choice.get("message") or {}

    parts: list[dict] = []
    if msg.get("content"):
        parts.append({"text": msg["content"]})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        parts.append({
            "functionCall": {
                "name": fn.get("name", ""),
                "args": _parse_json_object(fn.get("arguments")),
            }
        })

    return {
        "candidates": [{
            "content": {"role": "model", "parts": parts},
            "finishReason": _FINISH_REASON_MAP.get(choice.get("finish_reason"), "STOP"),
            "index": 0,
        }],
        "usageMetadata": _usage_metadata(resp.get("usage") or {}),
        "modelVersion": resp.get("model", ""),
        "responseId": resp.get("id", ""),
    }


# ── Stream translation (OpenAI chunk frames → Gemini chunk dicts) ──────

# Engine SSE error-frame `type` → HTTP-ish code for the Google envelope
# (the Google status string derives from the code via
# _STATUS_TO_GOOGLE_STATUS). Client retry/backoff logic keys off the
# status, so a provider rate limit must surface as RESOURCE_EXHAUSTED,
# not INTERNAL.
_STREAM_ERROR_TYPE_TO_CODE = {
    "rate_limit_error": 429,
    "model_not_found": 404,
    "context_length_exceeded": 400,
    # Operator-side and permanent until they act (credential rejected, or
    # no provider key configured at all) — must not surface as a retryable
    # 503/UNAVAILABLE that SDKs keep backing off against.
    "upstream_auth_error": 403,
    "no_providers_configured": 403,
    "upstream_timeout": 503,
    "upstream_error": 503,
}


async def stream_chunks(frames: AsyncIterable[dict]) -> AsyncGenerator[dict, None]:
    """Transform the engine's OpenAI chunk-dict stream into
    GenerateContentResponse-shaped chunk dicts. Text deltas stream through
    one-to-one; tool-call argument fragments are buffered (Gemini never
    emits a partial functionCall) and flushed complete before the final
    finishReason + usageMetadata chunk."""
    model = ""
    resp_id = ""
    finish: str | None = None
    usage: dict = {}
    tool_buf: dict[int, dict] = {}

    def _base(extra: dict) -> dict:
        return {"modelVersion": model, "responseId": resp_id, **extra}

    try:
        async for frame in frames:
            if "error" in frame and "choices" not in frame:
                err = frame.get("error") or {}
                code = _STREAM_ERROR_TYPE_TO_CODE.get(err.get("type"), 500)
                yield {
                    "error": {
                        "code": code,
                        "message": err.get("message", "Upstream provider error"),
                        "status": _STATUS_TO_GOOGLE_STATUS.get(code, "INTERNAL"),
                    }
                }
                # Read on to the [DONE] the engine sends after its error
                # frame, so `finish()` below drains it to a normal
                # completion and it logs 503 + the real error type.
                # Returning here without that would leave it suspended and
                # `finish()` would close it, mislogging a 499 disconnect.
                async for _ in frames:
                    pass
                return

            model = frame.get("model") or model
            resp_id = frame.get("id") or resp_id
            choices = frame.get("choices") or []
            choice = choices[0] if choices else {}
            delta = choice.get("delta") or {}

            text = delta.get("content")
            if text:
                yield _base({
                    "candidates": [{
                        "content": {"role": "model", "parts": [{"text": text}]},
                        "index": 0,
                    }],
                })

            for tcd in delta.get("tool_calls") or []:
                slot = tool_buf.setdefault(tcd.get("index", 0), {"name": "", "args": ""})
                fn = tcd.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]

            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            if frame.get("usage"):
                usage = frame["usage"]

        # Normal end of stream.
        if tool_buf:
            yield _base({
                "candidates": [{
                    "content": {
                        "role": "model",
                        "parts": [
                            {"functionCall": {
                                "name": slot["name"],
                                "args": _parse_json_object(slot["args"]),
                            }}
                            for _, slot in sorted(tool_buf.items())
                        ],
                    },
                    "index": 0,
                }],
            })
        yield _base({
            "candidates": [{
                "content": {"role": "model", "parts": []},
                "finishReason": _FINISH_REASON_MAP.get(finish, "STOP"),
                "index": 0,
            }],
            "usageMetadata": _usage_metadata(usage),
        })
    finally:
        # Last, deliberately: this drains the engine (running its
        # RequestLog commit), so the final chunk above always reaches the
        # client ahead of that DB write. See OpenAIFrameStream.
        await finish_quietly(frames)


# ── Error envelope ──────────────────────────────────────────────────────

_STATUS_TO_GOOGLE_STATUS = {
    400: "INVALID_ARGUMENT",
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    429: "RESOURCE_EXHAUSTED",
    500: "INTERNAL",
    503: "UNAVAILABLE",
}


def native_status(status: int, error_type: str | None) -> int:
    """Correct the engine's generic HTTP status using its translated
    error_type (relayed via the x-orca-error-type header) where the plain
    status would misrepresent the failure on this surface — e.g. the
    engine uses 422 for model_not_found but Google's contract is 404
    NOT_FOUND. Derived from _STREAM_ERROR_TYPE_TO_CODE (rather than a
    hand-kept mirror) so the stream and blocking paths cannot drift."""
    return _STREAM_ERROR_TYPE_TO_CODE.get(error_type, status)


def error_response(status: int, message: str) -> JSONResponse:
    """Render an error in the Google API envelope (422 collapses to 400)."""
    if status == 422:
        status = 400
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": status,
                "message": message,
                "status": _STATUS_TO_GOOGLE_STATUS.get(status, "INTERNAL"),
            }
        },
    )
