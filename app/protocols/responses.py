"""OpenAI Responses API ↔ internal OpenAI chat format translation.

The client this exists for is OpenAI's Codex CLI, which only speaks the
Responses wire API (`wire_api = "responses"`, always streaming). Pure
functions + one pure async stream transformer, like the Anthropic and
Gemini adapters. The load-bearing mapping decisions:

- The gateway is stateless: `previous_response_id` is a 400 (the caller
  must send the whole conversation in `input`, which Codex does with
  `store: false`). `store`, `include`, `prompt_cache_key`, `reasoning`,
  `text.verbosity`, `service_tier`, `truncation` are accepted and ignored —
  the internal schema has no field for them, and a 400 would make Codex
  unusable.
- `reasoning` input items are dropped (their encrypted content is only
  meaningful to OpenAI); unknown item types are dropped with a debug log,
  and so are tool outputs whose call no longer exists in the history (an
  orphan tool message is a hard upstream error).
- Hosted tools (web_search, local_shell, file_search, ...) are dropped.
  A `custom` (freeform) tool — Codex's grammar-based apply_patch — becomes
  a function tool taking one string parameter `input`; calls the model
  makes to it go back out as `custom_tool_call` items carrying that raw
  string, in both the blocking and the streaming response.
- Every streaming path that does not end in an engine error ends with
  `response.completed` (also for a truncated response, whose status is
  then "incomplete"): Codex fails the turn with "stream closed before
  response.completed" otherwise. Engine errors end with `response.failed`.
- Streamed function-call items open on their first named fragment and
  stream their argument deltas live; fragments of parallel calls that
  interleave stay with their own item (every event names its item_id and
  output_index). Text never interleaves with an open call: text that
  lands while a call's arguments are still incomplete is held back until
  they complete, so items reach the client in the order the model
  produced them.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass, field

import anyio
import structlog
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.protocols import require_text
from app.protocols.anthropic import _args_complete, flatten_openai_content
from app.protocols.sse import finish_quietly

logger = structlog.get_logger()


# ── Request schema ─────────────────────────────────────────────────────

class ResponsesRequest(BaseModel):
    """Wire schema for POST /v1/responses. Extra fields are tolerated (the
    API grows fields regularly; unknown ones are ignored, not rejected)."""

    model_config = ConfigDict(extra="allow")

    model: str
    input: str | list[dict] | None = None
    instructions: str | None = None
    stream: bool = False
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    parallel_tool_calls: bool | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    # OpenAI's own ranges: out-of-range values would come back from the
    # upstream as a BadRequest the engine reports as a retryable 503.
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    text: dict | None = None
    reasoning: dict | None = None
    previous_response_id: str | None = None
    user: str | None = None
    store: bool | None = None
    metadata: dict | None = None


# ── Request translation (Responses → OpenAI chat) ──────────────────────

def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


_TEXT_PART_TYPES = ("input_text", "output_text", "text")


def _image_part(part: dict) -> dict:
    url = part.get("image_url")
    if isinstance(url, dict):  # tolerate the chat-completions shape
        url = url.get("url")
    if not isinstance(url, str) or not url:
        # `file_id` images need OpenAI's file store, which we don't have.
        raise _invalid("input_image requires an 'image_url' (file_id images are not supported)")
    image: dict = {"url": url}
    if isinstance(part.get("detail"), str):
        image["detail"] = part["detail"]
    return {"type": "image_url", "image_url": image}


def _content_parts(content, *, field: str) -> list[dict]:
    """A message's content (string or part list) as OpenAI chat parts."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if content is None:
        return []
    if not isinstance(content, list):
        raise _invalid(f"{field} must be a string or a list of content parts")
    parts: list[dict] = []
    for p in content:
        if not isinstance(p, dict):
            raise _invalid(f"{field}[] entries must be objects")
        ptype = p.get("type")
        if ptype in _TEXT_PART_TYPES:
            text = require_text(p.get("text"), field=f"{field}[].text")
            if text:
                parts.append({"type": "text", "text": text})
        elif ptype == "refusal":
            text = require_text(p.get("refusal"), field=f"{field}[].refusal")
            if text:
                parts.append({"type": "text", "text": text})
        elif ptype == "input_image":
            parts.append(_image_part(p))
        elif ptype == "input_file":
            # Dropping a document would silently answer without it.
            raise _invalid("input_file content parts are not supported by this endpoint")
        else:
            logger.debug("responses_content_part_dropped", part_type=ptype)
    return parts


