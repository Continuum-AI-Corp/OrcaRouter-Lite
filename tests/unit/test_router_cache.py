"""Router cache: deployment-list assembly + hosted-as-upstream injection.

These tests pin the contract of `build_deployments` without instantiating
litellm.Router (covered by integration tests). Pure-Python is the right
shape for TDD on this layer.
"""

from __future__ import annotations


def test_no_keys_no_deployments():
    """Empty inputs → empty deployment list."""
    from app.config import Settings
    from app.router_cache import build_deployments

    s = Settings(_env_file=None)
    assert build_deployments(env_keys={}, db_keys=[], settings=s) == []


def test_env_openai_key_creates_deployments_per_openai_model():
    """An env-sourced openai key creates one deployment per OpenAI catalog entry."""
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.litellm_adapter.catalog import models_for_provider

    s = Settings(_env_file=None)
    deps = build_deployments(env_keys={"openai": "sk-x"}, db_keys=[], settings=s)

    expected = {m.id for m in models_for_provider("openai")}
    actual = {d.model_name for d in deps if d.provider == "openai"}
    assert actual == expected
    for d in deps:
        assert d.api_key == "sk-x"
        assert d.litellm_model.startswith("openai/")


def test_env_keys_for_multiple_providers_combine():
    from app.config import Settings
    from app.router_cache import build_deployments

    s = Settings(_env_file=None)
    deps = build_deployments(
        env_keys={"openai": "sk-o", "anthropic": "sk-a"},
        db_keys=[],
        settings=s,
    )
    providers = {d.provider for d in deps}
    assert providers == {"openai", "anthropic"}


def test_db_provider_key_takes_precedence_over_env():
    """If both env and DB set a provider key, DB wins (UI-edited keys are authoritative)."""
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.auth.encryption import encrypt_credential
    from packages.db.models.provider_key import ProviderKey

    s = Settings(_env_file=None)
    db_row = ProviderKey(
        provider="openai",
        encrypted_key=encrypt_credential("sk-from-db"),
        key_prefix="sk-from-...",
        label="default",
        is_enabled=True,
    )

    deps = build_deployments(
        env_keys={"openai": "sk-from-env"},
        db_keys=[db_row],
        settings=s,
    )
    openai_deps = [d for d in deps if d.provider == "openai"]
    assert openai_deps  # at least one
    assert all(d.api_key == "sk-from-db" for d in openai_deps)


def test_disabled_db_provider_key_is_skipped():
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.auth.encryption import encrypt_credential
    from packages.db.models.provider_key import ProviderKey

    s = Settings(_env_file=None)
    db_row = ProviderKey(
        provider="openai",
        encrypted_key=encrypt_credential("sk-disabled"),
        key_prefix="sk-...",
        label="default",
        is_enabled=False,
    )
    deps = build_deployments(env_keys={}, db_keys=[db_row], settings=s)
    assert deps == []


def test_orcarouter_api_key_adds_hosted_upstream_per_model(monkeypatch):
    """When ORCAROUTER_API_KEY is set, every catalog model gets an `orcarouter` deployment.

    This is the headline integration: a lite instance with no provider keys but
    ORCAROUTER_API_KEY set still routes everything via the hosted control plane.
    """
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.litellm_adapter.hosted_catalog import (
        HOSTED_MODEL_ALIASES,
        HOSTED_MODELS,
    )

    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-hosted-xyz")
    s = Settings(_env_file=None)

    deps = build_deployments(env_keys={}, db_keys=[], settings=s)
    orca_deps = [d for d in deps if d.provider == "orcarouter"]
    assert len(orca_deps) == len(HOSTED_MODELS) + len(HOSTED_MODEL_ALIASES)
    for d in orca_deps:
        assert d.api_base == "https://api.orcarouter.ai/v1"
        assert d.api_key == "sk-orca-hosted-xyz"
        assert d.custom_llm_provider == "openai"
        assert d.extra_headers == {"X-OrcaRouter-beta-usd": "response"}
        assert "/" in d.litellm_model


def test_orcarouter_upstream_combines_with_local_keys(monkeypatch):
    """Hosted-as-upstream coexists with local provider keys — fallback chain."""
    from app.config import Settings
    from app.router_cache import build_deployments

    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-h")
    s = Settings(_env_file=None)

    deps = build_deployments(env_keys={"openai": "sk-o"}, db_keys=[], settings=s)
    providers = {d.provider for d in deps}
    assert "openai" in providers
    assert "orcarouter" in providers


def test_orcarouter_db_row_enables_hosted_upstream():
    """Pasting the orcarouter key in the dashboard (→ DB row) lights up
    hosted upstream, not just an inert provider entry. Mirrors what happens
    after a user clicks "Activate fallback" on the hosted CTA card."""
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.auth.encryption import encrypt_credential
    from packages.db.models.provider_key import ProviderKey
    from packages.litellm_adapter.hosted_catalog import (
        HOSTED_MODEL_ALIASES,
        HOSTED_MODELS,
    )

    s = Settings(_env_file=None)
    db_row = ProviderKey(
        provider="orcarouter",
        encrypted_key=encrypt_credential("sk-orca-from-dashboard"),
        key_prefix="sk-orca-...",
        label="default",
        is_enabled=True,
    )
    deps = build_deployments(env_keys={}, db_keys=[db_row], settings=s)
    orca_deps = [d for d in deps if d.provider == "orcarouter"]
    assert len(orca_deps) == len(HOSTED_MODELS) + len(HOSTED_MODEL_ALIASES)
    for d in orca_deps:
        assert d.api_key == "sk-orca-from-dashboard"
        assert d.api_base == "https://api.orcarouter.ai/v1"


