"""Outgoing links tagged with where they came from (H8).

Every link the engine hands the app or the dashboard (OrcaRouter's sign-up,
key, console and billing pages; the download page) carries `ref=<source>`,
so the landing page can count visits by source without cookies. Only these
fixed source names are allowed: a link never carries anything about the user.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LANDING_URL = "https://continuum-ai-corp.github.io/OrcaRouter-Lite/"

SETUP = "lite-setup"    # setup window and the dashboard's OrcaRouter card
CARD = "lite-card"      # the shareable savings card (V2)
BADGE = "lite-badge"    # the README badge (V6)
PANEL = "lite-panel"    # the menu-bar panel
SHARE = "lite-share"    # "Share my setup" (V3)
DASHBOARD = "lite-dashboard"  # the dashboard's OrcaRouter card (tagged in the browser)
SITE = "lite-site"      # the landing page's OrcaRouter section
SOURCES = (SETUP, CARD, BADGE, PANEL, SHARE, DASHBOARD, SITE)


def with_ref(url: str | None, source: str) -> str | None:
    """`url` with `ref=<source>` (replacing any earlier ref)."""
    if source not in SOURCES:
        raise ValueError(f"unknown link source: {source}")
    if not url:
        return None
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "ref"]
    query.append(("ref", source))
    return urlunsplit(parts._replace(query=urlencode(query)))
