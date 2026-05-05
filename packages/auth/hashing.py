"""API key generation, hashing, password utilities.

Vendored from main repo, simplified. Reads API_KEY_PEPPER from the loaded
Settings (which honors `.env`) with `os.environ` as a fallback for tests.
Lite is single-tenant so the brute-force surface is the operator's own
machine, but the pepper still matters for offline attacks against a stolen
SQLite file.
"""

import hashlib
import hmac
import os
import secrets


def _get_api_key_pepper() -> bytes | None:
    # Prefer Settings (which loads .env) over raw os.environ. pydantic-settings
    # does NOT propagate .env values into os.environ, so a user who follows
    # the README and sets API_KEY_PEPPER in .env would otherwise silently get
    # un-peppered (plain SHA-256) hashes — a downgrade from the documented
    # security posture.
    pepper = ""
    try:
        from app.config import get_settings
        pepper = get_settings().api_key_pepper or ""
    except Exception:
        # Settings may not be importable in some isolated test contexts.
        pass
    if not pepper:
        pepper = os.environ.get("API_KEY_PEPPER", "")
    if not pepper or len(pepper) < 32:
        return None
    return pepper.encode("utf-8")


def generate_api_key() -> tuple[str, str, str]:
    """Generate (full_key, key_hash, key_prefix). Plaintext shown to user once."""
    random_part = secrets.token_hex(16)
    full_key = f"sk-orca-{random_part}"
    key_hash = hash_api_key(full_key)
    key_prefix = f"sk-orca-....{random_part[-4:]}"
    return full_key, key_hash, key_prefix


def hash_api_key(raw_key: str) -> str:
    """HMAC-SHA256 with pepper if configured, else plain SHA-256."""
    pepper = _get_api_key_pepper()
    if pepper is None:
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return hmac.new(pepper, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def api_key_lookup_hashes(raw_key: str) -> tuple[str, str]:
    """Return (legacy_sha256, peppered) for dual-lookup during pepper rollout."""
    legacy = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    peppered = hash_api_key(raw_key)
    return legacy, peppered