def _texts(parts: list[dict]) -> list[str]:
    return [p["text"] for p in parts if p["type"] == "text"]


def _tool_output(output) -> tuple[str, list[dict]]:
    """function_call_output.output: a string, or a list of content parts
    (Codex sends one for tools returning images). An OpenAI tool message
    holds text only, so images are handed back separately."""
    if isinstance(output, str):
        return output, []
    if output is None:
        return "", []
    if isinstance(output, list):
        parts = _content_parts(output, field="function_call_output.output")
        images = [p for p in parts if p["type"] == "image_url"]
        return "\n".join(_texts(parts)), images
    return json.dumps(output), []


def _require_call_id(item: dict, kind: str) -> str:
    call_id = item.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise _invalid(f"{kind} item requires a non-empty string 'call_id'")
    return call_id


def _require_name(item: dict, kind: str) -> str:
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise _invalid(f"{kind} item requires a non-empty string 'name'")
    return name


_MESSAGE_ROLES = {"user": "user", "assistant": "assistant", "system": "system", "developer": "system"}


def _translate_input(items: list) -> list[dict]:
    messages: list[dict] = []
    known_calls: set[str] = set()
    pending_images: list[dict] = []

    def emit(msg: dict) -> None:
        # Images returned by tools ride in a user message placed after the
        # whole run of tool results: those must directly follow the
        # assistant tool_calls turn, and a tool message holds text only.
        if pending_images and msg["role"] != "tool":
            messages.append({"role": "user", "content": list(pending_images)})
            pending_images.clear()
        messages.append(msg)

    def add_tool_call(call: dict) -> None:
        prev = messages[-1] if messages else None
        if prev is not None and prev["role"] == "assistant" and not pending_images:
            prev.setdefault("tool_calls", []).append(call)
        else:
            emit({"role": "assistant", "content": None, "tool_calls": [call]})

    for item in items:
        if not isinstance(item, dict):
            raise _invalid("input[] entries must be objects")
        itype = item.get("type")
        if itype is None and "role" in item:
            itype = "message"

        if itype == "message":
            role = _MESSAGE_ROLES.get(item.get("role"))  # type: ignore[arg-type]
            if role is None:
                raise _invalid(f"Unsupported message role: {item.get('role')!r}")
            parts = _content_parts(item.get("content"), field="input[].content")
            if role == "user":
                if not parts:
                    logger.debug("responses_empty_message_dropped", role=role)
                    continue
                if len(parts) == 1 and parts[0]["type"] == "text":
                    emit({"role": "user", "content": parts[0]["text"]})
                else:
                    emit({"role": "user", "content": parts})
                continue
            if len(parts) != len(_texts(parts)):
                logger.warning("responses_non_text_part_dropped", role=role)
            joiner = "" if role == "assistant" else "\n\n"
            text = joiner.join(_texts(parts))
            if not text:
                logger.debug("responses_empty_message_dropped", role=role)
                continue
            prev = messages[-1] if messages else None
            if role == "assistant" and prev is not None and prev.get("tool_calls") and not pending_images:
                # Text the model wrote after its calls, replayed before their
                # results: an assistant message may not sit between tool_calls
                # and the tool messages, so it joins the calling turn.
                prev["content"] = (prev.get("content") or "") + text
                continue
            emit({"role": role, "content": text})

        elif itype in ("function_call", "custom_tool_call"):
            call_id = _require_call_id(item, itype)
            name = _require_name(item, itype)
            if itype == "function_call":
                args = item.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args if args is not None else {})
            else:
                args = json.dumps({"input": require_text(item.get("input"), field="custom_tool_call.input")})
            known_calls.add(call_id)
            add_tool_call({
                "id": call_id, "type": "function",
                "function": {"name": name, "arguments": args},
            })

        elif itype in ("function_call_output", "custom_tool_call_output"):
            call_id = _require_call_id(item, itype)
            if call_id not in known_calls:
                logger.debug("responses_orphan_tool_output_dropped", call_id=call_id)
                continue
            text, images = _tool_output(item.get("output"))
            emit({"role": "tool", "tool_call_id": call_id, "content": text})
            pending_images.extend(images)

        else:
            # reasoning (encrypted, OpenAI-only), hosted-tool calls,
            # item_reference, ... — nothing an upstream chat model can use.
            logger.debug("responses_input_item_dropped", item_type=itype)

    if pending_images:
        messages.append({"role": "user", "content": list(pending_images)})
    return messages


