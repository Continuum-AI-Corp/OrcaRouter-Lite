"""Encryption key + API-key pepper must come from Settings (which loads .env)
in addition to os.environ — pydantic-settings does NOT propagate .env values
into os.environ, so reading os.environ alone silently falls back to the
public dev-fallback constant for any operator who follows the README.

These tests prove both helpers see the same value Settings exposes, even
when os.environ has nothing.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Strip the env vars these helpers also fall back to, so the test
    isolates whether Settings is being consulted at all."""
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("API_KEY_PEPPER", raising=False)


def test_encryption_reads_credential_key_from_settings(monkeypatch):
    """A key set on Settings (mimicking .env) must produce ciphertext that
    decrypts back round-trip. Without the Settings lookup, encrypt would
    use the dev fallback and decrypt would too — a green test that proves
    nothing. So we ALSO confirm the key is not the dev fallback by checking
    that encrypting under a different Settings key produces different
    ciphertext for the same plaintext."""
    from app import config as cfg

    # Two distinct hex keys — encrypt under each, ciphertext must differ.
    key_a = "00" * 32
    key_b = "ff" * 32

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "")  # ensure env path is empty

    # Build a Settings instance with our key and pin it via monkeypatch so
    # cleanup restores the real cached settings after the test. Pass
    # `_env_file=None` per-instance instead of mutating the class-level
    # model_config (which would persist across tests in the same process).
    s_a = cfg.Settings(_env_file=None, credential_encryption_key=key_a)
    monkeypatch.setattr(cfg, "get_settings", lambda: s_a)
    from packages.auth.encryption import decrypt_credential, encrypt_credential

    blob_a = encrypt_credential("hello world")
    assert decrypt_credential(blob_a) == "hello world"

    # Swap settings to a different key. The blob from key A must NOT
    # decrypt under key B — that's the only thing that proves the helper
    # is actually reading the Settings field instead of using a fixed
    # constant. Successful decrypt under one's own key + failed cross-key
    # decrypt together rule out the dev fallback.
    s_b = cfg.Settings(_env_file=None, credential_encryption_key=key_b)
    monkeypatch.setattr(cfg, "get_settings", lambda: s_b)
    # AES-GCM with the wrong key fails with InvalidTag, never silently
    # returns garbage. Pin the specific exception so future failures of
    # _other_ kinds (e.g. settings not loaded at all) get flagged as bugs
    # instead of being swallowed by a too-broad `pytest.raises(Exception)`.
    import pytest
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag):
        decrypt_credential(blob_a)
    # Sanity check: under key B, encrypting + decrypting still works.
    blob_b = encrypt_credential("hello world")
    assert decrypt_credential(blob_b) == "hello world"


def test_pepper_reads_from_settings(monkeypatch):
    """API_KEY_PEPPER set on Settings (mimicking .env) must be used by
    hash_api_key, even when os.environ has no pepper at all."""
    from app import config as cfg

    pepper_long_enough = "x" * 64
    cfg.get_settings.cache_clear()
    s = cfg.Settings(_env_file=None, api_key_pepper=pepper_long_enough)
    monkeypatch.setattr(cfg, "get_settings", lambda: s)
    from packages.auth.hashing import hash_api_key

    h_with_settings = hash_api_key("sk-orca-test")

    # Now point Settings at empty pepper — hash should change because the
    # helper falls back to plain SHA-256 with no pepper.
    s_empty = cfg.Settings(_env_file=None, api_key_pepper="")
    monkeypatch.setattr(cfg, "get_settings", lambda: s_empty)
    h_no_pepper = hash_api_key("sk-orca-test")

    assert h_with_settings != h_no_pepper, (
        "settings-based pepper must change the hash; if these match, the "
        "helper isn't reading from Settings"
    )
