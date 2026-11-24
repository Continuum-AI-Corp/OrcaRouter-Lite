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
