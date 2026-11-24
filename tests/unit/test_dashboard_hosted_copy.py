"""The dashboard's OrcaRouter card describes the hosted gateway as it is today.

One key for every model, failover between providers, free models to start and
pay per request for paid models; no sign-up credit. The card's copy is
translated like the rest of the dashboard (design/app.js `I18N`), so every
locale carries the same keys and the page marks the elements with data-i18n.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = (ROOT / "design" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "design" / "index.html").read_text(encoding="utf-8")

HOSTED_KEYS = ("hosted.title", "hosted.sub", "hosted.register", "hosted.providers_sub", "hosted.ready_desktop")


def _locales() -> dict[str, dict[str, str]]:
    block = re.search(r"const I18N = \{(.*?)\n\};", APP_JS, re.S)
    assert block
    out = {}
    for locale, body in re.findall(r"\n\s{2}([a-z]{2}):\s*\{(.*?)\},", block.group(1), re.S):
        out[locale] = dict(re.findall(r'"([a-z0-9_.]+)"\s*:\s*"([^"]*)"', body))
    assert len(out) == 12
    return out


LOCALES = _locales()


@pytest.mark.parametrize("locale", sorted(LOCALES))
def test_every_locale_translates_the_hosted_card(locale):
    values = LOCALES[locale]
    for key in HOSTED_KEYS:
        assert values.get(key), f"{locale} is missing {key}"
        if locale != "en":
            assert values[key] != LOCALES["en"][key], f"{locale} uses English for {key}"
        assert "$" not in values[key]


def test_english_copy_describes_the_gateway():
    en = LOCALES["en"]
    assert en["hosted.title"] == "OrcaRouter gateway"
    assert "One key for every model" in en["hosted.sub"]
    assert "failover between providers" in en["hosted.sub"]
    assert "Free models to start" in en["hosted.sub"]
    assert "per request" in en["hosted.sub"]
    assert "free models" in en["hosted.register"]


@pytest.mark.parametrize("key", HOSTED_KEYS)
def test_the_card_marks_its_copy_for_translation(key):
    assert f'data-i18n="{key}"' in INDEX
