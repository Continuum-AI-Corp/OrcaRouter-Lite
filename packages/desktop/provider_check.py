"""Check a provider key with the provider before the desktop app saves it.

The check lists the provider's models, which every one of these APIs offers
and which spends no tokens: 200 means the key works, 401/403 means it
doesn't. A network problem is reported as "unreachable" and doesn't stop the
key being saved, so setup still works offline. The key itself never appears
in a result.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx

# provider -> (display name, default models URL, how the key is sent, env var overriding the base URL)
CHECKS: dict[str, tuple[str, str, str, str | None]] = {
    "openai": ("OpenAI", "https://api.openai.com/v1", "bearer", "OPENAI_BASE_URL"),
    "anthropic": ("Anthropic", "https://api.anthropic.com/v1", "x-api-key", "ANTHROPIC_BASE_URL"),
    "google": ("Google", "https://generativelanguage.googleapis.com/v1beta", "x-goog-api-key", None),
    "deepseek": ("DeepSeek", "https://api.deepseek.com", "bearer", None),
    "xai": ("xAI", "https://api.x.ai/v1", "bearer", None),
    "mistral": ("Mistral", "https://api.mistral.ai/v1", "bearer", None),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "bearer", None),
    "together": ("Together", "https://api.together.xyz/v1", "bearer", None),
    "fireworks": ("Fireworks", "https://api.fireworks.ai/inference/v1", "bearer", None),
    "orcarouter": ("OrcaRouter", "https://api.orcarouter.ai/v1", "bearer", "ORCAROUTER_BASE_URL"),
}


def _request(provider: str, key: str, env: Mapping[str, str]) -> tuple[str, str, dict[str, str]]:
    name, base, style, env_var = CHECKS[provider]
    base = (env.get(env_var) if env_var else None) or base
    headers: dict[str, str]
    if style == "bearer":
        headers = {"Authorization": f"Bearer {key}"}
    elif style == "x-api-key":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        headers = {"x-goog-api-key": key}
    return name, f"{base.rstrip('/')}/models", headers


async def check_key(
    provider: str,
    key: str,
    *,
    client: httpx.AsyncClient,
    env: Mapping[str, str],
) -> dict[str, str]:
    """{"status": valid|invalid|unreachable|unchecked, "detail": text for the user}."""
    if provider not in CHECKS:
        return {"status": "unchecked", "detail": "Saved without checking; this provider has no key check."}
    name, url, headers = _request(provider, key, env)
    try:
        r = await client.get(url, headers=headers, timeout=10)
    except httpx.HTTPError:
        return {"status": "unreachable", "detail": f"Couldn't reach {name} to check the key; it's saved anyway."}
    if r.status_code in (401, 403):
        return {"status": "invalid", "detail": f"{name} rejected this key. Check you copied all of it."}
    if r.is_success:
        return {"status": "valid", "detail": f"{name} accepted the key."}
    return {"status": "unreachable", "detail": f"{name} answered {r.status_code} while checking the key; it's saved anyway."}
