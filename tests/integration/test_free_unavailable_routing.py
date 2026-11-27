"""Through the chat engine: an account OrcaRouter won't give free models to
gets OrcaRouter's reason and how to keep going (a 403 no agent retries),
never "out of credit"; once noted, auto stops trying the free models first."""

from __future__ import annotations

from packages.desktop import hosted_state
from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, hosted, own

PING = {"model": "auto", "messages": [{"role": "user", "content": "ping"}]}
FREE = ("z-ai/glm-5.3-flash-free", "deepseek/deepseek-v4-flash-free", "orcarouter/free")
REASON = "Free models are not available to this account yet. Link an established GitHub account."


def _refused():
    return UpstreamProviderError(REASON, http_status=403, error_type="free_unavailable")


async def test_free_mode_with_free_models_refused_says_why_and_how_to_continue(engine):
    engine.router = FakeRouter([*hosted(*FREE)])
    engine.router.failing["orcarouter"] = _refused()
    r = await engine.chat(engine.root_key, PING)
    assert r.status_code == 403, r.text
    assert r.headers["x-orca-error-type"] == "free_unavailable"
    message = r.json()["error"]["message"]
    assert REASON in message and "Paid models on OrcaRouter" in message
    assert hosted_state.free_unavailable()
    assert not hosted_state.out_of_credit()


async def test_claude_code_gets_a_permission_error_it_will_not_retry(engine):
    engine.router = FakeRouter([*hosted(*FREE)])
    engine.router.failing["orcarouter"] = _refused()
    key = await engine.agent_key("claude-code")
    async with engine.client(key) as c:
        r = await c.post("/v1/messages", json={"model": "auto", "max_tokens": 10, "messages": PING["messages"]},
                         headers={"anthropic-version": "2023-06-01"})
    assert r.status_code == 403, r.text
    assert r.json()["error"]["type"] == "permission_error"


async def test_once_refused_auto_skips_the_free_models(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*hosted(*FREE, "claude-sonnet-4.6"), *own("openai", "gpt-4o-mini")])
    hosted_state.mark_free_unavailable(REASON)
    r = await engine.chat(engine.root_key, PING)
    assert r.status_code == 200, r.text
    call = engine.router.calls[-1]
    tried = [call["model"], *((call["fallbacks"] or [{}])[0].get(call["model"], []))]
    assert not set(tried) & {*FREE, *(m.split("/", 1)[1] for m in FREE)}, tried
