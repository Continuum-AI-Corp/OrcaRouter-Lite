"""latest.json, the manifest the desktop app's in-app updater reads.

Built from a release's signed updater files: each platform's entry points at
its download on this repository's release page and carries the signature the
app checks against the public key it was built with. A file without its
signature is an error, never a silently unsigned update.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging" / "updater" / "render_latest_json.py"
BASE = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/download/v0.2.0"

FILES = {
    "OrcaRouter Lite_0.2.0_aarch64.app.tar.gz": "darwin-aarch64",
    "OrcaRouter Lite_0.2.0_x64.app.tar.gz": "darwin-x86_64",
    "OrcaRouter Lite_0.2.0_amd64.AppImage": "linux-x86_64",
    "OrcaRouter Lite_0.2.0_x64-setup.exe": "windows-x86_64",
}


@pytest.fixture
def release(tmp_path):
    d = tmp_path / "updater"
    d.mkdir()
    for name, platform in FILES.items():
        (d / name).write_bytes(b"payload")
        (d / f"{name}.sig").write_text(f"sig-for-{platform}\n")
    (d / "OrcaRouter Lite_0.2.0_x64_en-US.msi").write_bytes(b"not an updater file")
    return d


def _run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def test_every_platform_points_at_its_signed_download(release):
    r = _run("--version", "0.2.0", str(release))
    assert r.returncode == 0, r.stderr
    manifest = json.loads(r.stdout)
    assert manifest["version"] == "0.2.0"
    assert manifest["notes"] == "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/tag/v0.2.0"
    assert manifest["pub_date"].endswith("Z")
    assert set(manifest["platforms"]) == set(FILES.values())
    for name, platform in FILES.items():
        entry = manifest["platforms"][platform]
        assert entry["signature"] == f"sig-for-{platform}"
        assert entry["url"] == f"{BASE}/{name.replace(' ', '%20')}"


def test_a_file_without_its_signature_is_refused(release):
    (release / "OrcaRouter Lite_0.2.0_amd64.AppImage.sig").unlink()
    r = _run("--version", "0.2.0", str(release))
    assert r.returncode != 0
    assert "AppImage" in r.stderr and "signature" in r.stderr


def test_files_from_another_version_are_refused(release):
    r = _run("--version", "0.3.0", str(release))
    assert r.returncode != 0
    assert "0.3.0" in r.stderr


def test_an_empty_release_is_refused(tmp_path):
    r = _run("--version", "0.2.0", str(tmp_path))
    assert r.returncode != 0
