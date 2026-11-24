"""P1: own keys for Moonshot (Kimi), Qwen (DashScope), MiniMax, Z.ai (GLM)
and OpenRouter.

Each provider needs four things to work end to end: catalog entries under
its LiteLLM prefix (so a key deploys its models), an env key name, a key
check and a key-shape hint. The newer providers resell models the original
ones already list, so they must never take a model id away from its
original vendor.
"""

from __future__ import annotations

import httpx
import pytest

from packages.desktop import provider_check as pc
from packages.litellm_adapter.catalog import CATALOG_BY_ID, models_for_provider

NEW = {
    "moonshot": ("moonshot/", "kimi-k2.6"),
    "qwen": ("dashscope/", "qwen-plus"),
    "minimax": ("minimax/", "MiniMax-M2.5"),
    "zai": ("zai/", "glm-4.6"),
    "openrouter": ("openrouter/", "deepseek/deepseek-v4-pro"),
}


@pytest.mark.parametrize("provider", sorted(NEW))
def test_each_new_provider_deploys_its_models_under_its_prefix(provider):
    prefix, model = NEW[provider]
    models = {m.id: m for m in models_for_provider(provider)}
    assert model in models, sorted(models)[:20]
    assert models[model].litellm_prefix == prefix
    assert models[model].provider == provider


def test_resellers_never_take_a_model_away_from_its_vendor():
    # DashScope and OpenRouter also list DeepSeek's models.
    assert CATALOG_BY_ID["deepseek-v4-flash"].provider == "deepseek"
    assert "deepseek-v4-flash" in {m.id for m in models_for_provider("deepseek")}
    # ...but a DashScope key still deploys them.
    assert "deepseek-v4-flash" in {m.id for m in models_for_provider("qwen")}


def test_hosted_prices_survive_an_unpriced_litellm_entry():
    # litellm lists dashscope/qwen3-max without a price; the hosted catalog
    # knows it, and auto needs a price to rank it.
    assert CATALOG_BY_ID["qwen3-max"].input_cost_per_token > 0


def test_env_key_names(monkeypatch, isolated_env):
    from app.config import Settings

    for name, value in {
        "MOONSHOT_API_KEY": "sk-moon", "DASHSCOPE_API_KEY": "sk-dash", "MINIMAX_API_KEY": "mm",
        "ZAI_API_KEY": "z.ai", "OPENROUTER_API_KEY": "sk-or-v1-x",
    }.items():
        monkeypatch.setenv(name, value)
    keys = Settings(_env_file=None).env_provider_keys()
    assert {k: keys[k] for k in NEW} == {
        "moonshot": "sk-moon", "qwen": "sk-dash", "minimax": "mm", "zai": "z.ai", "openrouter": "sk-or-v1-x",
    }


def test_a_moonshot_key_deploys_kimi():
    from app.config import Settings
    from app.router_cache import build_deployments

    deps = build_deployments(env_keys={"moonshot": "sk-moon"}, db_keys=[], settings=Settings(_env_file=None))
    kimi = next(d for d in deps if d.model_name == "kimi-k2.6")
    assert (kimi.provider, kimi.litellm_model, kimi.api_key) == ("moonshot", "moonshot/kimi-k2.6", "sk-moon")


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("provider,host", [
    ("moonshot", "api.moonshot.ai"),
    ("qwen", "dashscope-intl.aliyuncs.com"),
    ("zai", "api.z.ai"),
    ("openrouter", "openrouter.ai"),
])
async def test_new_providers_check_keys(provider, host):
    seen = []

    def handler(req):
        seen.append((req.url.host, req.headers.get("authorization")))
        return httpx.Response(401, json={})

    async with _client(handler) as c:
        r = await pc.check_key(provider, "k", client=c, env={})
    assert r["status"] == "invalid"
    assert seen == [(host, "Bearer k")]


async def test_openrouter_checks_the_key_not_the_public_model_list():
    # OpenRouter's model list is public, so it would accept any key.
    seen = []
    async with _client(lambda req: seen.append(req.url.path) or httpx.Response(200, json={})) as c:
        await pc.check_key("openrouter", "k", client=c, env={})
    assert seen == ["/api/v1/key"]


async def test_new_provider_base_urls_can_be_overridden():
    seen = []
    async with _client(lambda req: seen.append(str(req.url)) or httpx.Response(200, json={})) as c:
        await pc.check_key("moonshot", "k", client=c, env={"MOONSHOT_API_BASE": "http://127.0.0.1:9/moonshot/v1"})
    assert seen == ["http://127.0.0.1:9/moonshot/v1/models"]


async def test_minimax_is_saved_unchecked():
    async with _client(lambda req: httpx.Response(500)) as c:
        r = await pc.check_key("minimax", "k", client=c, env={})
    assert r["status"] == "unchecked"


@pytest.mark.parametrize("provider,good,bad", [
    ("moonshot", "sk-abc123456789", "AIzaXXXXXXXXXX"),
    ("qwen", "sk-abc123456789", "gsk_XXXXXXXXXXX"),
    ("openrouter", "sk-or-v1-abcdef", "sk-ant-XXXXXXXX"),
])
def test_key_shape_hints(provider, good, bad):
    from app.routes.providers import provider_key_format_warning

    assert provider_key_format_warning(provider, good) is None
    assert provider_key_format_warning(provider, bad) is not None


def test_agent_fallback_prefers_moonshot_for_kimi_and_zai_for_glm():
    from app.agent_model_fallback import fallback_preferences
    from packages.litellm_adapter.catalog import CATALOG

    deployable = {"gpt-4o-mini", "kimi-k2.5", "kimi-k2.6", "glm-4.6", "glm-4.5-air"}
    kimi = fallback_preferences("kimi-for-coding", deployable, catalog=CATALOG, is_agent_key=True, desktop_mode=True)
    assert kimi and set(kimi) <= {"kimi-k2.5", "kimi-k2.6"}
    glm = fallback_preferences("glm-9", deployable, catalog=CATALOG, is_agent_key=True, desktop_mode=True)
    assert glm and set(glm) <= {"glm-4.6", "glm-4.5-air"}
