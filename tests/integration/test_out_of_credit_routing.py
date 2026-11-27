"""H4 through the chat engine: OrcaRouter answering payment-required marks
it out of credit (route_note out_of_credit, a message naming the billing
page), auto then keeps to own keys, and the next answer from OrcaRouter
clears it. Its reported cost prices hosted requests."""

from __future__ import annotations

import pytest

from packages.desktop import hosted_state
from packages.litellm_adapter.types import UpstreamProviderError
from tests.integration.routing_harness import FakeRouter, hosted, own

PING = {"model": "auto", "messages": [{"role": "user", "content": "ping"}]}
DETAIL = ("OrcaRouter is out of credit. Add credit at https://www.orcarouter.ai/console/topup, "
          "or add your own provider key in Orca.")


def _no_credit():
    return UpstreamProviderError("Insufficient credit", http_status=402, error_type="out_of_credit")


@pytest.mark.parametrize("stream", [False, True])
async def test_payment_required_marks_orcarouter_out_of_credit(engine, stream):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*hosted("claude-sonnet-4.6"), *own("openai", "gpt-4o-mini")])
    engine.router.failing["orcarouter"] = _no_credit()
    r = await engine.chat(engine.root_key, {**PING, "model": "claude-sonnet-4.6"}, stream=stream)
    assert r.status_code == 402
    assert r.headers["x-orca-error-type"] == "out_of_credit"
    assert r.json()["error"]["message"] == DETAIL
    assert hosted_state.out_of_credit()
    log = await engine.last_log()
    assert (log.route_note, log.status_code, log.provider) == ("out_of_credit", 402, "orcarouter")


async def test_own_keys_keep_serving_auto_while_out_of_credit(engine):
    engine.router = FakeRouter([
        *hosted("z-ai/glm-5.3-flash-free", "orcarouter/free"), *own("openai", "gpt-4o-mini", "gpt-4.1"),
    ])
    hosted_state.mark_out_of_credit()
    r = await engine.chat(engine.root_key, PING)
    assert r.status_code == 200
    call = engine.router.calls[-1]
    tried = [call["model"], *((call["fallbacks"] or [{}])[0].get(call["model"], []))]
    assert set(tried) <= {"gpt-4o-mini", "gpt-4.1"}


async def test_own_keys_come_before_orcarouter_for_the_same_model(engine):
    # LiteLLM picks at random among deployments of one model; the engine
    # weights an own key's deployment over OrcaRouter's so OrcaRouter is
    # only the backup (and while it's out of credit, never the first try).
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*own("openai", "gpt-5", "gpt-4o-mini"), *hosted("gpt-5")])
    await engine.chat(engine.root_key, {**PING, "model": "gpt-5"})
    assert engine.router.calls[-1]["_router_weights"] == {"gpt-5": {"openai::gpt-5": 1.0, "hosted::gpt-5": 0.0}}
    await engine.chat(engine.root_key, {**PING, "model": "gpt-4o-mini"})
    assert "_router_weights" not in engine.router.calls[-1]  # nothing to weigh


def test_own_key_deployments_have_stable_ids():
    from app.config import Settings
    from app.router_cache import build_deployments

    deps = build_deployments(env_keys={"openai": "sk-o"}, db_keys=[], settings=Settings(_env_file=None))
    assert {d.deployment_id for d in deps if d.model_name == "gpt-4o-mini"} == {"openai::gpt-4o-mini"}


async def test_an_agent_falls_back_to_own_keys_too(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter([*hosted("claude-sonnet-4.6", "claude-haiku-4.5"), *own("openai", "gpt-4o-mini")])
    hosted_state.mark_out_of_credit()
    key = await engine.agent_key("claude-code")
    r = await engine.chat(key, {**PING, "model": "claude-opus-9"})
    assert r.status_code == 200
    assert engine.router.calls[-1]["model"] == "gpt-4o-mini"


async def test_with_nothing_else_orcarouter_is_tried_and_an_answer_clears_it(engine):
    # A paid answer proves credit is back (a free one doesn't: see
    # test_routing_review_fixes).
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter(hosted("gpt-5"))
    hosted_state.mark_out_of_credit()
    r = await engine.chat(engine.root_key, PING)
    assert r.status_code == 200
    assert not hosted_state.out_of_credit()


async def test_streaming_answer_from_orcarouter_clears_it(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter(hosted("gpt-5"))
    hosted_state.mark_out_of_credit()
    r = await engine.chat(engine.root_key, PING, stream=True)
    assert r.status_code == 200
    assert not hosted_state.out_of_credit()


async def test_streamed_hosted_requests_are_priced_by_orcarouters_cost_header(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter(hosted("claude-sonnet-4.6"))
    r = await engine.chat(engine.root_key, {**PING, "model": "claude-sonnet-4.6"}, stream=True)
    assert r.status_code == 200
    assert (await engine.last_log()).cost_microcents == 12_300  # $0.0123


async def test_the_anthropic_surface_reports_a_billing_error(engine):
    await engine.settings(hosted_models="all")
    engine.router = FakeRouter(hosted("claude-sonnet-4.6"))
    engine.router.failing["orcarouter"] = _no_credit()
    key = await engine.agent_key("claude-code")
    async with engine.client(key) as c:
        r = await c.post("/v1/messages", headers={"anthropic-version": "2023-06-01"},
                         json={"model": "claude-sonnet-4.6", "max_tokens": 8,
                               "messages": [{"role": "user", "content": "ping"}]})
    assert r.status_code == 402
    assert r.json()["error"] == {"type": "billing_error", "message": DETAIL}
