"""Settings — env-driven configuration for orcarouter-lite.

Single-workspace edition: ~15 fields versus ~40 in the SaaS settings.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROVIDERS_FROM_ENV = (
    "openai",
    "anthropic",
    "google",
    "groq",
    "together",
    "fireworks",
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
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    groq_api_key: str | None = None
    together_api_key: str | None = None
    fireworks_api_key: str | None = None

    # ── Hosted-as-upstream (standard fallback) ──
    # When configured (env or via dashboard), every catalog model gets an extra
    # deployment routed through hosted — so requests for a model the user has
    # no local key for still succeed. Free trial credit available via the
    # signup URL surfaced in the Lite dashboard's "Hosted fallback" card.
    orcarouter_api_key: str | None = None
    orcarouter_base_url: str = "https://api.orcarouter.ai/v1"
    orcarouter_signup_url: str = "https://www.orcarouter.ai/register"
    # Source of truth for the "Models you can't reach" tile's curated
    # top list. Fetched lazily, cached in-process for ~1h, with a static
    # fallback if the remote is unreachable.
    orcarouter_models_url: str = "https://www.orcarouter.ai/models"

    # ── Body limit (for image / file attachments) ──
    max_body_bytes: int = 100 * 1024 * 1024

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