def test_hosted_free_models_accept_exact_wire_ids(monkeypatch):
    """Free hosted IDs copied from O2's model list work unchanged in Lite."""
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.litellm_adapter.hosted_catalog import HOSTED_MODEL_ALIASES

    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-hosted-xyz")
    s = Settings(_env_file=None)
    deps = build_deployments(env_keys={}, db_keys=[], settings=s)

    by_group = {d.model_name: d for d in deps}
    assert HOSTED_MODEL_ALIASES <= by_group.keys()
    for wire_id in HOSTED_MODEL_ALIASES:
        assert by_group[wire_id].litellm_model == wire_id
        assert by_group[wire_id].provider == "orcarouter"


def test_orcarouter_db_row_overrides_env_key(monkeypatch):
    """DB-stored hosted key beats env, just like every other provider does.
    Lets a user rotate via the dashboard without restarting the container."""
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.auth.encryption import encrypt_credential
    from packages.db.models.provider_key import ProviderKey

    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-from-env")
    s = Settings(_env_file=None)

    db_row = ProviderKey(
        provider="orcarouter",
        encrypted_key=encrypt_credential("sk-orca-from-db"),
        key_prefix="sk-orca-...",
        label="default",
        is_enabled=True,
    )
    deps = build_deployments(env_keys={}, db_keys=[db_row], settings=s)
    orca_deps = [d for d in deps if d.provider == "orcarouter"]
    assert orca_deps  # at least one
    assert all(d.api_key == "sk-orca-from-db" for d in orca_deps)


def test_disabled_orcarouter_db_row_falls_back_to_env(monkeypatch):
    """A disabled hosted DB row shouldn't shadow the env key — env is the
    fallback when the dashboard-stored key is turned off."""
    from app.config import Settings
    from app.router_cache import build_deployments
    from packages.auth.encryption import encrypt_credential
    from packages.db.models.provider_key import ProviderKey

    monkeypatch.setenv("ORCAROUTER_API_KEY", "sk-orca-from-env")
    s = Settings(_env_file=None)

    db_row = ProviderKey(
        provider="orcarouter",
        encrypted_key=encrypt_credential("sk-orca-disabled"),
        key_prefix="sk-orca-...",
        label="default",
        is_enabled=False,
    )
    deps = build_deployments(env_keys={}, db_keys=[db_row], settings=s)
    orca_deps = [d for d in deps if d.provider == "orcarouter"]
    assert orca_deps
    assert all(d.api_key == "sk-orca-from-env" for d in orca_deps)


def test_hosted_key_source_reports_origin(monkeypatch):
    """`hosted_key_source` underpins the dashboard's "Hosted fallback"
    pill — must distinguish dashboard-set vs env-set vs unconfigured."""
    from app.router_cache import hosted_key_source
    from packages.auth.encryption import encrypt_credential
    from packages.db.models.provider_key import ProviderKey

    assert hosted_key_source(env_key=None, db_keys=[]) is None
    assert hosted_key_source(env_key="sk-orca-x", db_keys=[]) == "env"

    db_row = ProviderKey(
        provider="orcarouter",
        encrypted_key=encrypt_credential("sk-orca-d"),
        key_prefix="sk-orca-...",
        label="default",
        is_enabled=True,
    )
    assert hosted_key_source(env_key=None, db_keys=[db_row]) == "dashboard"
    # DB beats env in the precedence reporting too
    assert hosted_key_source(env_key="sk-orca-x", db_keys=[db_row]) == "dashboard"


def test_hosted_key_source_treats_undecryptable_db_row_as_unconfigured():
    """A DB row whose ciphertext can't be decrypted (e.g. after encryption-
    key rotation or DB corruption) is functionally unusable —
    build_deployments silently drops it and never creates hosted
    deployments. hosted_key_source must report the same view, otherwise
    /v1/hosted lies about coverage and the dashboard shows "Active" while
    requests fail."""
    from app.router_cache import hosted_key_source
    from packages.db.models.provider_key import ProviderKey

    corrupt = ProviderKey(
        provider="orcarouter",
        encrypted_key=b"too-short-to-be-valid-aesgcm",
        key_prefix="sk-orca-...",
        label="default",
        is_enabled=True,
    )
    # No env, only a corrupt DB row → unconfigured.
    assert hosted_key_source(env_key=None, db_keys=[corrupt]) is None
    # Env still wins as fallback when the DB row can't be decrypted.
    assert hosted_key_source(env_key="sk-orca-env", db_keys=[corrupt]) == "env"


def test_usable_providers_from_db_skips_undecryptable_rows():
    """Helper that mirrors build_deployments' decryption filter so callers
    reporting 'configured providers' (e.g. /v1/analytics/unreachable) can't
    drift from what the router actually deploys."""
    from app.router_cache import usable_providers_from_db
    from packages.auth.encryption import encrypt_credential
    from packages.db.models.provider_key import ProviderKey

    rows = [
        ProviderKey(
            provider="openai",
            encrypted_key=encrypt_credential("sk-good"),
            key_prefix="sk-...", label="default", is_enabled=True,
        ),
        ProviderKey(
            provider="anthropic",
            encrypted_key=b"corrupt-blob-cant-decrypt",
            key_prefix="sk-ant-...", label="default", is_enabled=True,
        ),
        ProviderKey(
            provider="google",
            encrypted_key=encrypt_credential("sk-disabled"),
            key_prefix="sk-...", label="default", is_enabled=False,
        ),
    ]
    assert usable_providers_from_db(rows) == {"openai"}
