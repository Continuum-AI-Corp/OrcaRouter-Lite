"""Settings — env-driven configuration for orcarouter-lite.

Single-workspace edition: ~15 fields versus ~40 in the SaaS settings.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Providers we accept from env vars. Must stay in sync with:
#   - the matching `<provider>_api_key` fields on Settings below
#   - `PROVIDERS_KNOWN` in design/app.js (dashboard quick-add chips)
#   - `_PROVIDER_BY_LITELLM_KEY` in packages/litellm_adapter/catalog.py
#     (which decides the runtime provider id for catalog entries)
#
# xAI / DeepSeek were missing here pre-2026-05, leaving their catalog
# models silently un-routable: the catalog had grok-4 + deepseek-v3 etc,
# but Settings didn't read XAI_API_KEY / DEEPSEEK_API_KEY, and the
# dashboard had no chip for them. Operators couldn't configure without
# raw curl PUT (or hit the wrong provider — famously: "grok" PUT'd into
# "groq", which is a different company).
_PROVIDERS_FROM_ENV = (
    "openai",
    "anthropic",
    "google",
    "groq",
    "together",
    "fireworks",
    "xai",          # Grok 2/3/4 series. NOTE: NOT the same as `groq`.
    "deepseek",     # deepseek-chat / -reasoner / -v3 / -v3.2.
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./orca.db"

    # ── Redis (optional) ──────────────────────────────
    redis_url: str | None = None

    # ── Server ────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # ── Encryption (auto-generated on first run if empty) ──
    credential_encryption_key: str = ""
    api_key_pepper: str = ""

    # ── Provider keys via env (alternative to UI-stored keys) ──
    # Keep in sync with `_PROVIDERS_FROM_ENV` above. Pydantic-settings reads
    # case-insensitively (config: `case_sensitive=False`), so XAI_API_KEY,
    # xai_api_key, etc all hit the same field.
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    groq_api_key: str | None = None
    together_api_key: str | None = None
    fireworks_api_key: str | None = None
    xai_api_key: str | None = None
    deepseek_api_key: str | None = None

    # ── Hosted-as-upstream (standard fallback) ──
    # When configured (env or via dashboard), every catalog model gets an extra
    # deployment routed through hosted — so requests for a model the user has
    # no local key for still succeed. Free trial credit available via the
    # signup URL surfaced in the Lite dashboard's "Hosted fallback" card.
    orcarouter_api_key: str | None = None
    orcarouter_base_url: str = "https://api.orcarouter.ai/v1"
    orcarouter_signup_url: str = "https://www.orcarouter.ai/register"
    # Where an account holder actually copies their sk-orca-* key — the
    # target of the dashboard's "Get your key" button. /register above is
    # only for users without an account yet (the token console bounces
    # them through sign-up/login on its own).
    orcarouter_token_url: str = "https://www.orcarouter.ai/console/token"
    # Source of truth for the "Models you can't reach" tile's curated
    # top list. Fetched lazily, cached in-process for ~1h, with a static
    # fallback if the remote is unreachable.
    orcarouter_models_url: str = "https://www.orcarouter.ai/models"


    # ── Quality scoring (Artificial Analysis) ──
    # API key from https://artificialanalysis.ai (free tier: 1000 req/day).
    # When set, model="auto" with strategy="quality" picks the model with
    # the highest Intelligence Index from AA's benchmark aggregator instead
    # of the most expensive (the legacy proxy that broke when Anthropic /
    # OpenAI started pricing newer flagships LOWER than older ones).
    # Empty string disables AA scoring; quality strategy degrades to the
    # cost-based fallback. Attribution to AA is displayed in the dashboard
    # whenever scores are in use, per their free-tier terms.
    artificial_analysis_api_key: str = ""
    artificial_analysis_models_url: str = (
        "https://artificialanalysis.ai/api/v2/data/llms/models"
    )

    # ── Router behavior (LiteLLM Router cooldown + cascade) ──
    # How long a deployment stays cooled-down after a failure. LiteLLM's
    # own default is 1 second (effectively no cooldown — a dead model
    # gets re-picked on the very next request).
    #
    # Our default is 60s — a developer-friendly middle ground:
    #   - long enough that a genuinely dead model isn't hammered every
    #     request while you debug
    #   - short enough that fixing your API key + waiting a minute beats
    #     restarting the process to clear in-memory cooldowns
    # Production deployments under sustained traffic should set this to
    # 600-3600 in `.env` to avoid burning quota on a known-dead model.
    # Tests should set 0 to disable cooldown entirely.
    router_cooldown_seconds: int = 60
    # Global default for failures-before-cooldown across all error types,
    # used by LiteLLM Router as the fallback when AllowedFailsPolicy returns
    # a falsy value. We set 0 so the policy's "fail fast on hard errors"
    # values (also 0) actually take effect — LiteLLM's internal
    # `allowed_fails = policy_value or router.allowed_fails` short-circuits
    # any 0 in the policy back to this default. Per-error-type leniency for
    # transients (429 / 5xx / timeouts) still applies via non-zero policy
    # values, set in client.py:_build_allowed_fails_policy().
    router_allowed_fails: int = 0
    # When True, LiteLLM filters deployments whose context window can't fit
    # the request before dispatching. Cheap pre-flight that prevents wasted
    # round-trips on prompts that would 422 anyway.
    router_pre_call_checks: bool = True
    # In-deployment retry count. The default applies to explicitly-pinned
    # model requests (where the user said "use this exact model, retry it").
    # The auto value is used when the request was model="auto" so cascade
    # to the next fallback candidate happens immediately instead of after
    # 2x in-deployment retries (which would add ~30-90s of perceived latency).
    router_num_retries_default: int = 2
    router_num_retries_auto: int = 0

    def env_provider_keys(self) -> dict[str, str]:
        """Return the configured ENV-sourced provider keys as {provider: key}."""
        out: dict[str, str] = {}
        for prov in _PROVIDERS_FROM_ENV:
            val = getattr(self, f"{prov}_api_key", None)
            if val:
                out[prov] = val
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
