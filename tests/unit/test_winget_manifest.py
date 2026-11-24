"""The winget manifests are rendered from a release's real Windows installer.

`winget install OrcaRouter.Lite` installs the app from the NSIS setup .exe on
the GitHub release (the installer whose uninstall hook restores agents). A
winget-pkgs submission is three files: version, installer and default locale,
under manifests/o/OrcaRouter/Lite/<version>/.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging" / "winget" / "render_manifest.py"
ID = "OrcaRouter.Lite"
SCHEMA = "1.6.0"


@pytest.fixture
def setup_exe(tmp_path):
    p = tmp_path / "OrcaRouter Lite_0.2.0_x64-setup.exe"
    p.write_bytes(b"windows-setup-bytes")
    return p


def _run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


@pytest.fixture
def rendered(setup_exe, tmp_path):
    out = tmp_path / "out"
    r = _run("--version", "0.2.0", "--installer", str(setup_exe), "--out", str(out), "--release-date", "2026-12-01")
    assert r.returncode == 0, r.stderr
    folder = out / "manifests" / "o" / "OrcaRouter" / "Lite" / "0.2.0"
    files = {p.name: p for p in folder.iterdir()}
    assert set(files) == {f"{ID}.yaml", f"{ID}.installer.yaml", f"{ID}.locale.en-US.yaml"}
    return {name: (p.read_text(encoding="utf-8"), yaml.safe_load(p.read_text(encoding="utf-8"))) for name, p in files.items()}


def test_every_file_agrees_on_package_version_and_schema(rendered):
    types = {}
    for name, (text, doc) in rendered.items():
        assert doc["PackageIdentifier"] == ID
        assert doc["PackageVersion"] == "0.2.0"
        assert doc["ManifestVersion"] == SCHEMA
        assert text.startswith(f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.{doc['ManifestType']}.{SCHEMA}.schema.json")
        types[doc["ManifestType"]] = name
    assert set(types) == {"version", "installer", "defaultLocale"}


def test_version_manifest(rendered):
    _, doc = rendered[f"{ID}.yaml"]
    assert doc["DefaultLocale"] == "en-US"


def test_installer_points_at_the_release_asset_with_its_checksum(rendered):
    _, doc = rendered[f"{ID}.installer.yaml"]
    assert doc["InstallerType"] == "nullsoft"
    assert doc["Scope"] == "user"
    assert str(doc["ReleaseDate"]) == "2026-12-01"  # YAML reads it as a date
    [inst] = doc["Installers"]
    assert inst["Architecture"] == "x64"
    assert inst["InstallerUrl"] == (
        "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/download/v0.2.0/OrcaRouter%20Lite_0.2.0_x64-setup.exe"
    )
    assert inst["InstallerSha256"] == hashlib.sha256(b"windows-setup-bytes").hexdigest().upper()
    assert re.fullmatch(r"[0-9A-F]{64}", inst["InstallerSha256"])
    assert doc["MinimumOSVersion"] == "10.0.17763.0"


def test_locale_manifest_has_the_required_fields(rendered):
    _, doc = rendered[f"{ID}.locale.en-US.yaml"]
    assert doc["PackageLocale"] == "en-US"
    for field in ("Publisher", "PackageName", "License", "ShortDescription"):
        assert doc[field], field
    assert doc["PackageName"] == "OrcaRouter Lite"
    assert doc["License"] == "MIT"
    assert doc["ShortDescription"] == "Put a budget on every coding agent"
    assert len(doc["ShortDescription"]) <= 256
    assert doc["PackageUrl"] == "https://continuum-ai-corp.github.io/OrcaRouter-Lite/"
    assert doc["ReleaseNotesUrl"].endswith("/releases/tag/v0.2.0")
    assert all(re.fullmatch(r"[a-z0-9-]+", t) for t in doc["Tags"])
    assert "$" not in doc["Description"]


def test_refuses_an_installer_from_another_version(setup_exe, tmp_path):
    r = _run("--version", "0.3.0", "--installer", str(setup_exe), "--out", str(tmp_path / "o"))
    assert r.returncode != 0
    assert "0.3.0" in r.stderr


def test_refuses_anything_but_the_x64_setup_exe(tmp_path):
    msi = tmp_path / "OrcaRouter Lite_0.2.0_x64_en-US.msi"
    msi.write_bytes(b"msi")
    r = _run("--version", "0.2.0", "--installer", str(msi), "--out", str(tmp_path / "o"))
    assert r.returncode != 0


def test_desktop_workflow_renders_and_attaches_the_manifests():
    wf = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
    assert "packaging/winget/render_manifest.py" in wf
