"""Tests for app.config.Settings."""



def test_settings_load_with_defaults(isolated_env):
    """Settings loads with sane defaults when no env vars are set."""
    from app.config import Settings

    s = Settings(_env_file=None)

    assert s.database_url == "sqlite+aiosqlite:///./orca.db"
    assert s.redis_url is None
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.orcarouter_base_url == "https://api.orcarouter.ai/v1"
    assert s.orcarouter_token_url == "https://www.orcarouter.ai/console/token"
    assert s.orcarouter_api_key is None
    assert s.openai_api_key is None


def test_settings_reads_env_provider_keys(isolated_env, monkeypatch):
    """Provider keys come in via env."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-hosted")
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.openai_api_key == "sk-test-openai"
    assert s.anthropic_api_key == "sk-ant-test"
    assert s.orcarouter_api_key == "sk-orca-hosted"


def test_settings_env_provider_keys_returns_dict(isolated_env, monkeypatch):
    """`.env_provider_keys` exposes only the configured providers as a dict."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-1")
    monkeypatch.setenv("GROQ_API_KEY", "sk-2")
    from app.config import Settings

    s = Settings(_env_file=None)
    keys = s.env_provider_keys()
    assert keys == {"openai": "sk-1", "groq": "sk-2"}


def test_settings_reads_extended_provider_keys(isolated_env, monkeypatch):
    """xAI / DeepSeek were missing from Settings before, leaving their
    catalog models unroutable. Regression test: each var must wire to
    the matching field AND surface via env_provider_keys() with the
    catalog provider id (NOT the env var name — `xai` not `XAI`).

    The xAI test in particular doubles as a guard against the famous
    'grok vs groq' typo: `XAI_API_KEY` must produce provider id `xai`,
    so the runtime can't route grok-* models to a Groq endpoint."""
    monkeypatch.setenv("XAI_API_KEY", "xai-test-grok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.xai_api_key == "xai-test-grok"
    assert s.deepseek_api_key == "sk-ds-test"

    keys = s.env_provider_keys()
    assert keys == {
        "xai": "xai-test-grok",
        "deepseek": "sk-ds-test",
    }
    assert "xai" in keys, "XAI_API_KEY must surface as 'xai' not 'XAI' or 'grok'"
    assert "groq" not in keys, "XAI_API_KEY must NOT alias to groq (different company)"


def test_settings_xai_and_groq_are_separate_providers(isolated_env, monkeypatch):
    """Belt-and-suspenders for the grok/groq footgun: setting both env
    vars must populate two distinct provider entries in env_provider_keys.
    A previous bug surfaced as operators PUTting xai keys into the groq
    provider via the dashboard (groq was the only chip available)."""
    monkeypatch.setenv("XAI_API_KEY", "xai-grok-key")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_groq-key")
    from app.config import Settings

    s = Settings(_env_file=None)
    keys = s.env_provider_keys()
    assert keys == {"xai": "xai-grok-key", "groq": "gsk_groq-key"}
    assert s.xai_api_key != s.groq_api_key


def test_settings_database_url_override(isolated_env, monkeypatch):
    """DATABASE_URL env var overrides the SQLite default."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@h/db"


def test_settings_redis_optional(isolated_env, monkeypatch):
    """REDIS_URL is opt-in."""
    from app.config import Settings

    s1 = Settings(_env_file=None)
    assert s1.redis_url is None

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    s2 = Settings(_env_file=None)
    assert s2.redis_url == "redis://localhost:6379/0"
