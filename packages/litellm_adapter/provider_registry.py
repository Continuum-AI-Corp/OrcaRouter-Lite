"""The one list of providers a user can add a key for.

Setup, the dashboard and the panel each used to keep their own list, and
they drifted (setup offered nine providers, the dashboard eight). They now
read this one, through `GET /v1/providers/supported`, in display order:
OrcaRouter's hosted gateway first, then each vendor.

`checkable` says whether `packages.desktop.provider_check` can ask the
provider about a key before it's saved; `new` marks the providers added
with own keys in P1 so the UI can highlight them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    name: str
    key_hint: str          # the key's usual shape, for placeholders; "" when it has none
    env_var: str           # the environment variable the engine reads it from
    docs_url: str          # where the user creates a key
    new: bool = False
    hosted: bool = False


HOSTED_ID = "orcarouter"

PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo("orcarouter", "OrcaRouter", "sk-orca-…", "ORCAROUTER_API_KEY",
                 "https://www.orcarouter.ai/console/token", hosted=True),
    ProviderInfo("anthropic", "Anthropic", "sk-ant-…", "ANTHROPIC_API_KEY",
                 "https://console.anthropic.com/settings/keys"),
    ProviderInfo("openai", "OpenAI", "sk-…", "OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
    ProviderInfo("google", "Google Gemini", "AIza…", "GOOGLE_API_KEY", "https://aistudio.google.com/apikey"),
    ProviderInfo("deepseek", "DeepSeek", "sk-…", "DEEPSEEK_API_KEY", "https://platform.deepseek.com/api_keys"),
    ProviderInfo("xai", "xAI Grok", "xai-…", "XAI_API_KEY", "https://console.x.ai"),
    ProviderInfo("mistral", "Mistral", "", "MISTRAL_API_KEY", "https://console.mistral.ai/api-keys"),
    ProviderInfo("groq", "Groq", "gsk_…", "GROQ_API_KEY", "https://console.groq.com/keys"),
    ProviderInfo("together", "Together", "", "TOGETHER_API_KEY", "https://api.together.ai/settings/api-keys"),
    ProviderInfo("fireworks", "Fireworks", "fw_…", "FIREWORKS_API_KEY", "https://fireworks.ai/account/api-keys"),
    ProviderInfo("cohere", "Cohere", "", "COHERE_API_KEY", "https://dashboard.cohere.com/api-keys"),
    ProviderInfo("moonshot", "Moonshot (Kimi)", "sk-…", "MOONSHOT_API_KEY",
                 "https://platform.moonshot.ai/console/api-keys", new=True),
    ProviderInfo("qwen", "Qwen (DashScope)", "sk-…", "DASHSCOPE_API_KEY",
                 "https://www.alibabacloud.com/help/en/model-studio/get-api-key", new=True),
    ProviderInfo("minimax", "MiniMax", "", "MINIMAX_API_KEY",
                 "https://www.minimax.io/platform/user-center/basic-information/interface-key", new=True),
    ProviderInfo("zai", "Z.ai (GLM)", "", "ZAI_API_KEY", "https://z.ai/manage-apikey/apikey-list", new=True),
    ProviderInfo("openrouter", "OpenRouter", "sk-or-…", "OPENROUTER_API_KEY",
                 "https://openrouter.ai/settings/keys", new=True),
)

BY_ID: dict[str, ProviderInfo] = {p.id: p for p in PROVIDERS}


def supported_providers(*, checkable: set[str], token_url: str | None = None) -> list[dict]:
    """The list as JSON rows. `checkable` is the set of providers with a key
    check; `token_url` overrides OrcaRouter's key page (it's configurable)."""
    rows = []
    for p in PROVIDERS:
        row = asdict(p)
        if p.hosted and token_url:
            row["docs_url"] = token_url
        if not p.hosted:
            del row["hosted"]
        row["checkable"] = p.id in checkable
        rows.append(row)
    return rows


def display_name(provider: str) -> str:
    info = BY_ID.get(provider)
    return info.name if info else provider
