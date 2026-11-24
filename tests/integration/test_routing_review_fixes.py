"""Fixes from the routing review: desktop-only routing stays out of server
mode, and OrcaRouter's out-of-credit state behaves at its edges."""

from __future__ import annotations

import pytest

from app import config
from packages.desktop import hosted_state
from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, hosted, own

PING = {"model": "auto", "messages": [{"role": "user", "content": "ping"}]}


@pytest.fixture
def server_mode(monkeypatch):
    """The same engine, but started as a server (not the desktop app)."""
    monkeypatch.setenv("ORCA_DESKTOP_MODE", "0")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def _chain(call: dict) -> list[str]:
    return [call["model"], *((call["fallbacks"] or [{}])[0].get(call["model"], []))]


async def test_server_mode_keeps_a_pinned_model_as_asked(engine, server_mode):
    # Only OrcaRouter's dotted spelling is deployed: a server must not
    # silently rewrite the operator's pinned name to it.
    engine.router = FakeRouter([*hosted("claude-sonnet-4.6"), *own("openai", "gpt-4o-mini")])
    await engine.chat(engine.root_key, {**PING, "model": "claude-sonnet-4-6"})
    assert engine.router.calls[-1]["model"] == "claude-sonnet-4-6"


async def test_server_mode_adds_no_paid_orcarouter_backup_to_a_pinned_model(engine, server_mode):
    engine.router = FakeRouter([*own("anthropic", "claude-sonnet-4-6"), *hosted("claude-sonnet-4.6")])
    await engine.chat(engine.root_key, {**PING, "model": "claude-sonnet-4-6"})
    assert _chain(engine.router.calls[-1]) == ["claude-sonnet-4-6"]


async def test_server_mode_auto_never_picks_zero_priced_free_models(engine, server_mode):
    engine.router = FakeRouter([
        *hosted("deepseek/deepseek-v4-pro-free", "orcarouter/free"), *own("openai", "gpt-4o-mini"),
    ])
    await engine.chat(engine.root_key, PING)
    tried = _chain(engine.router.calls[-1])
    assert "deepseek/deepseek-v4-pro-free" not in tried and "orcarouter/free" not in tried


async def test_a_free_model_answer_does_not_clear_out_of_credit(engine):
    # Free models answer even with no credit, so they prove nothing about
    # paid requests; only a paid answer from OrcaRouter clears the state.
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*hosted("orcarouter/free", "gpt-5")])
    hosted_state.mark_out_of_credit()
    r = await engine.chat(engine.root_key, {**PING, "model": "orcarouter/free"})
    assert r.status_code == 200
    assert hosted_state.out_of_credit()
    await engine.chat(engine.root_key, {**PING, "model": "gpt-5"})
    assert not hosted_state.out_of_credit()


async def test_out_of_credit_agent_falls_back_to_own_keys_not_orcarouter(engine):
    # Claude Code asks for claude-sonnet-4-6; only OrcaRouter serves it (as
    # claude-sonnet-4.6) and it is out of credit, while an own OpenAI key
    # works: the agent is answered by the own key instead of a 402.
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*hosted("claude-sonnet-4.6"), *own("openai", "gpt-4o-mini")])
    engine.router.failing["orcarouter"] = UpstreamProviderError(
        "Insufficient credit", http_status=402, error_type="out_of_credit")
    hosted_state.mark_out_of_credit()
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, {**PING, "model": "claude-sonnet-4-6"})
    assert r.status_code == 200
    assert set(_chain(engine.router.calls[-1])) <= {"gpt-4o-mini"}