_CUSTOM_INPUT_PARAMETERS = {
    "type": "object",
    "properties": {"input": {
        "type": "string",
        "description": "The raw freeform input for this tool, as plain text (not JSON).",
    }},
    "required": ["input"],
    "additionalProperties": False,
}


def _translate_tool(tool: dict) -> dict | None:
    """One Responses tool → an OpenAI function tool, or None when it has no
    chat-completions equivalent (hosted tools)."""
    if not isinstance(tool, dict):
        raise _invalid("tools[] entries must be objects")
    ttype = tool.get("type")
    if ttype not in ("function", "custom"):
        logger.debug("responses_tool_dropped", tool_type=ttype)
        return None
    name = tool.get("name")
    if not isinstance(name, str) or not name:
        raise _invalid("Tool definition requires a non-empty string 'name'")
    description = tool.get("description")
    if description is not None and not isinstance(description, str):
        raise _invalid(f"Tool '{name}' has a non-string description")
    if ttype == "function":
        params = tool.get("parameters")
        if params is not None and not isinstance(params, dict):
            raise _invalid(f"Tool '{name}' has non-object parameters")
        fn: dict = {"name": name}
        if description:
            fn["description"] = description
        fn["parameters"] = params or {"type": "object", "properties": {}}
        return {"type": "function", "function": fn}

    # custom (freeform) tool: the grammar is the only spec the model gets
    # for the input, so it goes into the description.
    desc = description or ""
    fmt = tool.get("format")
    if isinstance(fmt, dict) and fmt.get("type") == "grammar" and isinstance(fmt.get("definition"), str):
        syntax = fmt.get("syntax") or "grammar"
        desc = (
            f"{desc}\n\nThe `input` argument is raw text (not JSON) that must match "
            f"this {syntax} grammar:\n{fmt['definition']}"
        ).strip()
    fn = {"name": name, "parameters": _CUSTOM_INPUT_PARAMETERS}
    if desc:
        fn["description"] = desc
    return {"type": "function", "function": fn}


def _translate_tool_choice(tc: str | dict) -> str | dict:
    if isinstance(tc, str):
        if tc in ("auto", "none", "required"):
            return tc
        raise _invalid(f"Unsupported tool_choice: {tc!r}")
    tctype = tc.get("type")
    if tctype in ("function", "custom"):
        name = tc.get("name")
        if not isinstance(name, str) or not name:
            raise _invalid("tool_choice of type 'function' requires a non-empty string 'name'")
        return {"type": "function", "function": {"name": name}}
    if tctype == "allowed_tools":
        mode = tc.get("mode")
        return mode if mode in ("auto", "required") else "auto"
    # A hosted tool (web_search, ...) we dropped: let the model choose.
    logger.debug("responses_tool_choice_relaxed", tool_choice_type=tctype)
    return "auto"


def _response_format(text: dict | None) -> dict | None:
    fmt = (text or {}).get("format")
    if not isinstance(fmt, dict):
        return None
    ftype = fmt.get("type")
    if ftype == "json_object":
        return {"type": "json_object"}
    if ftype == "json_schema":
        inner = {k: fmt[k] for k in ("name", "schema", "strict", "description") if k in fmt}
        return {"type": "json_schema", "json_schema": inner}
    return None


