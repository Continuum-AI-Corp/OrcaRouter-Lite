"""Unit tests for OrcaLiteLLMClient — focused on the stream/non-stream branch.

Round 5 of /codex review caught a real production bug: the adapter always
called `model_dump()` on the LiteLLM response, but `stream=True` returns a
`CustomStreamWrapper` (an async iterable), not a response object with
`model_dump`. Streaming through the production adapter would either crash
or return garbage. Integration tests had been mocking `client.acompletion`
directly so the real adapter path was untested.

These tests pin the contract: stream=True returns the raw wrapper for the
caller to iterate; stream=False returns a dict with `_orca_meta` injected.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class _FakeChunkAsyncIter:
    """Stand-in for litellm's CustomStreamWrapper — async iterable of chunks."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


@pytest.fixture
def fake_router_with_stream(monkeypatch):
    """Build an OrcaLiteLLMClient whose Router is mocked to return a stream
    wrapper for stream=True and a ModelResponse-like object for stream=False.
    """
    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import ProviderDeployment

    deployments = [
        ProviderDeployment(
            model_name="gpt-4o-mini",
            litellm_model="openai/gpt-4o-mini",
            api_key="sk-test",
            provider="openai",
        )
    ]

    # Patch the Router class so __init__ doesn't try to talk to upstream.
    fake_router = MagicMock()

    class _ResponseModel:
        def __init__(self, model: str):
            self.model = model

        def model_dump(self):
            return {"model": self.model, "choices": [], "usage": {}}

    async def _acompletion(**kwargs):
        if kwargs.get("stream"):
            return _FakeChunkAsyncIter([
                {"id": "x", "model": "gpt-4o-mini",
                 "choices": [{"delta": {"content": "hi"}}]},
                {"id": "x", "model": "gpt-4o-mini",
                 "choices": [{"delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
            ])
        return _ResponseModel("gpt-4o-mini")

    fake_router.acompletion = AsyncMock(side_effect=_acompletion)
    # The adapter imports Router inside __init__, so patch the source
    # symbol on the litellm package before construction.
    import litellm
    monkeypatch.setattr(litellm, "Router", lambda **_: fake_router)

    client = OrcaLiteLLMClient(deployments=deployments, strategy="balanced")
    return client


async def test_acompletion_stream_returns_async_iterable_not_dict(fake_router_with_stream):
    """Production bug from round-5 review: passing stream=True must not
    eagerly coerce the wrapper to a dict. The caller (chat.py SSE path)
    needs to `async for` over it."""
    result = await fake_router_with_stream.acompletion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )
    # Result must be async-iterable.
    assert hasattr(result, "__aiter__"), (
        f"stream=True must return an async iterable, got {type(result).__name__}"
    )
    # Drain it.
    chunks = []
    async for c in result:
        chunks.append(c)
    assert len(chunks) == 2


async def test_acompletion_non_stream_returns_dict_with_orca_meta(fake_router_with_stream):
    """Non-stream path must keep returning a dict with the _orca_meta
    injection — that's the contract the existing chat.py blocking path
    and request_log writer rely on."""
    result = await fake_router_with_stream.acompletion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert isinstance(result, dict)
    assert result.get("model") == "gpt-4o-mini"
    assert "_orca_meta" in result
    assert result["_orca_meta"].get("provider") == "openai"


async def test_acompletion_propagates_litellm_hidden_params_into_orca_meta(monkeypatch):
    """LiteLLM stashes per-call cost on `_hidden_params.response_cost` and
    the actual provider on `_hidden_params.custom_llm_provider`. The
    adapter MUST extract these BEFORE `model_dump()` strips them, then
    surface them on _orca_meta. Otherwise downstream cost tracking falls
    back to the (much less accurate) catalog calculation for every request.
    """
    from unittest.mock import AsyncMock, MagicMock

    import litellm

    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import ProviderDeployment

    class _ResponseModel:
        def __init__(self):
            self.model = "claude-3-5-sonnet-20241022"
            # LiteLLM populates this in `_response_cost_calculator` —
            # value is USD (float).
            self._hidden_params = {
                "response_cost": 0.000_750,
                "custom_llm_provider": "anthropic",
                "litellm_call_id": "test-id",
            }

        def model_dump(self):
            # Pydantic strips _-prefixed attrs by default. This mirrors
            # what real LiteLLM ModelResponse.model_dump() does.
            return {
                "model": self.model,
                "choices": [],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }

    fake_router = MagicMock()

    async def _acompletion(**kwargs):
        return _ResponseModel()

    fake_router.acompletion = AsyncMock(side_effect=_acompletion)
    monkeypatch.setattr(litellm, "Router", lambda **_: fake_router)

    client = OrcaLiteLLMClient(
        deployments=[
            ProviderDeployment(
                model_name="claude-3-5-sonnet-20241022",
                litellm_model="anthropic/claude-3-5-sonnet-20241022",
                api_key="sk-test", provider="anthropic",
            )
        ],
        strategy="balanced",
    )
    result = await client.acompletion(
        model="claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": "hi"}],
    )
    meta = result.get("_orca_meta") or {}
    assert meta.get("cost_usd") == 0.000_750, (
        "_hidden_params.response_cost must survive into _orca_meta — "
        "downstream cost calculation reads it from there"
    )
    assert meta.get("provider") == "anthropic", (
        "_hidden_params.custom_llm_provider should win over the "
        "deployment-loop fallback (more reliable on aliased model names)"
    )


async def test_acompletion_orca_meta_cost_none_when_litellm_omits_it(monkeypatch):
    """When the response object has no `_hidden_params` (very old LiteLLM,
    custom upstream wrappers), `cost_usd` must be None on the meta — that's
    the signal for downstream code to fall back to catalog pricing."""
    from unittest.mock import AsyncMock, MagicMock

    import litellm

    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import ProviderDeployment

    class _BareResponse:
        model = "gpt-4o-mini"
        # Deliberately no _hidden_params.

        def model_dump(self):
            return {"model": self.model, "choices": [], "usage": {}}

    fake_router = MagicMock()
    fake_router.acompletion = AsyncMock(side_effect=lambda **_: _BareResponse())
    monkeypatch.setattr(litellm, "Router", lambda **_: fake_router)

    client = OrcaLiteLLMClient(
        deployments=[
            ProviderDeployment(
                model_name="gpt-4o-mini", litellm_model="openai/gpt-4o-mini",
                api_key="sk-test", provider="openai",
            )
        ],
        strategy="balanced",
    )
    result = await client.acompletion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result["_orca_meta"]["cost_usd"] is None
    # Provider attribution falls back to deployment-loop lookup.
    assert result["_orca_meta"]["provider"] == "openai"


async def test_acompletion_stream_raises_no_providers_when_router_is_none():
    """No-key configurations short-circuit before LiteLLM gets called.
    Stream requests must hit the same guard as non-stream ones."""
    from packages.litellm_adapter.client import OrcaLiteLLMClient
    from packages.litellm_adapter.types import UpstreamProviderError

    # Empty deployments → self._router is None.
    client = OrcaLiteLLMClient(deployments=[])
    with pytest.raises(UpstreamProviderError):
        await client.acompletion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
