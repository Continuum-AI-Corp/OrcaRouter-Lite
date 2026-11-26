"""Join a team's OrcaRouter Lite gateway instead of a local engine.

A platform team runs Lite as a shared gateway and hands each developer a key.
`orca login <url> --key …` (and "Join my company's gateway" in setup) checks
the URL and key, then points the developer's coding agents at the gateway with
the same backup/restore guarantees as a local connection.

The URL must be https, or plain http only to loopback or a private network
address, so a key is never sent in the clear over the internet.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

STATE = "gateway.json"


class GatewayError(Exception):
    pass


def _private_host(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    parts = urlsplit(raw)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise GatewayError("Use the gateway's https:// address, for example https://ai-gw.example.com.")
    if parts.username or parts.password:
        raise GatewayError("Put the key in --key, not in the URL (no credentials in the address).")
    if parts.scheme == "http" and not _private_host(parts.hostname):
        raise GatewayError("Use https for a gateway on the internet; plain http is only allowed on a private network.")
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        raise GatewayError("Use the gateway's address without /v1, for example https://ai-gw.example.com.")
    return raw.rstrip("/")


def verify(url: str, key: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 10.0) -> None:
    """Confirm the gateway answers and accepts the key, without spending tokens."""
    base = normalize_url(url)
    try:
        with httpx.Client(transport=transport, timeout=timeout) as client:
            resp = client.get(f"{base}/v1/models", headers={"Authorization": f"Bearer {key}"})
    except httpx.TransportError as exc:
        raise GatewayError(f"Couldn't reach {base}. Check the address and your network.") from exc
    if resp.status_code in (401, 403):
        raise GatewayError("The gateway didn't accept that key. Ask your platform team for a new one.")
    if resp.status_code != 200:
        raise GatewayError(f"{base} answered with HTTP {resp.status_code}; is it an OrcaRouter gateway?")
    try:
        data = resp.json()
    except ValueError as exc:
        raise GatewayError(f"{base} doesn't look like an OrcaRouter gateway.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise GatewayError(f"{base} doesn't look like an OrcaRouter gateway.")


def save(home: Path, url: str) -> None:
    from packages.desktop.home import _write_private

    Path(home).mkdir(parents=True, exist_ok=True)
    _write_private(Path(home) / STATE, json.dumps({"url": url}))


def load(home: Path) -> str | None:
    try:
        return json.loads((Path(home) / STATE).read_text()).get("url")
    except (OSError, ValueError):
        return None


def forget(home: Path) -> None:
    try:
        (Path(home) / STATE).unlink()
    except FileNotFoundError:
        pass