def to_openai_request(req: ResponsesRequest) -> dict:
    """Translate a validated Responses request into the internal OpenAI
    chat.completions dict consumed by the chat engine."""
    if req.previous_response_id:
        raise _invalid(
            "previous_response_id is not supported: this gateway does not store "
            "responses. Send the full conversation in 'input' (store: false)."
        )
    messages: list[dict] = []
    if req.instructions:
        messages.append({"role": "system", "content": req.instructions})
    if isinstance(req.input, str):
        if req.input:
            messages.append({"role": "user", "content": req.input})
    elif req.input is not None:
        messages.extend(_translate_input(req.input))
    if not any(m["role"] != "system" for m in messages):
        raise _invalid("'input' produced no messages to send")

    out: dict = {"model": req.model, "messages": messages, "stream": req.stream}
    if req.max_output_tokens is not None:
        out["max_tokens"] = req.max_output_tokens
    if req.temperature is not None:
        out["temperature"] = req.temperature
    if req.top_p is not None:
        out["top_p"] = req.top_p
    if req.user:
        out["user"] = req.user
    rf = _response_format(req.text)
    if rf is not None:
        out["response_format"] = rf

    tools = [t for t in (_translate_tool(t) for t in req.tools or []) if t is not None]
    if tools:
        # tool_choice / parallel_tool_calls without tools are upstream
        # BadRequests, so they only go out alongside at least one tool.
        out["tools"] = tools
        if req.tool_choice is not None:
            out["tool_choice"] = _translate_tool_choice(req.tool_choice)
        if req.parallel_tool_calls is not None:
            out["parallel_tool_calls"] = req.parallel_tool_calls
    if req.reasoning:
        # No reasoning-effort field in the internal schema (it would be
        # dropped silently) — say so in the log instead.
        logger.debug("responses_reasoning_param_dropped")
    return out


# ── Response context (shared by the blocking and streaming paths) ──────

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass
class ResponseContext:
    """Per-request state the response side needs: the response id (stable
    across all stream events), the custom tool names whose calls go back
    out as custom_tool_call items, the request fields a Response object
    echoes, and the stream's sequence counter."""

    response_id: str
    created_at: int
    model: str
    custom_tools: frozenset[str] = frozenset()
    echo: dict = field(default_factory=dict)
    seq: int = 0

    @classmethod
    def for_request(cls, req: ResponsesRequest) -> ResponseContext:
        custom = frozenset(
            t["name"] for t in req.tools or []
            if isinstance(t, dict) and t.get("type") == "custom" and isinstance(t.get("name"), str)
        )
        return cls(
            response_id=_new_id("resp"),
            created_at=int(time.time()),
            model=req.model,
            custom_tools=custom,
            echo={
                "instructions": req.instructions,
                "max_output_tokens": req.max_output_tokens,
                "parallel_tool_calls": (
                    req.parallel_tool_calls if req.parallel_tool_calls is not None else True
                ),
                "previous_response_id": None,
                "reasoning": req.reasoning,
                "store": False,
                "temperature": req.temperature,
                "text": req.text or {"format": {"type": "text"}},
                "tool_choice": req.tool_choice if req.tool_choice is not None else "auto",
                "tools": req.tools or [],
                "top_p": req.top_p,
                "truncation": "disabled",
                "metadata": req.metadata or {},
            },
        )

    def response(
        self, *, status: str, output: list[dict], usage: dict | None = None,
        model: str | None = None, finish_reason: str | None = None,
        error: dict | None = None,
    ) -> dict:
        incomplete = _INCOMPLETE_REASONS.get(finish_reason or "")
        if incomplete and status == "completed":
            status = "incomplete"
        return {
            "id": self.response_id,
            "object": "response",
            "created_at": self.created_at,
            "status": status,
            "error": error,
            "incomplete_details": {"reason": incomplete} if incomplete else None,
            "model": model or self.model,
            "output": output,
            "usage": usage,
            **self.echo,
        }

    def event(self, name: str, data: dict) -> str:
        payload = {"type": name, "sequence_number": self.seq, **data}
        self.seq += 1
        return f"event: {name}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


