"""Soft provider-key format warnings (issue #142).

Obvious prefix misses should warn; unknown providers and matching prefixes
must stay silent so unusual-but-valid BYOK keys still store.
"""

import pytest

from app.routes.providers import provider_key_format_warning


@pytest.mark.parametrize(
    "provider, key",
    [
        ("openai", "sk-test-12345"),
        ("openai", "sk-proj-abcdefghijklmnopqrstuvwxyz"),
        ("anthropic", "sk-ant-api03-abc"),
        ("groq", "gsk_abc123"),
        ("xai", "xai-grok-key"),
        ("deepseek", "sk-deepseek-abc"),
        ("orcarouter", "sk-orca-hosted-abc"),
        ("google", "AIzaSyAbcdEfGhIj"),
        ("google", '{"type": "service_account", "private_key": "x"}'),
        ("fireworks", "fw_abc123"),
        # Variable / unknown formats — do not guess.
        ("together", "abc"),
        ("custom-proxy", "not-a-known-shape"),
    ],
)
def test_matching_or_unknown_provider_has_no_warning(provider, key):
    assert provider_key_format_warning(provider, key) is None


@pytest.mark.parametrize(
    "provider, key, expected_fragment",
    [
        ("openai", "abc", "sk-"),
        ("openai", "gsk_oops", "sk-"),
        ("anthropic", "sk-not-ant", "sk-ant-"),
        ("groq", "sk-wrong", "gsk_"),
        ("xai", "sk-wrong", "xai-"),
        ("deepseek", "gsk_wrong", "sk-"),
        ("orcarouter", "sk-not-orca", "sk-orca-"),
        ("fireworks", "sk-wrong", "fw_"),
        ("google", "abc", "AIza"),
        ("OpenAI", "abc", "OpenAI"),  # provider slug is case-insensitive
    ],
)
def test_obvious_mismatch_returns_warning(provider, key, expected_fragment):
    warning = provider_key_format_warning(provider, key)
    assert warning is not None
    assert expected_fragment in warning
    assert "Verify this is correct" in warning
    # Never echo the full key — only a short prefix.
    assert key not in warning or len(key) <= 5


def test_warning_uses_short_prefix_not_full_key():
    key = "totally-invalid-openai-credential-value"
    warning = provider_key_format_warning("openai", key)
    assert warning is not None
    assert key not in warning
    assert "total" in warning
