"""Provider credential encryption — AES-256-GCM.

Vendored from main repo, simplified. Reads CREDENTIAL_ENCRYPTION_KEY from the
loaded Settings (which honors `.env`) with `os.environ` as a fallback for
test fixtures that set the env var directly.

If neither yields a key, derives a deterministic dev key from a fixed seed
so local development doesn't require any setup. The dev fallback is
publicly known via the source code, so anyone with read access to the
SQLite file could decrypt provider keys with it:

- Every use logs a prominent WARNING (`insecure_dev_encryption_key`).
- `packages.db.guards.assert_credential_encryption_ready` fail-closes at
  startup when the fallback would protect real credentials (existing
  provider rows, or any non-SQLite database) unless
  ORCA_ALLOW_INSECURE_DEV_KEY=1 is set explicitly.

Ciphertext format:

- v1 (current): ``b"\\x01" + nonce(12) + ciphertext+tag``
- legacy:       ``nonce(12) + ciphertext+tag`` (no version byte)

Decrypt auto-detects. A legacy blob whose first nonce byte happens to be
``0x01`` (~0.4% of legacy blobs) is attempted as v1 first and falls back
to the legacy parse when authentication fails, so upgrades never brick
stored credentials.
"""

from __future__ import annotations

import hashlib
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger("orca.encryption")

VERSION_BYTE = b"\x01"
_NONCE_LEN = 12
_TAG_LEN = 16

_dev_fallback_warned = False


def _warn_dev_fallback_once() -> None:
    global _dev_fallback_warned
    if _dev_fallback_warned:
        return
    _dev_fallback_warned = True
    logger.warning(
        "insecure_dev_encryption_key: CREDENTIAL_ENCRYPTION_KEY is not set; "
        "provider credentials are being sealed with a PUBLICLY-KNOWN dev "
        "key. Anyone with read access to the database can decrypt them. "
        "Generate one with `openssl rand -hex 32` (or set "
        "ORCA_ALLOW_INSECURE_DEV_KEY=1 to silence this check)."
    )


def _get_encryption_key() -> bytes:
    key, _source = _resolve_key_material()
    return key


def _resolve_key_material() -> tuple[bytes, str]:
    """Return (key_bytes, source) where source names how the key was obtained.

    Sources: "config" (Settings/.env), "env" (os.environ), "dev-fallback".
    """
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
    if key_hex:
        try:
            raw = bytes.fromhex(key_hex)
            if len(raw) >= 32:
                return raw[:32], "config"
        except ValueError:
            pass
        return hashlib.sha256(key_hex.encode()).digest(), "config"
    key_hex = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
    if key_hex:
        try:
            raw = bytes.fromhex(key_hex)
            if len(raw) >= 32:
                return raw[:32], "env"
        except ValueError:
            pass
        return hashlib.sha256(key_hex.encode()).digest(), "env"
    # Dev fallback so test fixtures and `docker compose up` Just Work.
    _warn_dev_fallback_once()
    return hashlib.sha256(b"orcarouter-lite-dev-key").digest(), "dev-fallback"


def is_using_insecure_dev_key() -> bool:
    try:
        return _resolve_key_material()[1] == "dev-fallback"
    except Exception:
        return False


def encrypt_credential(plaintext: str) -> bytes:
    aes = AESGCM(_get_encryption_key())
    nonce = os.urandom(_NONCE_LEN)
    return VERSION_BYTE + nonce + aes.encrypt(nonce, plaintext.encode("utf-8"), None)


def decrypt_credential(blob: bytes) -> str:
    key = _get_encryption_key()
    aes = AESGCM(key)

    if blob[:1] == VERSION_BYTE and len(blob) >= 1 + _NONCE_LEN + _TAG_LEN:
        try:
            return aes.decrypt(
                blob[1:1 + _NONCE_LEN], blob[1 + _NONCE_LEN:], None
            ).decode("utf-8")
        except InvalidTag:
            # Could be a LEGACY blob whose first nonce byte happens to be
            # 0x01 (~0.4%). Fall through and try the unversioned layout
            # before giving up.
            pass
        except ValueError as e:
            # Malformed v1 blob (should be rare due to length check) — treat
            # as authentication failure rather than leaking ValueError.
            raise InvalidTag(str(e)) from e

    # Legacy unversioned blob: nonce(12) || ciphertext+tag.
    nonce, ciphertext = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    try:
        return aes.decrypt(nonce, ciphertext, None).decode("utf-8")
    except ValueError as e:
        # cryptography raises ValueError for malformed inputs (nonce must be
        # 12 bytes / data must be at least 16 bytes) rather than InvalidTag,
        # which is only for GCM tag mismatch. Normalize so callers and the
        # truncated-blob test have a single exception type to handle.
        raise InvalidTag(str(e)) from e