_INCOMPLETE_REASONS = {"length": "max_output_tokens", "content_filter": "content_filter"}


def _usage(u: dict | None) -> dict:
    u = u or {}
    inp = int(u.get("prompt_tokens") or 0)
    out = int(u.get("completion_tokens") or 0)
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or u.get("cache_read_input_tokens")
    reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": int(u.get("total_tokens") or inp + out),
        "input_tokens_details": {"cached_tokens": int(cached or 0)},
        "output_tokens_details": {"reasoning_tokens": int(reasoning or 0)},
    }


def _custom_input(arguments: str) -> str:
    """The raw freeform input out of the `{"input": ...}` arguments the
    model produced for a custom tool. Anything else is passed through
    verbatim — better a malformed patch the tool can reject than none."""
    try:
        parsed = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return arguments
    if isinstance(parsed, dict):
        if isinstance(parsed.get("input"), str):
            return parsed["input"]
        strings = [v for v in parsed.values() if isinstance(v, str)]
        if len(strings) == 1:
            return strings[0]
    return arguments


def _message_item(item_id: str, text: str, status: str = "completed") -> dict:
    return {
        "id": item_id, "type": "message", "status": status, "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": []}] if status == "completed" else [],
    }


def _call_item(
    item_id: str, call_id: str, name: str, arguments: str, *, custom: bool, status: str = "completed",
) -> dict:
    if custom:
        return {"id": item_id, "type": "custom_tool_call", "status": status,
                "call_id": call_id, "name": name, "input": arguments}
    return {"id": item_id, "type": "function_call", "status": status,
            "call_id": call_id, "name": name, "arguments": arguments}


def to_responses_response(resp: dict, ctx: ResponseContext) -> dict:
    choices = resp.get("choices") or [{}]
    choice = choices[0] if choices else {}
    msg = choice.get("message") or {}

    output: list[dict] = []
    text = flatten_openai_content(msg.get("content"))
    if text:
        output.append(_message_item(_new_id("msg"), text))
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = fn.get("name") or ""
        args = fn.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args or {})
        if not args.strip():
            args = "{}"  # clients parse arguments as JSON
        custom = name in ctx.custom_tools
        output.append(_call_item(
            _new_id("ctc" if custom else "fc"), tc.get("id") or _new_id("call"), name,
            _custom_input(args) if custom else args, custom=custom,
        ))
    return ctx.response(
        status="completed", output=output, usage=_usage(resp.get("usage")),
        model=resp.get("model"), finish_reason=choice.get("finish_reason"),
    )


# ── Stream translation (OpenAI chunk frames → Responses SSE events) ────

# Engine error types (packages/litellm_adapter/client.py _translate_error,
# reported on SSE error frames and via the x-orca-error-type header) → the
# error code OpenAI itself uses, which Codex keys its handling on:
# context_length_exceeded is fatal there, rate_limit_exceeded is retried
# after the delay named in the message, anything else is a retryable
# stream error.
_ENGINE_ERROR_CODE = {
    "rate_limit_error": "rate_limit_exceeded",
    "overloaded_error": "server_is_overloaded",
}


def error_code(engine_type: str | None) -> str:
    """OpenAI's error code for an engine error type, before or inside a stream."""
    return _error_code(engine_type)


def _error_code(engine_type: str | None) -> str:
    if not engine_type:
        return "server_error"
    return _ENGINE_ERROR_CODE.get(engine_type, engine_type)


