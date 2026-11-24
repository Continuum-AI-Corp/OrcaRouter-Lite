"""A stand-in Ollama for the routing e2e: one coding model with tools and a
32K context, answering /api/chat (blocking or NDJSON streaming) the way
Ollama does. The engine finds it through OLLAMA_HOST. It records what it
received at /_calls; the test stops the process to check the cloud takes
over."""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
CALLS: list[dict] = []
MODEL = "qwen3-coder:30b"


@app.get("/api/tags")
async def tags() -> dict:
    return {"models": [{"name": MODEL, "model": MODEL, "size": 1}]}


@app.post("/api/show")
async def show(request: Request) -> dict:
    return {"capabilities": ["completion", "tools"], "model_info": {"qwen3moe.context_length": 32768}}


@app.get("/_calls")
async def calls() -> dict:
    return {"calls": CALLS}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    CALLS.append({"model": body.get("model"), "stream": bool(body.get("stream")),
                  "num_ctx": (body.get("options") or {}).get("num_ctx"), "tools": bool(body.get("tools"))})
    done = {"model": body.get("model"), "created_at": "2026-11-24T00:00:00Z", "done": True, "done_reason": "stop",
            "prompt_eval_count": 1200, "eval_count": 300}
    if not body.get("stream"):
        return {**done, "message": {"role": "assistant", "content": "pong from ollama"}}

    async def lines():
        piece = {"model": body.get("model"), "created_at": "2026-11-24T00:00:00Z", "done": False,
                 "message": {"role": "assistant", "content": "pong from ollama"}}
        yield json.dumps(piece) + "\n"
        yield json.dumps({**done, "message": {"role": "assistant", "content": ""}}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")
