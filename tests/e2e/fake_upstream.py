"""A stand-in OpenAI-compatible provider for the end-to-end tests.

The engine under test reaches it through OPENAI_BASE_URL, so every request
an agent sends travels the real path: agent protocol → Lite → LiteLLM →
this server. It records what it received at /_calls.
"""

from __future__ import annotations

import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
CALLS: list[dict] = []
# Big enough that a few requests cost real cents, so the budget stop can trip.
USAGE = {"prompt_tokens": 200_000, "completion_tokens": 100_000, "total_tokens": 300_000}


@app.get("/v1/models")
async def models(request: Request):
    # Like a real provider: a wrong key is refused, which setup's key check relies on.
    if request.headers.get("authorization", "") != "Bearer sk-e2e-upstream":
        return JSONResponse({"error": {"message": "Incorrect API key provided"}}, status_code=401)
    return {"object": "list", "data": [{"id": "gpt-4o-mini", "object": "model", "owned_by": "e2e"}]}


@app.get("/_calls")
async def calls() -> dict:
    return {"calls": CALLS}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    CALLS.append({"model": body.get("model"), "stream": bool(body.get("stream")),
                  "auth": request.headers.get("authorization", "")})
    if STATE["openai"] == "down":  # a stopped provider (the Test button's e2e)
        return JSONResponse({"error": {"message": "Service unavailable", "type": "server_error"}}, status_code=503)
    base = {"id": "chatcmpl-e2e", "created": int(time.time()), "model": body.get("model", "gpt-4o-mini")}
    messages = body.get("messages") or []
    if body.get("tools") and messages and messages[-1].get("role") == "user":
        return _tool_call(body, base)
    if messages and messages[-1].get("role") == "tool":
        return _answer(body, base, f"done: {messages[-1].get('content')}")
    if body.get("stream"):
        async def frames():
            chunk = {**base, "object": "chat.completion.chunk"}
            yield f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'pong'}, 'finish_reason': None}]})}\n\n"
            yield f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            if (body.get("stream_options") or {}).get("include_usage"):
                yield f"data: {json.dumps({**chunk, 'choices': [], 'usage': USAGE})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(frames(), media_type="text/event-stream")
    return {**base, "object": "chat.completion", "usage": USAGE,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}]}


# Like a real model offered tools: first call one (its arguments arrive in
# pieces when streaming), then answer once the tool's result comes back.
TOOL_ARGS = json.dumps({"path": "README.md"})


def _tool_call(body, base):
    name = body["tools"][0]["function"]["name"]
    call = {"id": "call_e2e", "type": "function", "function": {"name": name, "arguments": TOOL_ARGS}}
    if not body.get("stream"):
        return {**base, "object": "chat.completion", "usage": USAGE,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [call]},
                             "finish_reason": "tool_calls"}]}

    async def frames():
        chunk = {**base, "object": "chat.completion.chunk"}
        first = {"index": 0, "id": "call_e2e", "type": "function", "function": {"name": name, "arguments": ""}}
        yield f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'tool_calls': [first]}, 'finish_reason': None}]})}\n\n"
        for piece in (TOOL_ARGS[:6], TOOL_ARGS[6:]):
            delta = {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}
            yield f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})}\n\n"
        if (body.get("stream_options") or {}).get("include_usage"):
            yield f"data: {json.dumps({**chunk, 'choices': [], 'usage': USAGE})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(frames(), media_type="text/event-stream")


# ── more providers, for the routing e2e (tests/e2e/test_routing_e2e.py) ──
# Each lives under its own path prefix; the engine reaches them through the
# provider's base-URL variable (ORCAROUTER_BASE_URL, ANTHROPIC_BASE_URL,
# MOONSHOT_API_BASE). POST /_state switches how they behave.

STATE = {"anthropic": "ok", "orca": "ok", "openai": "ok"}
KEYS = {"orca": "Bearer sk-orca-e2e-key", "moonshot": "Bearer sk-moonshot-e2e"}
HOSTED_COST_USD = "0.0123"


@app.post("/_state")
async def set_state(request: Request) -> dict:
    STATE.update(await request.json())
    return STATE


def _record(upstream: str, request: Request, body: dict) -> None:
    CALLS.append({"upstream": upstream, "model": body.get("model"), "stream": bool(body.get("stream")),
                  "auth": request.headers.get("authorization") or request.headers.get("x-api-key", ""),
                  "images": "image_url" in json.dumps(body.get("messages") or [])})


def _keyed_models(prefix: str):
    async def models(request: Request):
        if request.headers.get("authorization", "") != KEYS[prefix]:
            return JSONResponse({"error": {"message": "Invalid API key"}}, status_code=401)
        return {"object": "list", "data": [{"id": "e2e-model", "object": "model"}]}
    return models


app.get("/orca/v1/models")(_keyed_models("orca"))
app.get("/moonshot/v1/models")(_keyed_models("moonshot"))


@app.post("/orca/v1/chat/completions")
async def orca_chat(request: Request):
    """OrcaRouter: reports each request's cost, or 402 once out of credit."""
    body = await request.json()
    _record("orca", request, body)
    if STATE["orca"] == "no_credit":
        return JSONResponse({"error": {"message": "Insufficient credit", "type": "insufficient_quota"}},
                            status_code=402)
    cost = "0" if "free" in body.get("model", "") else HOSTED_COST_USD
    response = await chat_reply(body)
    response.headers["X-OrcaRouter-beta-usd"] = cost
    return response


@app.post("/moonshot/v1/chat/completions")
async def moonshot_chat(request: Request):
    body = await request.json()
    _record("moonshot", request, body)
    return await chat_reply(body)


async def chat_reply(body: dict):
    base = {"id": "chatcmpl-e2e", "created": int(time.time()), "model": body.get("model", "")}
    if body.get("stream"):
        return _answer(body, base, "pong")
    return JSONResponse({**base, "object": "chat.completion", "usage": USAGE, "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}]})


@app.post("/anthropic/v1/messages")
async def anthropic_messages(request: Request):
    """Anthropic's own API: overloaded (529) when told to be."""
    body = await request.json()
    _record("anthropic", request, body)
    if STATE["anthropic"] == "overloaded":
        return JSONResponse({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
                            status_code=529)
    return {"id": "msg_e2e", "type": "message", "role": "assistant", "model": body.get("model"),
            "content": [{"type": "text", "text": "pong"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 100}}


def _answer(body, base, text):
    if not body.get("stream"):
        return {**base, "object": "chat.completion", "usage": USAGE,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}

    async def frames():
        chunk = {**base, "object": "chat.completion.chunk"}
        yield f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': text}, 'finish_reason': None}]})}\n\n"
        yield f"data: {json.dumps({**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
        if (body.get("stream_options") or {}).get("include_usage"):
            yield f"data: {json.dumps({**chunk, 'choices': [], 'usage': USAGE})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(frames(), media_type="text/event-stream")
