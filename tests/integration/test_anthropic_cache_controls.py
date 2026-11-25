# ruff: noqa: F811  (fixture imported from a sibling module)
"""Native cache policies must survive the real LiteLLM Anthropic payload.

Provider dispatch uses the real LiteLLM request transformations and a
deterministic response. No optional MCP server or network is needed.
"""

from __future__ import annotations

import json
from copy import deepcopy
from functools import partial

import httpx
import pytest
from openai import AsyncOpenAI

from tests.integration.test_anthropic_messages import native_client  # noqa: F401


@pytest.fixture
async def anthropic_provider(native_client, monkeypatch):
    import litellm
    from litellm.llms.anthropic.chat.transformation import AnthropicConfig

    from app import router_cache
    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import ProviderDeployment

    client, fake, key = native_client
    received = []
    reply = fake.acompletion.side_effect

    async def transform_and_reply(**kwargs):
        config = AnthropicConfig()
        params = {k: v for k, v in kwargs.items() if k not in {"model", "messages"}}
        optional = config.map_openai_params(
            non_default_params=params, optional_params={}, model=kwargs["model"], drop_params=False,
        )
        received.append(config.transform_request(
            model=kwargs["model"], messages=deepcopy(kwargs["messages"]),
            optional_params=optional, litellm_params={}, headers={},
        ))
        return await reply(**kwargs)

    fake.acompletion.side_effect = transform_and_reply
    monkeypatch.setattr(litellm, "Router", lambda **_: fake)
    adapter = OrcaLiteLLMClient(deployments=[ProviderDeployment(
        model_name="claude-3-5-sonnet-latest",
        litellm_model="anthropic/claude-3-5-sonnet-latest",
        api_key="sk-test", provider="anthropic",
    )], num_retries=0)
    async def get_router(_session):
        return adapter

    monkeypatch.setattr(router_cache, "get_router", get_router)
    yield client, key, received


@pytest.fixture
async def openai_provider(native_client, monkeypatch):
    from app import router_cache
    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import ProviderDeployment

    client, _, key = native_client
    received = []

    def respond(request):
        body = json.loads(request.content)
        received.append(body)
        common = {"id": "chatcmpl-policy", "model": body["model"], "created": 1}
        if body.get("stream"):
            chunk = {**common, "object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"},
            ]}
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json={
            **common, "object": "chat.completion", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"},
            ], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as upstream:
        async with AsyncOpenAI(api_key="sk-test", http_client=upstream) as sdk:
            adapter = OrcaLiteLLMClient(deployments=[ProviderDeployment(
                model_name="gpt-4o-mini", litellm_model="openai/gpt-4o-mini",
                api_key="sk-test", provider="openai",
            )], num_retries=0)
            monkeypatch.setattr(
                adapter._router, "acompletion", partial(adapter._router.acompletion, client=sdk),
            )

            async def get_router(_session):
                return adapter

            monkeypatch.setattr(router_cache, "get_router", get_router)
            yield client, key, received


async def _send(provider, *, stream=False, **overrides):
    client, key, received = provider
    response = await client.post("/v1/messages", headers={"x-api-key": key}, json={
        "model": "claude-3-5-sonnet-latest", "max_tokens": 32,
        "messages": [{"role": "user", "content": "hi"}], "stream": stream,
        **overrides,
    })
    assert response.status_code == 200, response.text
    assert len(received) == 1
    return received[0]