class _StreamState:
    """Output-item bookkeeping for one stream. Every method returns the
    events it produced, in order."""

    def __init__(self, ctx: ResponseContext):
        self.ctx = ctx
        self.output: dict[int, dict] = {}  # output_index → finished item
        self.next_index = 0
        self.text: dict | None = None  # the open message item
        self.pending_text = ""
        self.tools: dict[int, dict] = {}  # tool_calls[].index → open slot
        self.closed_names: dict[int, str] = {}

    def _alloc(self) -> int:
        index = self.next_index
        self.next_index += 1
        return index

    # text ---------------------------------------------------------------

    def _open_text(self) -> list[str]:
        ev = self.ctx.event
        self.text = {"id": _new_id("msg"), "output_index": self._alloc(), "text": ""}
        base = {"item_id": self.text["id"], "output_index": self.text["output_index"]}
        return [
            ev("response.output_item.added", {
                "output_index": self.text["output_index"],
                "item": _message_item(self.text["id"], "", status="in_progress"),
            }),
            ev("response.content_part.added", {
                **base, "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": []},
            }),
        ]

    def close_text(self) -> list[str]:
        if self.text is None:
            return []
        ev = self.ctx.event
        t, self.text = self.text, None
        base = {"item_id": t["id"], "output_index": t["output_index"]}
        item = _message_item(t["id"], t["text"])
        self.output[t["output_index"]] = item
        return [
            ev("response.output_text.done", {
                **base, "content_index": 0, "text": t["text"], "logprobs": [],
            }),
            ev("response.content_part.done", {
                **base, "content_index": 0, "part": item["content"][0],
            }),
            ev("response.output_item.done", {"output_index": t["output_index"], "item": item}),
        ]

    def text_delta(self, text: str) -> list[str]:
        if self._tools_incomplete():
            # Inside an unfinished call's arguments: hold the text back so
            # it is not delivered before the call it followed.
            self.pending_text += text
            return []
        out = self.close_tools()
        text, self.pending_text = self.pending_text + text, ""
        if not text:
            return out
        if self.text is None:
            out += self._open_text()
        self.text["text"] += text
        out.append(self.ctx.event("response.output_text.delta", {
            "item_id": self.text["id"], "output_index": self.text["output_index"],
            "content_index": 0, "delta": text, "logprobs": [],
        }))
        return out

    # tool calls ---------------------------------------------------------

    def _tools_incomplete(self) -> bool:
        return any(not _args_complete(s["args"]) for s in self.tools.values())

    def _is_custom(self, slot: dict) -> bool:
        return slot["name"] in self.ctx.custom_tools

    def _open_function(self, slot: dict) -> list[str]:
        ev = self.ctx.event
        slot["item_id"] = _new_id("fc")
        slot["output_index"] = self._alloc()
        slot["call_id"] = slot["call_id"] or _new_id("call")
        out = [ev("response.output_item.added", {
            "output_index": slot["output_index"],
            "item": _call_item(slot["item_id"], slot["call_id"], slot["name"], "",
                               custom=False, status="in_progress"),
        })]
        if slot["args"]:
            out.append(self._args_delta(slot, slot["args"]))
        return out

    def _args_delta(self, slot: dict, delta: str) -> str:
        return self.ctx.event("response.function_call_arguments.delta", {
            "item_id": slot["item_id"], "output_index": slot["output_index"], "delta": delta,
        })

    def tool_fragment(self, tcd: dict) -> list[str]:
        out = self.close_text()
        idx = tcd.get("index") or 0
        current = self.tools.get(idx)
        if (current is not None and tcd.get("id") and current["call_id"]
                and tcd["id"] != current["call_id"] and _args_complete(current["args"])):
            # Some providers restart the index for every call: a new id on
            # a finished slot is a new call, not more of the old one.
            del self.tools[idx]
            out += self._close_slot(current)
        if idx not in self.tools:
            # A new call starting: the ones whose arguments are already
            # whole are done (the sequential case). Incomplete ones stay
            # open — their fragments interleave with this one.
            out += self.close_tools(only_complete=True)
            if idx in self.closed_names:
                logger.warning("responses_tool_fragments_after_close",
                               index=idx, name=self.closed_names[idx])
            self.tools[idx] = {
                "call_id": "", "name": self.closed_names.get(idx, ""), "args": "",
                "item_id": None, "output_index": None,
            }
        slot = self.tools[idx]
        opened = slot["item_id"] is not None
        if tcd.get("id") and not opened:
            slot["call_id"] = tcd["id"]
        fn = tcd.get("function") or {}
        if fn.get("name") and not opened:
            slot["name"] = fn["name"]
        args = fn.get("arguments") or ""
        if not isinstance(args, str):
            args = json.dumps(args)
        slot["args"] += args
        if opened:
            if args:
                out.append(self._args_delta(slot, args))
        elif slot["name"] and not self._is_custom(slot):
            out += self._open_function(slot)
        elif slot["name"] and slot["output_index"] is None:
            # Custom calls are sent whole at the end, but keep their place.
            slot["output_index"] = self._alloc()
        if self.pending_text and not self._tools_incomplete():
            out += self.text_delta("")
        return out

    def _close_slot(self, slot: dict) -> list[str]:
        ev = self.ctx.event
        out: list[str] = []
        if self._is_custom(slot):
            index = slot["output_index"] if slot["output_index"] is not None else self._alloc()
            item_id = _new_id("ctc")
            call_id = slot["call_id"] or _new_id("call")
            raw = _custom_input(slot["args"])
            base = {"item_id": item_id, "output_index": index}
            out.append(ev("response.output_item.added", {
                "output_index": index,
                "item": _call_item(item_id, call_id, slot["name"], "", custom=True, status="in_progress"),
            }))
            if raw:
                out.append(ev("response.custom_tool_call_input.delta", {**base, "delta": raw}))
            out.append(ev("response.custom_tool_call_input.done", {**base, "input": raw}))
            item = _call_item(item_id, call_id, slot["name"], raw, custom=True)
        else:
            if slot["item_id"] is None:  # never saw a name: open it now
                out += self._open_function(slot)
            if not slot["args"].strip():
                slot["args"] = "{}"  # clients parse arguments as JSON
            index = slot["output_index"]
            out.append(ev("response.function_call_arguments.done", {
                "item_id": slot["item_id"], "output_index": index,
                "name": slot["name"], "arguments": slot["args"],
            }))
            item = _call_item(slot["item_id"], slot["call_id"], slot["name"], slot["args"], custom=False)
        out.append(ev("response.output_item.done", {"output_index": index, "item": item}))
        self.output[index] = item
        return out

    def close_tools(self, *, only_complete: bool = False) -> list[str]:
        out: list[str] = []
        for idx in sorted(self.tools):
            slot = self.tools[idx]
            if only_complete and not _args_complete(slot["args"]):
                continue
            del self.tools[idx]
            self.closed_names[idx] = slot["name"]
            out += self._close_slot(slot)
        return out

    def finish(self) -> list[str]:
        return self.close_text() + self.close_tools() + self.text_delta("") + self.close_text()

    def items(self) -> list[dict]:
        return [self.output[i] for i in sorted(self.output)]


