"""H2 and H3 through the chat engine.

H2: a request that fails upstream (overloaded, rate limited, down) with no
other provider left is logged as no_fallback, against the provider that
failed, so the panel can offer OrcaRouter as a backup. Once OrcaRouter can
serve the same model (it spells some versions with dots), the same request
is rescued through it.

H3: an agent answered by a different model than it asked for is logged as
substituted; the same model under OrcaRouter's spelling is not a
substitution.
"""

from __future__ import annotations

import pytest

from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, hosted, own

ASK = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "ping"}]}


def _overloaded():
    return UpstreamProviderError("Overloaded", http_status=503, error_type="upstream_error")


@pytest.mark.parametrize("stream", [False, True])
async def test_a_failure_with_no_backup_is_noted_against_the_provider(engine, stream):
    engine.router = FakeRouter(own("anthropic", "claude-sonnet-4-6", "claude-haiku-4-5"))
    engine.router.failing["anthropic"] = _overloaded()
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, ASK, stream=stream)
    assert r.status_code == 503
    log = await engine.last_log()
    assert (log.route_note, log.provider, log.model_resolved) == ("no_fallback", "anthropic", "claude-sonnet-4-6")


@pytest.mark.parametrize("error_type", ["rate_limit_error", "upstream_timeout"])
async def test_rate_limits_and_timeouts_count_too(engine, error_type):
    engine.router = FakeRouter(own("anthropic", "claude-sonnet-4-6"))
    engine.router.failing["anthropic"] = UpstreamProviderError("x", http_status=429, error_type=error_type)
    await engine.chat(engine.root_key, ASK)
    assert (await engine.last_log()).route_note == "no_fallback"


async def test_a_bad_key_is_not_something_a_backup_fixes(engine):
    engine.router = FakeRouter(own("anthropic", "claude-sonnet-4-6"))
    engine.router.failing["anthropic"] = UpstreamProviderError("bad key", http_status=503,
                                                               error_type="upstream_auth_error")
    await engine.chat(engine.root_key, ASK)
    assert (await engine.last_log()).route_note is None


@pytest.mark.parametrize("stream", [False, True])
async def test_orcarouter_rescues_the_same_request_under_its_spelling(engine, stream):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*own("anthropic", "claude-sonnet-4-6"), *hosted("claude-sonnet-4.6")])
    engine.router.failing["anthropic"] = _overloaded()
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, ASK, stream=stream)
    assert r.status_code == 200
    call = engine.router.calls[-1]
    assert call["model"] == "claude-sonnet-4-6"
    assert call["fallbacks"] == [{"claude-sonnet-4-6": ["claude-sonnet-4.6"]}]
    log = await engine.last_log()
    assert (log.provider, log.fallback_level, log.route_note) == ("orcarouter", 1, None)


async def test_without_a_failure_the_own_key_serves(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*own("anthropic", "claude-sonnet-4-6"), *hosted("claude-sonnet-4.6")])
    r = await engine.chat(engine.root_key, ASK)
    assert r.status_code == 200
    log = await engine.last_log()
    assert (log.provider, log.fallback_level) == ("anthropic", 0)


async def test_orcarouters_spelling_of_the_asked_model_is_not_a_substitution(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*hosted("claude-sonnet-4.6", "claude-haiku-4.5"), *own("openai", "gpt-4.1")])
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, ASK)
    assert r.status_code == 200
    assert engine.router.calls[-1]["model"] == "claude-sonnet-4.6"
    assert r.headers["x-orca-requested-model"] == "claude-sonnet-4-6"
    assert (await engine.last_log()).route_note is None


@pytest.mark.parametrize("stream", [False, True])
async def test_an_agent_answered_by_another_model_is_substituted(engine, stream):
    engine.router = FakeRouter(own("openai", "gpt-4.1", "gpt-4o-mini"))
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, ASK, stream=stream)
    assert r.status_code == 200
    log = await engine.last_log()
    assert (log.route_note, log.model_requested) == ("substituted", "claude-sonnet-4-6")
    assert log.model_resolved in {"gpt-4.1", "gpt-4o-mini"}
