"""The Homebrew cask is rendered from a release's real Apple-silicon .dmg.

Intel Macs aren't built: cryptography (a core dependency) ships no Intel
macOS wheels from 50.x on, so Intel users install with `uvx … orca up`.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging" / "homebrew" / "render_cask.py"


@pytest.fixture
def dmg(tmp_path):
    arm = tmp_path / "OrcaRouter Lite_0.2.0_aarch64.dmg"
    arm.write_bytes(b"arm-bytes")
    return arm


def _run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def test_renders_an_apple_silicon_cask_with_version_and_checksum(dmg):
    r = _run("--version", "0.2.0", "--arm64", str(dmg))
    assert r.returncode == 0, r.stderr
    cask = r.stdout
    assert 'cask "orcarouter-lite" do' in cask
    assert 'version "0.2.0"' in cask
    assert f'sha256 "{hashlib.sha256(b"arm-bytes").hexdigest()}"' in cask
    assert "releases/download/v#{version}/OrcaRouter%20Lite_#{version}_aarch64.dmg" in cask
    assert "depends_on arch: :arm64" in cask
    assert 'app "OrcaRouter Lite.app"' in cask
    assert 'zap trash: "~/.orcarouter-lite"' in cask


def test_refuses_a_version_that_does_not_match_the_file(dmg):
    r = _run("--version", "0.3.0", "--arm64", str(dmg))
    assert r.returncode != 0
    assert "0.3.0" in r.stderr