async def stream_events(
    frames: AsyncIterable[dict], ctx: ResponseContext,
) -> AsyncGenerator[str, None]:
    """Transform the engine's OpenAI chunk-dict stream into Responses SSE
    events. `response.created` / `response.in_progress` go out before the
    first frame is awaited; the stream always ends in `response.completed`
    (carrying the full output and the usage from the engine's end-of-stream
    usage frame) or, for an engine error, `response.failed`."""
    state = _StreamState(ctx)
    usage: dict = {}
    finish_reason: str | None = None
    model: str | None = None
    failed = False

    try:
        initial = ctx.response(status="in_progress", output=[])
        yield ctx.event("response.created", {"response": initial})
        yield ctx.event("response.in_progress", {"response": initial})

        async for frame in frames:
            if "error" in frame and "choices" not in frame:
                err = frame.get("error") or {}
                # Consume the [DONE] the engine sends right after its error
                # frame BEFORE yielding, so finish() below drains the engine
                # to a normal completion (logged as 503 + the real error
                # type) even if the client goes away at this yield. Same
                # contract as the Anthropic transformer.
                async for _ in frames:
                    pass
                yield ctx.event("response.failed", {"response": ctx.response(
                    status="failed", output=state.items(), model=model,
                    error={
                        "code": _error_code(err.get("type")),
                        "message": err.get("message", "Upstream provider error"),
                    },
                )})
                return

            if frame.get("model") and model is None:
                model = frame["model"]
            choices = frame.get("choices") or []
            choice = choices[0] if choices else {}
            delta = choice.get("delta") or {}

            text = delta.get("content")
            if isinstance(text, str) and text:
                for ev in state.text_delta(text):
                    yield ev
            for tcd in delta.get("tool_calls") or []:
                for ev in state.tool_fragment(tcd):
                    yield ev
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            if frame.get("usage"):
                usage = frame["usage"]

        # Normal end of stream ([DONE] consumed by the frame source).
        for ev in state.finish():
            yield ev
        yield ctx.event("response.completed", {"response": ctx.response(
            status="completed", output=state.items(), usage=_usage(usage),
            model=model, finish_reason=finish_reason,
        )})
    except Exception:
        # Our own fault, not the client's: abort the engine (adapter_error)
        # rather than close it, which would read as a client disconnect.
        failed = True
        raise
    finally:
        # Last, deliberately, and shielded: this drains the engine (its
        # RequestLog commit) only after the client has the terminal event,
        # and a client disconnect's cancellation must not stop the close
        # from reaching the engine. See OpenAIFrameStream.
        with anyio.CancelScope(shield=True):
            await finish_quietly(frames, failed=failed)


