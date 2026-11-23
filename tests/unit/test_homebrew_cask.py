"""The Homebrew cask is rendered from a release's real macOS .dmg files.

Apple silicon and Intel each get their own .dmg and checksum; Homebrew picks
the right one with `arch`.
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
def dmgs(tmp_path):
    arm = tmp_path / "OrcaRouter Lite_0.2.0_aarch64.dmg"
    x64 = tmp_path / "OrcaRouter Lite_0.2.0_x64.dmg"
    arm.write_bytes(b"arm-bytes")
    x64.write_bytes(b"intel-bytes")
    return arm, x64


def _run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def test_renders_a_two_arch_cask_with_version_and_checksums(dmgs):
    arm, x64 = dmgs
    r = _run("--version", "0.2.0", "--arm64", str(arm), "--x64", str(x64))
    assert r.returncode == 0, r.stderr
    cask = r.stdout
    assert 'cask "orcarouter-lite" do' in cask
    assert 'arch arm: "aarch64", intel: "x64"' in cask
    assert 'version "0.2.0"' in cask
    assert f'arm:   "{hashlib.sha256(b"arm-bytes").hexdigest()}"' in cask
    assert f'intel: "{hashlib.sha256(b"intel-bytes").hexdigest()}"' in cask
    assert "releases/download/v#{version}/OrcaRouter%20Lite_#{version}_#{arch}.dmg" in cask
    assert "depends_on arch" not in cask
    assert 'app "OrcaRouter Lite.app"' in cask
    assert 'zap trash: "~/.orcarouter-lite"' in cask


def test_refuses_files_from_another_version(dmgs):
    arm, x64 = dmgs
    r = _run("--version", "0.3.0", "--arm64", str(arm), "--x64", str(x64))
    assert r.returncode != 0
    assert "0.3.0" in r.stderr


def test_both_architectures_are_required(dmgs):
    arm, _ = dmgs
    assert _run("--version", "0.2.0", "--arm64", str(arm)).returncode != 0
