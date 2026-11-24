"""H4: recognising OrcaRouter's payment-required answer, and reading the
exact cost it reports per request."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.desktop import hosted_state


@pytest.fixture(autouse=True)
def _fresh():
    hosted_state.reset()
    yield
    hosted_state.reset()


def test_out_of_credit_lasts_ten_minutes():
    hosted_state.mark_out_of_credit(now=1000.0)
    assert hosted_state.out_of_credit(now=1000.0)
    assert hosted_state.out_of_credit(now=1599.0)
    assert not hosted_state.out_of_credit(now=1601.0)


def test_any_answer_from_orcarouter_clears_it():
    hosted_state.mark_out_of_credit()
    assert hosted_state.out_of_credit()
    hosted_state.note_success()
    assert not hosted_state.out_of_credit()


def _api_error(status: int, deployment_id: str):
    import litellm

    exc = litellm.APIError(status_code=status, message="Insufficient credit", llm_provider="openai",
                           model="anthropic/claude-sonnet-4.6")
    exc.failed_deployment_id = deployment_id
    return exc


def test_a_402_from_orcarouter_is_out_of_credit():
    from packages.litellm_adapter.client import _translate_error

    err = _translate_error(_api_error(402, "hosted::anthropic/claude-sonnet-4.6"))
    assert (err.http_status, err.error_type) == (402, "out_of_credit")


def test_a_402_from_an_own_key_is_just_payment_required():
    # DeepSeek answers 402 when its balance runs out: not OrcaRouter's credit.
    from packages.litellm_adapter.client import _translate_error

    err = _translate_error(_api_error(402, "e55d57ef"))
    assert (err.http_status, err.error_type) == (402, "payment_required")


async def test_the_hosted_cost_header_prices_a_request(monkeypatch):
    from packages.litellm_adapter import client as client_mod
    from packages.litellm_adapter.types import ProviderDeployment

    dep = ProviderDeployment(model_name="claude-sonnet-4.6", litellm_model="anthropic/claude-sonnet-4.6",
                             api_key="sk-orca", api_base="http://orca.test/v1", provider="orcarouter",
                             custom_llm_provider="openai", deployment_id="hosted::anthropic/claude-sonnet-4.6")
    fake_router = MagicMock()

    class _Resp:
        _hidden_params = {"model_id": "hosted::anthropic/claude-sonnet-4.6", "api_base": "http://orca.test/v1",
                          "response_cost": 0.0,
                          "additional_headers": {"llm_provider-x-orcarouter-beta-usd": "0.0123"}}

        def model_dump(self):
            return {"model": "anthropic/claude-sonnet-4.6", "choices": [], "usage": {}}

    fake_router.acompletion = AsyncMock(return_value=_Resp())
    monkeypatch.setattr("litellm.Router", lambda **kw: fake_router)
    c = client_mod.OrcaLiteLLMClient([dep])
    out = await c.acompletion(model="claude-sonnet-4.6", messages=[])
    assert out["_orca_meta"]["cost_usd"] == pytest.approx(0.0123)
    assert out["_orca_meta"]["provider"] == "orcarouter"
    assert out["_orca_meta"]["model_group"] == "claude-sonnet-4.6"
