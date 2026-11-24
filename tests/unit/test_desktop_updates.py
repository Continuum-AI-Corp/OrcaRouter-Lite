"""Update check for the desktop app.

The engine asks GitHub for the latest release once a day and the app shows
"Update available" with a link to the release page. Only stable releases of
this repository count, only links to this repository's release pages are
passed on, and a failed check is silent (it never breaks the summary).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from packages.desktop import updates

PAGE = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/tag/v0.3.0"


def _transport(status=200, body=None, seen=None):
    def handler(request: httpx.Request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else {
            "tag_name": "v0.3.0", "html_url": PAGE, "draft": False, "prerelease": False})
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("current, latest, newer", [
    ("0.2.0", "v0.3.0", True),
    ("0.2.0", "0.2.1", True),
    ("0.2.9", "0.10.0", True),  # numeric, not string, comparison
    ("0.3.0", "v0.3.0", False),
    ("0.3.1", "v0.3.0", False),
    ("0.2.0", "v0.3.0-rc.1", False),  # pre-releases are never offered
    ("0.2.0", "nightly", False),
    ("0.2.0.dev0", "v0.3.0", False),  # a dev build doesn't nag
])
def test_is_newer(current, latest, newer):
    assert updates.is_newer(current, latest) is newer


async def test_check_reports_a_newer_stable_release():
    seen = []
    got = await updates.check("0.2.0", transport=_transport(seen=seen))
    assert got == {"version": "0.3.0", "url": PAGE}
    req = seen[0]
    assert str(req.url) == "https://api.github.com/repos/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest"
    assert req.headers["user-agent"] == "orcarouter-lite/0.2.0"  # nothing about the user


async def test_check_is_quiet_when_up_to_date():
    assert await updates.check("0.3.0", transport=_transport()) is None


@pytest.mark.parametrize("body", [
    {"tag_name": "v0.3.0", "html_url": PAGE, "draft": True, "prerelease": False},
    {"tag_name": "v0.3.0", "html_url": PAGE, "draft": False, "prerelease": True},
    {"tag_name": "v0.3.0", "html_url": "https://evil.example/download", "draft": False, "prerelease": False},
    {"tag_name": "v0.3.0", "html_url": "https://github.com/someone-else/OrcaRouter-Lite/releases/tag/v0.3.0"},
    {"html_url": PAGE},
    ["not", "an", "object"],
])
async def test_check_ignores_anything_that_is_not_a_stable_release_of_this_repo(body):
    assert await updates.check("0.2.0", transport=_transport(body=body)) is None


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_check_failures_are_silent(status):
    assert await updates.check("0.2.0", transport=_transport(status=status)) is None


async def test_check_network_errors_are_silent():
    def boom(_request):
        raise httpx.ConnectError("offline")
    assert await updates.check("0.2.0", transport=httpx.MockTransport(boom)) is None


async def test_checker_keeps_the_latest_result_and_can_be_switched_off(monkeypatch):
    monkeypatch.delenv("ORCA_NO_UPDATE_CHECK", raising=False)
    checker = updates.UpdateChecker("0.2.0", transport=_transport())
    assert checker.latest is None
    await checker.refresh()
    assert checker.latest == {"version": "0.3.0", "url": PAGE}

    monkeypatch.setenv("ORCA_NO_UPDATE_CHECK", "1")
    off = updates.UpdateChecker("0.2.0", transport=_transport())
    await off.refresh()
    assert off.latest is None


async def test_run_forever_checks_then_waits_a_day(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(updates.asyncio, "sleep", fake_sleep)
    monkeypatch.delenv("ORCA_NO_UPDATE_CHECK", raising=False)
    checker = updates.UpdateChecker("0.2.0", transport=_transport())
    with pytest.raises(asyncio.CancelledError):
        await checker.run_forever()
    assert checker.latest == {"version": "0.3.0", "url": PAGE}
    assert sleeps == [24 * 60 * 60]


async def test_a_failed_check_keeps_the_last_known_release(monkeypatch):
    monkeypatch.delenv("ORCA_NO_UPDATE_CHECK", raising=False)
    checker = updates.UpdateChecker("0.2.0", transport=_transport())
    await checker.refresh()
    checker._transport = _transport(status=500)  # a network blip a day later
    await checker.refresh()
    assert checker.latest == {"version": "0.3.0", "url": PAGE}


async def test_an_unexpected_error_never_ends_the_daily_check(monkeypatch):
    monkeypatch.delenv("ORCA_NO_UPDATE_CHECK", raising=False)

    def broken(_request):
        raise OSError("bad SSL_CERT_FILE")

    checker = updates.UpdateChecker("0.2.0", transport=httpx.MockTransport(broken))
    await checker.refresh()  # must not raise
    assert checker.latest is None


async def test_once_up_to_date_the_notice_clears(monkeypatch):
    monkeypatch.delenv("ORCA_NO_UPDATE_CHECK", raising=False)
    checker = updates.UpdateChecker("0.2.0", transport=_transport())
    await checker.refresh()
    checker.current = "0.3.0"  # the user updated
    await checker.refresh()
    assert checker.latest is None
