"""Issue 19: an agent's pinned model that is deployed but fails upstream (no
capacity, 503) is backed up by the same vendor's closest models, instead of
failing with "no fallback was attempted"."""

from __future__ import annotations

from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, hosted, own

PING = {"messages": [{"role": "user", "content": "ping"}]}
NO_CAPACITY = UpstreamProviderError("No capacity for model claude-sonnet-4-5", http_status=503,
                                    error_type="upstream_error")
DEPS = [*hosted("claude-sonnet-4-5", "claude-sonnet-4.6", "claude-haiku-4.5", "claude-opus-4.7"),
        *own("openai", "gpt-4o-mini")]


async def test_an_agents_model_without_capacity_is_served_by_its_closest_sibling(engine):
    engine.router = FakeRouter(DEPS)
    engine.router.failing["claude-sonnet-4-5"] = NO_CAPACITY
    r = await engine.chat(await engine.agent_key("claude-code"), {**PING, "model": "claude-sonnet-4-5"})
    assert r.status_code == 200, r.text
    call = engine.router.calls[-1]
    assert call["model"] == "claude-sonnet-4-5"
    backups = call["fallbacks"][0]["claude-sonnet-4-5"]
    assert backups[0] == "claude-sonnet-4.6"
    assert "gpt-4o-mini" not in backups  # same vendor only
    assert "num_retries" in call  # cascade like auto instead of retrying the dead model first
    log = await engine.last_log()
    assert (log.model_requested, log.route_note) == ("claude-sonnet-4-5", "substituted")


async def test_the_asked_model_answering_is_not_a_substitution(engine):
    engine.router = FakeRouter(DEPS)
    r = await engine.chat(await engine.agent_key("claude-code"), {**PING, "model": "claude-sonnet-4-5"})
    assert r.status_code == 200
    assert (await engine.last_log()).route_note is None


async def test_a_dashboard_key_keeps_strict_pinned_behaviour(engine):
    engine.router = FakeRouter(DEPS)
    engine.router.failing["claude-sonnet-4-5"] = NO_CAPACITY
    r = await engine.chat(engine.root_key, {**PING, "model": "claude-sonnet-4-5"})
    assert r.status_code == 503
    assert engine.router.calls[-1]["fallbacks"] is None


async def test_backups_must_handle_the_request(engine):
    from packages.litellm_adapter import catalog

    engine.router = FakeRouter(DEPS)
    body = {"model": "claude-sonnet-4-5", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]}
    await engine.chat(await engine.agent_key("claude-code"), body)
    backups = (engine.router.calls[-1]["fallbacks"] or [{}])[0].get("claude-sonnet-4-5", [])
    for m in backups:
        entry = catalog.CATALOG_BY_ID.get(m)
        assert entry is None or entry.supports_vision
