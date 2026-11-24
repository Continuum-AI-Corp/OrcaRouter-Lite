"""The launch kit (docs/launch/) and the script that records its demo GIF."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAUNCH = ROOT / "docs" / "launch"


def test_kit_is_complete():
    for name in ("checklist.md", "show-hn.md", "product-hunt.md", "demo-script.md", "demo.gif"):
        assert (LAUNCH / name).is_file(), name
    assert (LAUNCH / "demo.gif").read_bytes()[:6] in (b"GIF87a", b"GIF89a")
    assert (LAUNCH / "demo.gif").stat().st_size < 2_000_000


def test_storyboard_has_four_scenes_in_thirty_seconds():
    text = (LAUNCH / "demo-script.md").read_text(encoding="utf-8")
    for slot, scene in (("0:00–0:06", "Install"), ("0:06–0:14", "Connect"), ("0:14–0:22", "Spend"), ("0:22–0:30", "Alert")):
        assert f"| {slot} | **{scene}** |" in text


def test_show_hn_title_fits():
    text = (LAUNCH / "show-hn.md").read_text(encoding="utf-8")
    title = next(line[2:] for line in text.splitlines() if line.startswith("> Show HN:"))
    assert len(title) <= 80


def test_product_hunt_tagline_fits():
    lines = (LAUNCH / "product-hunt.md").read_text(encoding="utf-8").splitlines()
    tagline = lines[lines.index("**Tagline** (60 characters max):") + 2]
    assert len(tagline.removeprefix("> ")) <= 60


def test_recorder_uses_the_demo_seeder_in_a_throwaway_home():
    sh = (ROOT / "scripts" / "record_demo.sh").read_text(encoding="utf-8")
    assert "desktop/scripts/seed_demo.py" in sh
    assert 'export HOME="$WORK/home"' in sh
    assert "mktemp -d" in sh and 'rm -rf "$WORK"' in sh


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_recorder_script_parses():
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "record_demo.sh")]).returncode == 0


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_recorder_frames_script_parses():
    assert subprocess.run(["node", "--check", str(ROOT / "scripts" / "record_demo.cjs")]).returncode == 0
