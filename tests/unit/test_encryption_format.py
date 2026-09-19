"""Tests for the versioned ciphertext format and legacy-blob compatibility.

The v1 format prefixes ``b"\\x01" + nonce + ct`` so key rotation becomes
possible later; legacy unversioned blobs (and the ~0.4% of them whose first
nonce byte collides with the version byte) must keep decrypting.
"""

from __future__ import annotations

import os

import pytest
from cryptography.exceptions import InvalidTag


@pytest.fixture
def hex_key(monkeypatch):
    """Pin a known 32-byte hex key via env (Settings-independent path)."""
    monkeypatch.delenv("CREDENTIAL_ENCRYPTION_KEY", raising=False)

    from app import config as cfg

    cfg.get_settings.cache_clear()
    s = cfg.Settings(_env_file=None, credential_encryption_key="ab" * 32)
    monkeypatch.setattr(cfg, "get_settings", lambda: s)
    return bytes.fromhex("ab" * 32)


def test_encrypt_produces_versioned_blob(hex_key):
    from packages.auth.encryption import VERSION_BYTE, decrypt_credential, encrypt_credential

    blob = encrypt_credential("sk-secret")
    assert blob[:1] == VERSION_BYTE
    assert len(blob) == 1 + 12 + len(b"sk-secret") + 16  # ver+nonce+ct+tag
    assert decrypt_credential(blob) == "sk-secret"


def test_decrypt_handles_legacy_unversioned_blob(hex_key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from packages.auth.encryption import decrypt_credential

    aes = AESGCM(hex_key)
    nonce = os.urandom(12)
    assert nonce[:1] != b"\x01"
    legacy = nonce + aes.encrypt(nonce, b"legacy-cred", None)
    assert decrypt_credential(legacy) == "legacy-cred"


def test_decrypt_recovers_legacy_blob_whose_nonce_starts_with_version_byte(hex_key):
    """A legacy blob with nonce[0] == 0x01 (~0.4% of old blobs) must not brick."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from packages.auth.encryption import VERSION_BYTE, decrypt_credential

    aes = AESGCM(hex_key)
    nonce = VERSION_BYTE + os.urandom(11)
    tricky_legacy = nonce + aes.encrypt(nonce, b"tricky", None)
    assert tricky_legacy[:1] == b"\x01"
    assert decrypt_credential(tricky_legacy) == "tricky"


def test_wrong_key_raises_invalid_tag(hex_key):
    from app import config as cfg
    from packages.auth.encryption import decrypt_credential, encrypt_credential

    blob = encrypt_credential("x")

    other = cfg.Settings(_env_file=None, credential_encryption_key="cd" * 32)
    cfg_get = cfg.get_settings
    cfg.get_settings = lambda: other  # not monkeypatched; restored below
    try:
        with pytest.raises(InvalidTag):
            decrypt_credential(blob)
    finally:
        cfg.get_settings = cfg_get


def test_truncated_blob_raises_rather_than_returning_garbage(hex_key):
    from packages.auth.encryption import decrypt_credential, encrypt_credential

    blob = encrypt_credential("x")
    with pytest.raises(InvalidTag):
        decrypt_credential(blob[:8])


def test_credential_is_decryptable_reports_current_key_only(hex_key, monkeypatch):
    from app import config as cfg
    from packages.auth.encryption import (
        credential_is_decryptable,
        decrypt_credential,
        encrypt_credential,
        materialize_encryption_key,
    )

    blob = encrypt_credential("sk-secret")
    assert credential_is_decryptable(blob) is True

    other = cfg.Settings(_env_file=None, credential_encryption_key="cd" * 32)
    monkeypatch.setattr(cfg, "get_settings", lambda: other)
    assert credential_is_decryptable(blob) is False
    # Explicit previous key still opens the blob (migrate path).
    assert decrypt_credential(blob, key=materialize_encryption_key("ab" * 32)) == "sk-secret"


def test_materialize_encryption_key_accepts_hex_and_passphrase():
    from packages.auth.encryption import materialize_encryption_key

    hex_key = materialize_encryption_key("ab" * 32)
    assert hex_key == bytes.fromhex("ab" * 32)
    assert len(materialize_encryption_key("not-hex-passphrase")) == 32