@pytest.mark.parametrize("stream", [False, True])
async def test_system_content_and_tool_breakpoints_reach_provider(anthropic_provider, stream):
    wire = await _send(anthropic_provider, stream=stream,
        system=[
            {"type": "text", "text": "prefix", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "suffix"},
        ],
        tools=[{"name": "lookup", "input_schema": {"type": "object"},
                "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        ]}],
    )
    assert wire["system"] == [
        {"type": "text", "text": "prefix", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        {"type": "text", "text": "suffix"},
    ]
    assert wire["tools"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert wire["messages"][0]["content"] == [
        {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
    ]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("policy", [
    {"type": "ephemeral"}, {"type": "ephemeral", "ttl": "5m"},
    {"type": "ephemeral", "ttl": "1h"},
])
async def test_automatic_cache_policy_reaches_provider(anthropic_provider, stream, policy):
    wire = await _send(anthropic_provider, stream=stream, cache_control=policy)
    # The documented automatic-policy equivalent is an explicit breakpoint
    # on the last cacheable block, avoiding Anthropic-only top-level extras
    # when the same native ingress resolves to another provider.
    assert wire["messages"][0]["content"] == [
        {"type": "text", "text": "hi", "cache_control": policy},
    ]
    assert "cache_control" not in wire


async def test_automatic_policy_uses_last_rendered_block_after_existing_grouping(anthropic_provider):
    wire = await _send(anthropic_provider,
        cache_control={"type": "ephemeral", "ttl": "1h"},
        tools=[{"name": "lookup", "input_schema": {"type": "object"}}],
        messages=[
            {"role": "user", "content": "lookup"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}},
                {"type": "text", "text": "checking"},
            ]},
        ],
    )
    # The established translator groups assistant text before calls. The
    # automatic policy must cover the final rendered call, as a top-level
    # policy on this same Anthropic payload would, rather than stop early.
    assert wire["messages"][-1]["content"] == [
        {"type": "text", "text": "checking"},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {},
         "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ]


@pytest.mark.parametrize("stream", [False, True])
async def test_tool_use_and_result_breakpoints_keep_content(anthropic_provider, stream):
    wire = await _send(anthropic_provider, stream=stream,
        tools=[{"name": "lookup", "input_schema": {"type": "object"}}],
        messages=[
            {"role": "user", "content": "lookup"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "checking", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "x"},
                 "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "found",
                 "cache_control": {"type": "ephemeral", "ttl": "5m"}},
            ]},
        ],
    )
    assert wire["messages"][1]["content"] == [
        {"type": "text", "text": "checking", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "x"},
         "cache_control": {"type": "ephemeral", "ttl": "1h"}},
    ]
    assert wire["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": "found",
         "cache_control": {"type": "ephemeral", "ttl": "5m"}},
    ]


@pytest.mark.parametrize("stream", [False, True])
async def test_native_cache_policy_does_not_leak_to_openai_wire(openai_provider, stream):
    wire = await _send(openai_provider, stream=stream, model="gpt-4o-mini",
        cache_control={"type": "ephemeral", "ttl": "1h"},
        system=[{"type": "text", "text": "prefix", "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
        messages=[
            {"role": "user", "content": "look"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {},
                 "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                    {"type": "text", "text": "found"},
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png", "data": "aGk=",
                    }},
                ]},
            ]},
        ],
    )
    assert "cache_control" not in json.dumps(wire)
    tool_message = next(m for m in wire["messages"] if m["role"] == "tool")
    assert tool_message["tool_call_id"] == "toolu_1"
    assert tool_message["content"] == "found"
    assert wire["messages"][-1]["role"] == "user"
    assert wire["messages"][-1]["content"][-1] == {
        "type": "image_url", "image_url": {"url": "data:image/png;base64,aGk="},
    }


@pytest.mark.parametrize("stream", [False, True])
async def test_marked_image_and_nested_tool_content_reach_provider(anthropic_provider, stream):
    image = {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": "aGk=",
    }, "cache_control": {"type": "ephemeral", "ttl": "5m"}}
    wire = await _send(anthropic_provider, stream=stream,
        tools=[{"name": "lookup", "input_schema": {"type": "object"}}],
        messages=[
            {"role": "user", "content": [image]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                    {"type": "text", "text": "found", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
                    image,
                ]},
            ]},
        ],
    )
    assert wire["messages"][0]["content"] == [image]
    assert wire["messages"][2]["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
            {"type": "text", "text": "found", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
            image,
        ]},
    ]
