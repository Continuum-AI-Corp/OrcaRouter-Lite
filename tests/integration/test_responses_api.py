"""POST /v1/responses — OpenAI Responses API ingress (for Codex CLI).

Real app + mocked LiteLLM router (the `native_client` fixture shared with
the Anthropic ingress tests). Covers: auth, the OpenAI error envelope with
400 (not 422) validation failures, blocking + streaming translation, tool
and custom-tool round trips, RequestLog writeback, and the stream lifecycle
(response.completed on every non-error path, response.failed otherwise).
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

from tests.integration.test_anthropic_messages import (  # noqa: F401  (fixture)
    _openai_response,
    native_client,
)


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _payload(**overrides) -> dict:
    base: dict = {"model": "gpt-4o-mini", "input": "hi"}
    base.update(overrides)
    return base


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        lines = frame.splitlines()
        assert lines[0].startswith("event: "), f"frame missing event line: {frame!r}"
        assert lines[1].startswith("data: ")
        events.append((lines[0][len("event: "):], json.loads(lines[1][len("data: "):])))
    return events


def _chunk(delta: dict, finish_reason: str | None = None, **extra) -> dict:
    return {
        "id": "chatcmpl-1", "object": "chat.completion.chunk",
        "model": "gpt-4o-mini", "created": int(time.time()),
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        **extra,
    }


_USAGE = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}


def _stream_of(chunks: list[dict]):
    async def _acompletion(**kwargs):
        assert kwargs.get("stream")

        async def _it():
            for c in chunks:
                yield c
        return _it()
    return AsyncMock(side_effect=_acompletion)


async def _log_rows():
    from sqlalchemy import select

    from packages.db import session as session_mod
    from packages.db.models.request_log import RequestLog

    async with session_mod._session_factory() as s:
        return (await s.execute(select(RequestLog))).scalars().all()


# Shapes taken from what Codex sends with wire_api = "responses".
_SHELL_TOOL = {
    "type": "function", "name": "shell", "description": "Runs a shell command.",
    "strict": False,
    "parameters": {"type": "object", "properties": {"command": {"type": "array", "items": {"type": "string"}}},
                   "required": ["command"], "additionalProperties": False},
}
_APPLY_PATCH_TOOL = {
    "type": "custom", "name": "apply_patch", "description": "Edit files with a patch.",
    "format": {"type": "grammar", "syntax": "lark", "definition": 'start: "*** Begin Patch" LF'},
}


def _codex_payload(**overrides) -> dict:
    base = {
        "model": "gpt-4o-mini",
        "instructions": "You are Codex, a coding agent.",
        "input": [
            {"type": "message", "role": "developer",
             "content": [{"type": "input_text", "text": "<permissions>workspace-write</permissions>"}]},
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "<environment_context>cwd=/repo</environment_context>"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "list files"}]},
        ],
        "tools": [_SHELL_TOOL, _APPLY_PATCH_TOOL, {"type": "web_search"}],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning": {"effort": "medium", "summary": "auto"},
        "store": False,
        "stream": True,
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": "0199-session",
        "text": {"verbosity": "medium"},
    }
    base.update(overrides)
    return base


# ── auth & errors ──


async def test_bearer_authenticates(native_client):
    client, _, key = native_client
    r = await client.post("/v1/responses", json=_payload(), headers=_auth(key))
    assert r.status_code == 200, r.text


async def test_missing_key_is_401_openai_envelope(native_client):
    client, _, _ = native_client
    r = await client.post("/v1/responses", json=_payload())
    assert r.status_code == 401
    assert "message" in r.json()["error"]


async def test_validation_failure_is_400_openai_envelope_not_422(native_client):
    client, _, key = native_client
    r = await client.post("/v1/responses", json={"input": "hi"}, headers=_auth(key))
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["type"] == "invalid_request_error"
    assert "model" in err["message"]

    r = await client.post("/v1/responses", json=_payload(input=5), headers=_auth(key))
    assert r.status_code == 400


async def test_malformed_json_and_non_object_bodies_are_400(native_client):
    client, _, key = native_client
    r = await client.post("/v1/responses", content=b"{nope",
                          headers={**_auth(key), "content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"
    r = await client.post("/v1/responses", json=[1], headers=_auth(key))
    assert r.status_code == 400


async def test_previous_response_id_is_rejected_with_a_clear_400(native_client):
    client, fake, key = native_client
    r = await client.post("/v1/responses", json=_payload(previous_response_id="resp_1"),
                          headers=_auth(key))
    assert r.status_code == 400
    assert "previous_response_id" in r.json()["error"]["message"]
    fake.acompletion.assert_not_awaited()


async def test_upstream_failure_keeps_engine_status_in_openai_envelope(native_client):
    client, fake, key = native_client
    fake.acompletion = AsyncMock(side_effect=RuntimeError("provider exploded"))
    r = await client.post("/v1/responses", json=_payload(), headers=_auth(key))
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["type"] == "server_error"
    assert "provider exploded" in err["message"]


async def test_streaming_request_failing_before_the_stream_is_a_json_error(native_client):
    client, fake, key = native_client
    fake.acompletion = AsyncMock(side_effect=RuntimeError("provider exploded"))
    r = await client.post("/v1/responses", json=_payload(stream=True), headers=_auth(key))
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/json")
    assert "error" in r.json()


async def test_model_not_found_is_404_and_logged_as_delivered(native_client):
    client, fake, key = native_client
    from packages.litellm_adapter.types import UpstreamProviderError

    fake.acompletion = AsyncMock(side_effect=UpstreamProviderError(
        "model does not exist", http_status=422, error_type="model_not_found",
    ))
    r = await client.post("/v1/responses", json=_payload(), headers=_auth(key))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"
    (row,) = await _log_rows()
    assert row.status_code == 404


async def test_model_outside_the_key_allowlist_is_403(native_client):
    client, _, _ = native_client
    from packages.auth.hashing import generate_api_key
    from packages.db import session as session_mod
    from packages.db.models.api_key import ApiKey

    restricted, h, prefix = generate_api_key()
    async with session_mod._session_factory() as s:
        s.add(ApiKey(workspace_id="default", name="restricted", key_hash=h, key_prefix=prefix,
                     model_allowlist=["gpt-4o"]))
        await s.commit()
    r = await client.post("/v1/responses", json=_payload(), headers=_auth(restricted))
    assert r.status_code == 403
    assert r.json()["error"]["type"] == "permission_error"


# ── blocking ──


async def test_blocking_response_shape_and_translated_engine_body(native_client):
    client, fake, key = native_client
    r = await client.post("/v1/responses", json=_payload(
        instructions="Be brief.", max_output_tokens=64, temperature=0.3,
    ), headers=_auth(key))
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "response"
    assert body["id"].startswith("resp_")
    assert body["status"] == "completed"
    (item,) = body["output"]
    assert item["type"] == "message"
    assert item["content"] == [{"type": "output_text", "text": "Hello world", "annotations": []}]
    assert body["usage"]["input_tokens"] == 4
    assert body["usage"]["output_tokens"] == 2
    assert body["usage"]["total_tokens"] == 6
    assert r.headers["x-orca-resolved-model"] == "gpt-4o-mini"

    kwargs = fake.acompletion.call_args.kwargs
    assert kwargs["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "hi"},
    ]
    assert kwargs["max_tokens"] == 64
    assert kwargs["temperature"] == 0.3


async def test_blocking_tool_calls_including_custom_tool(native_client):
    client, fake, key = native_client

    async def _tool_response(**kwargs):
        return _openai_response(message={
            "role": "assistant", "content": None,
            "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "shell", "arguments": '{"command": ["ls"]}'}},
                {"id": "call_2", "type": "function",
                 "function": {"name": "apply_patch",
                              "arguments": json.dumps({"input": "*** Begin Patch\n*** End Patch"})}},
            ],
        }, finish_reason="tool_calls")

    fake.acompletion = AsyncMock(side_effect=_tool_response)
    r = await client.post("/v1/responses", json=_codex_payload(stream=False), headers=_auth(key))
    assert r.status_code == 200, r.text
    fc, ctc = r.json()["output"]
    assert fc["type"] == "function_call"
    assert fc["call_id"] == "call_1"
    assert fc["arguments"] == '{"command": ["ls"]}'
    assert ctc["type"] == "custom_tool_call"
    assert ctc["call_id"] == "call_2"
    assert ctc["input"] == "*** Begin Patch\n*** End Patch"

    kwargs = fake.acompletion.call_args.kwargs
    assert [t["function"]["name"] for t in kwargs["tools"]] == ["shell", "apply_patch"]
    assert kwargs["parallel_tool_calls"] is False
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["messages"][0] == {"role": "system", "content": "You are Codex, a coding agent."}
    assert kwargs["messages"][1] == {"role": "system", "content": "<permissions>workspace-write</permissions>"}


# ── streaming ──


async def test_streaming_text_event_sequence_and_request_log(native_client):
    client, _, key = native_client
    r = await client.post("/v1/responses", json=_payload(stream=True), headers=_auth(key))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "[DONE]" not in r.text
    events = _parse_sse(r.text)
    assert [n for n, _ in events] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [d["sequence_number"] for _, d in events] == list(range(len(events)))
    completed = events[-1][1]["response"]
    assert completed["status"] == "completed"
    assert completed["output"][0]["content"][0]["text"] == "Hello world"
    assert completed["usage"]["input_tokens"] == 4
    assert completed["usage"]["output_tokens"] == 2

    (row,) = await _log_rows()
    assert row.is_streaming is True
    assert row.status_code == 200
    assert row.input_tokens == 4
    assert row.output_tokens == 2


async def test_streaming_codex_request_with_text_and_two_tool_calls(native_client):
    client, fake, key = native_client
    fake.acompletion = _stream_of([
        _chunk({"role": "assistant", "content": "Listing."}),
        _chunk({"tool_calls": [{"index": 0, "id": "call_a", "type": "function",
                                "function": {"name": "shell", "arguments": ""}}]}),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"command": ["ls"]}'}}]}),
        _chunk({"tool_calls": [{"index": 1, "id": "call_b", "type": "function",
                                "function": {"name": "shell", "arguments": '{"command": '}}]}),
        _chunk({"tool_calls": [{"index": 1, "function": {"arguments": '["pwd"]}'}}]}),
        _chunk({}, "tool_calls"),
        _chunk({}, usage=_USAGE),
    ])
    r = await client.post("/v1/responses", json=_codex_payload(), headers=_auth(key))
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert [n for n, _ in events] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    output = events[-1][1]["response"]["output"]
    assert [(o["type"], o.get("call_id"), o.get("arguments")) for o in output] == [
        ("message", None, None),
        ("function_call", "call_a", '{"command": ["ls"]}'),
        ("function_call", "call_b", '{"command": ["pwd"]}'),
    ]
    # Codex-only fields never reach the engine; the hosted tool is dropped.
    kwargs = fake.acompletion.call_args.kwargs
    for absent in ("store", "include", "prompt_cache_key", "reasoning", "text", "instructions"):
        assert absent not in kwargs
    assert [t["function"]["name"] for t in kwargs["tools"]] == ["shell", "apply_patch"]


async def test_streaming_custom_tool_round_trip(native_client):
    """The model calls Codex's freeform apply_patch: it goes out as a
    custom_tool_call; Codex sends it back with its output next turn, and
    the engine sees an ordinary tool call + tool message."""
    client, fake, key = native_client
    patch = "*** Begin Patch\n*** Add File: hello.txt\n+hi\n*** End Patch\n"
    fake.acompletion = _stream_of([
        _chunk({"tool_calls": [{"index": 0, "id": "call_p", "type": "function",
                                "function": {"name": "apply_patch",
                                             "arguments": json.dumps({"input": patch})}}]}),
        _chunk({}, "tool_calls", usage=_USAGE),
    ])
    r = await client.post("/v1/responses", json=_codex_payload(), headers=_auth(key))
    events = _parse_sse(r.text)
    done = [d["item"] for n, d in events if n == "response.output_item.done"]
    assert done == [{"id": done[0]["id"], "type": "custom_tool_call", "status": "completed",
                     "call_id": "call_p", "name": "apply_patch", "input": patch}]
    assert events[-1][0] == "response.completed"

    fake.acompletion = _stream_of([_chunk({"content": "Created."}), _chunk({}, "stop", usage=_USAGE)])
    payload = _codex_payload()
    payload["input"] = payload["input"] + [
        done[0],
        {"type": "custom_tool_call_output", "call_id": "call_p",
         "output": "Success. Updated the following files:\nA hello.txt"},
    ]
    r = await client.post("/v1/responses", json=payload, headers=_auth(key))
    assert _parse_sse(r.text)[-1][0] == "response.completed"
    messages = fake.acompletion.call_args.kwargs["messages"]
    assert messages[-2] == {"role": "assistant", "tool_calls": [{
        "id": "call_p", "type": "function",
        "function": {"name": "apply_patch", "arguments": json.dumps({"input": patch})},
    }]}
    assert messages[-1] == {"role": "tool", "tool_call_id": "call_p",
                            "content": "Success. Updated the following files:\nA hello.txt"}


async def test_streaming_upstream_error_ends_with_response_failed(native_client):
    client, fake, key = native_client

    async def _acompletion(**kwargs):
        async def _it():
            yield _chunk({"content": "partial"})
            raise RuntimeError("connection reset by provider")
        return _it()

    fake.acompletion = AsyncMock(side_effect=_acompletion)
    r = await client.post("/v1/responses", json=_payload(stream=True), headers=_auth(key))
    assert r.status_code == 200
    events = _parse_sse(r.text)
    names = [n for n, _ in events]
    assert names[-1] == "response.failed"
    assert "response.completed" not in names
    failed = events[-1][1]["response"]
    assert failed["status"] == "failed"
    assert "connection reset by provider" in failed["error"]["message"]
    assert failed["error"]["code"]

    (row,) = await _log_rows()
    assert row.status_code == 503


async def test_adapter_failure_mid_stream_renders_response_failed(native_client, monkeypatch):
    client, _, key = native_client
    from app.protocols import responses as proto
    from app.routes import responses_compat

    real = proto.stream_events

    async def exploding(frames, ctx):
        async for ev in real(frames, ctx):
            yield ev
            raise RuntimeError("adapter bug")

    monkeypatch.setattr(responses_compat.proto, "stream_events", exploding)
    r = await client.post("/v1/responses", json=_payload(stream=True), headers=_auth(key))
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[0][0] == "response.created"
    assert events[-1][0] == "response.failed"
    assert events[-1][1]["response"]["error"] == {"code": "server_error", "message": "Internal server error"}
    seqs = [d["sequence_number"] for _, d in events]
    assert seqs == sorted(seqs)


async def test_streaming_client_disconnect_closes_upstream_and_logs_499(native_client):
    import asyncio

    client, fake, key = native_client

    class _CancellingStream:
        def __init__(self):
            self.closed = False
            self._yielded = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._yielded:
                self._yielded = True
                return _chunk({"content": "Hi"})
            raise asyncio.CancelledError()

        async def aclose(self):
            self.closed = True

    slow = _CancellingStream()
    fake.acompletion = AsyncMock(return_value=slow)
    try:
        async with client.stream("POST", "/v1/responses", json=_payload(stream=True),
                                 headers=_auth(key)) as response:
            assert response.status_code == 200
            async for _ in response.aiter_lines():
                pass
    except Exception:
        pass
    await asyncio.sleep(0.2)

    assert slow.closed is True
    (row,) = await _log_rows()
    assert row.status_code == 499
    assert row.error_type == "client_disconnect"
