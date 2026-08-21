"""Smoke test for the native Anthropic + Gemini protocol endpoints.

Runs against a LIVE OrcaRouter Lite server with at least one real provider
key configured (real completions are made — a few cents of spend). Wire-level
checks use httpx (always available); when the official `anthropic` /
`google-genai` SDKs are installed, true SDK-compatibility checks run too.

Usage:
    # server side: docker compose up   (with a provider key in .env)
    ORCA_API_KEY=sk-orca-... PYTHONPATH=. python scripts/smoke_native.py

    # optional:
    ORCA_BASE_URL=http://localhost:8000   (default)
    ORCA_SMOKE_MODEL=auto                 (default; any catalog model works)

Exit code 0 = every check passed.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE_URL = os.environ.get("ORCA_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("ORCA_API_KEY", "")
MODEL = os.environ.get("ORCA_SMOKE_MODEL", "auto")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrap(fn):
        def run():
            try:
                detail = fn() or ""
                RESULTS.append((name, True, detail))
                print(f"  ✓ {name}" + (f" — {detail}" if detail else ""))
            except Exception as exc:  # noqa: BLE001 - report, don't crash the suite
                RESULTS.append((name, False, str(exc)))
                print(f"  ✗ {name} — {exc}")
        return run
    return wrap


# ── wire-level: Anthropic /v1/messages ──────────────────────────────────

@check("anthropic blocking (httpx)")
def anthropic_blocking():
    r = httpx.post(
        f"{BASE_URL}/v1/messages",
        headers={"x-api-key": API_KEY},
        json={
            "model": MODEL,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        },
        timeout=120,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body["type"] == "message" and body["role"] == "assistant", body
    assert body["content"] and body["content"][0]["type"] == "text", body
    assert body["usage"]["output_tokens"] > 0, body["usage"]
    return f"model={r.headers.get('x-orca-resolved-model')}"


@check("anthropic streaming (httpx)")
def anthropic_streaming():
    events: list[str] = []
    with httpx.stream(
        "POST", f"{BASE_URL}/v1/messages",
        headers={"x-api-key": API_KEY},
        json={
            "model": MODEL, "max_tokens": 64, "stream": True,
            "messages": [{"role": "user", "content": "Count to three."}],
        },
        timeout=120,
    ) as r:
        assert r.status_code == 200, f"HTTP {r.status_code}"
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                events.append(line[len("event: "):])
    assert events[0] == "message_start", events[:3]
    assert events[-1] == "message_stop", events[-3:]
    assert "content_block_delta" in events, events
    return f"{len(events)} events"


@check("anthropic tool use (httpx)")
def anthropic_tool_use():
    r = httpx.post(
        f"{BASE_URL}/v1/messages",
        headers={"x-api-key": API_KEY},
        json={
            "model": MODEL,
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "What's the weather in Paris?"}],
            "tools": [{
                "name": "get_weather",
                "description": "Get current weather for a city",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }],
            "tool_choice": {"type": "any"},
        },
        timeout=120,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    tool_blocks = [b for b in body["content"] if b["type"] == "tool_use"]
    assert tool_blocks, f"no tool_use block; stop_reason={body['stop_reason']}"
    assert tool_blocks[0]["name"] == "get_weather", tool_blocks[0]
    assert isinstance(tool_blocks[0]["input"], dict), tool_blocks[0]
    return f"stop_reason={body['stop_reason']}"


@check("anthropic count_tokens (httpx)")
def anthropic_count_tokens():
    r = httpx.post(
        f"{BASE_URL}/v1/messages/count_tokens",
        headers={"x-api-key": API_KEY},
        json={"model": MODEL,
              "messages": [{"role": "user", "content": "hello there"}]},
        timeout=30,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    tokens = r.json()["input_tokens"]
    assert isinstance(tokens, int) and tokens > 0, tokens
    return f"input_tokens={tokens}"


# ── wire-level: Gemini /v1beta ──────────────────────────────────────────

@check("gemini blocking (httpx)")
def gemini_blocking():
    r = httpx.post(
        f"{BASE_URL}/v1beta/models/{MODEL}:generateContent",
        headers={"x-goog-api-key": API_KEY},
        json={"contents": [{"role": "user",
                            "parts": [{"text": "Reply with exactly: pong"}]}]},
        timeout=120,
    )
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    cand = body["candidates"][0]
    assert cand["content"]["parts"][0]["text"], body
    assert body["usageMetadata"]["candidatesTokenCount"] > 0, body["usageMetadata"]
    return f"finishReason={cand['finishReason']}"


@check("gemini streaming alt=sse (httpx)")
def gemini_streaming():
    frames: list[dict] = []
    with httpx.stream(
        "POST", f"{BASE_URL}/v1beta/models/{MODEL}:streamGenerateContent?alt=sse",
        headers={"x-goog-api-key": API_KEY},
        json={"contents": [{"role": "user", "parts": [{"text": "Count to three."}]}]},
        timeout=120,
    ) as r:
        assert r.status_code == 200, f"HTTP {r.status_code}"
        for line in r.iter_lines():
            if line.startswith("data: "):
                frames.append(json.loads(line[len("data: "):]))
    assert frames, "no SSE frames"
    assert frames[-1]["candidates"][0].get("finishReason"), frames[-1]
    assert "usageMetadata" in frames[-1], frames[-1]
    return f"{len(frames)} frames"


@check("gemini model listing (httpx)")
def gemini_models():
    r = httpx.get(f"{BASE_URL}/v1beta/models",
                  headers={"x-goog-api-key": API_KEY}, timeout=30)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    models = r.json()["models"]
    assert models and models[0]["name"].startswith("models/"), models[:1]
    return f"{len(models)} models"


# ── SDK-level (run when installed) ──────────────────────────────────────

@check("anthropic SDK blocking + stream")
def anthropic_sdk():
    try:
        from anthropic import Anthropic
    except ImportError:
        return "SKIPPED (pip install anthropic)"
    client = Anthropic(base_url=BASE_URL, api_key=API_KEY)
    msg = client.messages.create(
        model=MODEL, max_tokens=64,
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
    )
    assert msg.content[0].text, msg
    chunks = []
    with client.messages.stream(
        model=MODEL, max_tokens=64,
        messages=[{"role": "user", "content": "Count to three."}],
    ) as stream:
        for text in stream.text_stream:
            chunks.append(text)
    assert "".join(chunks), "empty stream"
    return f"blocking + {len(chunks)} stream chunks"


@check("google-genai SDK blocking + stream")
def gemini_sdk():
    try:
        from google import genai
        from google.genai.types import HttpOptions
    except ImportError:
        return "SKIPPED (pip install google-genai)"
    client = genai.Client(api_key=API_KEY,
                          http_options=HttpOptions(base_url=BASE_URL))
    resp = client.models.generate_content(
        model=MODEL, contents="Reply with exactly: pong",
    )
    assert resp.text, resp
    chunks = [c for c in client.models.generate_content_stream(
        model=MODEL, contents="Count to three.",
    )]
    assert chunks, "empty stream"
    return f"blocking + {len(chunks)} stream chunks"


def main() -> int:
    if not API_KEY:
        print("ORCA_API_KEY is required (the sk-orca-* key printed at server startup).")
        return 2
    print(f"Native-protocol smoke against {BASE_URL} (model={MODEL})\n")
    for fn in (
        anthropic_blocking, anthropic_streaming, anthropic_tool_use,
        anthropic_count_tokens, gemini_blocking, gemini_streaming,
        gemini_models, anthropic_sdk, gemini_sdk,
    ):
        fn()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed"
          + (f" — FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
