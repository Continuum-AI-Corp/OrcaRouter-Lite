# ruff: noqa: F811  (fixture imported from a sibling module)
"""Explicit cache policy must survive ingress through provider serialization.

Only the provider HTTP transport is replaced; the schema, handler, Orca
adapter, LiteLLM Router and OpenAI SDK all execute their real request path.
"""

from __future__ import annotations

import json
from functools import partial

import httpx
import pytest
from openai import AsyncOpenAI

from tests.integration.test_chat_completion import chat_client  # noqa: F401


@pytest.fixture
async def provider_client(chat_client, monkeypatch):
    from app import router_cache
    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import ProviderDeployment

    client, _ = chat_client
    received = []

    def respond(request):
        body = json.loads(request.content)
        received.append(body)
        common = {"id": "chatcmpl-policy", "model": body["model"], "created": 1}
        if body.get("stream"):
            chunk = {
                **common,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
            }
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
            )
        return httpx.Response(200, json={
            **common,
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as upstream:
        async with AsyncOpenAI(
            api_key="sk-test", base_url="https://provider.invalid/v1", http_client=upstream,
        ) as sdk:
            adapter = OrcaLiteLLMClient(deployments=[
                ProviderDeployment(model_name=model, litellm_model=f"openai/{model}",
                                   api_key="sk-test", provider="openai")
                for model in ("gpt-5.6",)
            ], num_retries=0)
            # Inject the transport-backed SDK without replacing any conversion.
            monkeypatch.setattr(
                adapter._router, "acompletion", partial(adapter._router.acompletion, client=sdk),
            )

            async def get_router(_session):
                return adapter

            monkeypatch.setattr(router_cache, "get_router", get_router)
            yield client, received


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("model,controls", [
    ("gpt-5.6", {"prompt_cache_key": "prefix-family",
                 "prompt_cache_options": {"mode": "explicit", "ttl": "30m"}}),
    ("gpt-5.6", {"prompt_cache_options": {"mode": "implicit"}}),
    ("gpt-5.6", {"prompt_cache_key": "", "prompt_cache_options": {}}),
    ("gpt-5.6", {}),
    ("gpt-5.6", {"prompt_cache_key": None, "prompt_cache_options": None}),
])
async def test_cache_controls_reach_openai_payload(provider_client, stream, model, controls):
    client, received = provider_client
    response = await client.post("/v1/chat/completions", json={
        "model": model, "messages": [{"role": "user", "content": "hi"}],
        "stream": stream, **controls,
    })
    assert response.status_code == 200, response.text
    if not stream:
        assert response.headers["x-orca-cache"] == "BYPASS"
    assert len(received) == 1
    wire = received[0]
    assert wire["messages"] == [{"role": "user", "content": "hi"}]
    for field in ("prompt_cache_key", "prompt_cache_options"):
        if field in controls and controls[field] is not None:
            assert wire.get(field) == controls[field], f"{field} lost before provider serialization"
        else:
            assert field not in wire
