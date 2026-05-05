"""Provider credential encryption — AES-256-GCM.

Vendored from main repo, simplified. Reads CREDENTIAL_ENCRYPTION_KEY from the
loaded Settings (which honors `.env`) with `os.environ` as a fallback for
test fixtures that set the env var directly.

If neither yields a key, derives a deterministic dev key from a fixed seed
so local development doesn't require any setup. **In production, set a real
64-char hex string** — the dev fallback is publicly known via the source
code, so anyone with read access to the SQLite file could decrypt provider
keys with it.
"""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_encryption_key() -> bytes:
    # Prefer Settings (which loads .env) over raw os.environ, because
    # pydantic-settings does NOT propagate .env values into os.environ.
    # Without this lookup, a user who follows the README and writes
    # CREDENTIAL_ENCRYPTION_KEY=... in .env would silently get the dev
    # fallback constant — the worst possible "secure by default" failure.
    key_hex = ""
    try:
        from app.config import get_settings
        key_hex = get_settings().credential_encryption_key or ""
    except Exception:
        # Settings may not be importable in some isolated test contexts;
        # fall through to env-only behavior.
        pass
    if not key_hex:
        key_hex = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
    if key_hex:
        try:
            raw = bytes.fromhex(key_hex)
            if len(raw) >= 32:
                return raw[:32]
        except ValueError:
            pass
        return hashlib.sha256(key_hex.encode()).digest()
    # Dev fallback so test fixtures and `docker compose up` Just Work.
    return hashlib.sha256(b"orcarouter-lite-dev-key").digest()


def encrypt_credential(plaintext: str) -> bytes:
    aes = AESGCM(_get_encryption_key())
    nonce = os.urandom(12)
    return nonce + aes.encrypt(nonce, plaintext.encode("utf-8"), None)


def decrypt_credential(blob: bytes) -> str:
    aes = AESGCM(_get_encryption_key())
    nonce, ciphertext = blob[:12], blob[12:]
    return aes.decrypt(nonce, ciphertext, None).decode("utf-8")