def stream_error_event(ctx: ResponseContext, message: str) -> str:
    """The in-stream terminal event for a failure inside the adapter itself
    (after headers went out a non-200 is impossible)."""
    return ctx.event("response.failed", {"response": ctx.response(
        status="failed", output=[], error={"code": "server_error", "message": message},
    )})


# ── Error envelope ──────────────────────────────────────────────────────

# Engine error types whose generic engine status misstates them on this
# surface: OpenAI itself answers an unknown model with 404 and a context
# overflow with 400. The operator-side conditions (OUR provider key
# rejected, no provider configured, none capable of the request) are
# permanent until the operator acts, so — as on the Anthropic and Gemini
# surfaces — they are a non-retryable 403 rather than the engine's 503/422:
# Codex retries 5xx with backoff. Everything else keeps the engine's
# status, exactly as /v1/chat/completions reports it.
_ENGINE_ERROR_STATUS = {
    "model_not_found": 404,
    "context_length_exceeded": 400,
    "rate_limit_error": 429,
    "upstream_auth_error": 403,
    "no_providers_configured": 403,
    "no_capable_provider": 403,
    # The desktop app's refusals: only a paid model could serve the request
    # (the user has to allow paid models), or OrcaRouter is out of credit.
    # Neither succeeds on retry.
    "needs_paid_model": 403,
    # OrcaRouter refused its free models for this account: no retry helps.
    "free_unavailable": 403,
    "out_of_credit": 402,
    # A provider's own 402 (no balance left on the user's key).
    "payment_required": 402,
    # Ollama / LM Studio / llama.cpp isn't running. A 5xx would have the
    # agent back off and retry for minutes; nothing changes until the user
    # starts it, so it's a plain bad request on this surface.
    "local_runtime_unavailable": 400,
}

_STATUS_TO_ERROR_TYPE = {
    400: "invalid_request_error",
    401: "authentication_error",
    402: "insufficient_quota",
    403: "permission_error",
    404: "invalid_request_error",
    422: "invalid_request_error",
    429: "rate_limit_error",
}


def native_status(status: int, error_type: str | None) -> int:
    return _ENGINE_ERROR_STATUS.get(error_type or "", status)


def delivered_status(status: int, error_type: str | None) -> int:
    """Handed to `execute_chat(log_status=...)` so the RequestLog row
    records the status this surface actually returned."""
    return native_status(status, error_type)


def error_response(status: int, message: str, *, code: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {
            "message": message,
            "type": _STATUS_TO_ERROR_TYPE.get(status, "server_error"),
            "param": None,
            "code": code,
        }},
    )
