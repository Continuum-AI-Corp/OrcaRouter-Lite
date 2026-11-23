"""Tell the desktop app when a newer release is out.

Once a day the engine asks GitHub for this repository's latest release. The
app then shows "Update available" with a link to the release page, where the
user downloads the new installer. Nothing is downloaded or installed here.

Only a stable (not draft, not pre-release) release of this repository counts,
and only a link to this repository's release pages is passed on. The request
carries a generic user agent and no information about the user. A failed
check is silent. Set ORCA_NO_UPDATE_CHECK=1 to switch it off.
"""

from __future__ import annotations

import asyncio
import os
import re

import httpx
import structlog

log = structlog.get_logger()

REPO = "Continuum-AI-Corp/OrcaRouter-Lite"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGES = f"https://github.com/{REPO}/releases/"
INTERVAL_SECONDS = 24 * 60 * 60

_STABLE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _parse(version: str) -> tuple[int, int, int] | None:
    m = _STABLE.fullmatch((version or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def is_newer(current: str, latest: str) -> bool:
    cur, new = _parse(current), _parse(latest)
    return bool(cur and new and new > cur)


class _CheckFailed(Exception):
    pass


async def check(current: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict | None:
    """{"version", "url"} when a newer stable release exists, else None."""
    try:
        return await _fetch(current, transport)
    except _CheckFailed:
        return None


async def _fetch(current: str, transport) -> dict | None:
    """Like check(), but raises _CheckFailed when GitHub couldn't be asked."""
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10) as client:
            resp = await client.get(
                LATEST_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": f"orcarouter-lite/{current}"},
            )
        if resp.status_code != 200:
            raise _CheckFailed(f"HTTP {resp.status_code}")
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise _CheckFailed(str(exc)) from exc
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag, url = data.get("tag_name"), data.get("html_url")
    if not isinstance(tag, str) or not isinstance(url, str) or not url.startswith(RELEASE_PAGES):
        return None
    if not is_newer(current, tag):
        return None
    return {"version": tag.lstrip("v"), "url": url}


class UpdateChecker:
    def __init__(self, current: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self.current = current
        self.latest: dict | None = None
        self._transport = transport

    @staticmethod
    def enabled() -> bool:
        return not os.environ.get("ORCA_NO_UPDATE_CHECK")

    async def refresh(self) -> None:
        if not self.enabled():
            return
        try:
            found = await _fetch(self.current, self._transport)
        except Exception as exc:  # never let the daily check die
            # A blip keeps what we knew; it's asked again tomorrow.
            log.info("update_check_failed", error=str(exc))
            return
        if found != self.latest:
            log.info("update_available" if found else "update_cleared", **(found or {}))
        self.latest = found

    async def run_forever(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(INTERVAL_SECONDS)


def current_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("orcarouter-lite")
    except PackageNotFoundError:
        return "0.0.0.dev0"


# The engine's checker; the lifespan starts it in desktop mode.
CHECKER = UpdateChecker(current_version())
