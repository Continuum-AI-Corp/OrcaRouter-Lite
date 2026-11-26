"""Nothing we ship promises "$5 free credit".

OrcaRouter no longer gives sign-up credit. What it offers is free models and a
hosted gateway (one key for every model, failover between providers), so the
READMEs, INSTALL.md, the dashboard, the app's pages and the landing page talk
about free models instead. This trips if an old claim, in any language, comes
back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SHIPPED = [
    *sorted(ROOT.glob("README*.md")),
    ROOT / "INSTALL.md",
    *sorted(p for p in (ROOT / "design").rglob("*") if p.suffix in {".html", ".js", ".css", ".py"}),
    *sorted(p for p in (ROOT / "desktop" / "ui").rglob("*") if p.suffix in {".html", ".js", ".css", ".md"}),
    *sorted((ROOT / "app").rglob("*.py")),
    *sorted(p for p in (ROOT / "site").rglob("*") if p.suffix in {".html", ".js", ".css", ".md"}),
    *sorted(p for p in (ROOT / "docs").rglob("*.md")),
]

# "$5", "5 USD", "5美元", "5 ドル", "5달러", "5 dollars"... not "$5.20" or "$50".
FIVE_DOLLARS = re.compile(
    r"(?:\$\s?5(?![\d]|[.,]\d)|(?<![\d.,])\b5\s?\$|\b5\s?(?:USD|US\$|dollars?|долл\w*)\b|5\s?(?:美元|美金|ドル|달러|डॉलर))",
    re.I,
)
# Words that turn an amount into a sign-up offer, in the README languages.
OFFER = re.compile(
    r"free|credit|trial|gratis|gratuit|gratuito|grátis|kostenlos|guthaben|crédit|crédito|credito"
    r"|бесплатн|кредит|miễn phí|tín dụng|免费|赠送|額度|额度|無料|クレジット|무료|크레딧|मुफ़्त|क्रेडिट",
    re.I,
)
FREE_CREDIT = re.compile(
    r"free\s+(?:trial\s+)?credit|trial\s+credit|sign-?up\s+credit|free\s+\$\s?\d", re.I
)


def _claims(text: str) -> list[str]:
    hits = []
    for line in text.splitlines():
        if FREE_CREDIT.search(line) or (FIVE_DOLLARS.search(line) and OFFER.search(line)):
            hits.append(line.strip())
    return hits


def test_the_scan_covers_every_shipped_surface():
    names = {p.relative_to(ROOT).as_posix() for p in SHIPPED}
    for must in ("README.md", "README.zh.md", "INSTALL.md", "design/index.html", "design/app.js",
                 "desktop/ui/setup.html", "app/routes/hosted.py", "app/routes/analytics.py"):
        assert must in names


@pytest.mark.parametrize(
    "line",
    [
        'drives the dashboard\'s "Get $5 free credit" card',
        "Free <strong>$5</strong> trial credit on sign-up",
        '<span class="pill free">$5 free</span>',
        "免费获得 5 美元额度",
        "„5 $ Guthaben gratis“",
        "No account yet? Sign up for free credit",
    ],
)
def test_the_detector_catches_old_wording(line):
    assert _claims(line)


@pytest.mark.parametrize(
    "line",
    [
        "Free models to start; pay per request for paid models.",
        "Today $4.05 · 20% of $20.00",
        "A daily budget of $5.00 stops agents at 100%.",
        "$50 saved this month",
    ],
)
def test_the_detector_leaves_ordinary_amounts_alone(line):
    assert not _claims(line)


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_shipped_file_claims_five_dollars_free_credit(path):
    hits = _claims(path.read_text(encoding="utf-8", errors="replace"))
    assert not hits, f"{path.relative_to(ROOT)} still promises sign-up credit: {hits}"
