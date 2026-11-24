"""Render the winget manifests for a release from its Windows setup .exe.

    python packaging/winget/render_manifest.py --version 0.2.0 \
        --installer "OrcaRouter Lite_0.2.0_x64-setup.exe" --out winget

writes winget/manifests/o/OrcaRouter/Lite/0.2.0/ with the three files a
microsoft/winget-pkgs pull request needs (version, installer, default
locale). The release workflow attaches them to the GitHub release; see
packaging/winget/README.md for submitting them.

The NSIS setup .exe is the installer winget uses, not the .msi: its uninstall
hook restores the coding agents Orca connected, and it installs per user.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path
from urllib.parse import quote

PACKAGE_ID = "OrcaRouter.Lite"
SCHEMA = "1.6.0"
REPO = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite"


def _header(kind: str) -> str:
    return f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.{kind}.{SCHEMA}.schema.json\n\n"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def render(version: str, installer: Path, release_date: str) -> dict[str, str]:
    url = f"{REPO}/releases/download/v{version}/{quote(installer.name)}"
    common = f"PackageIdentifier: {PACKAGE_ID}\nPackageVersion: {version}\n"
    tail = lambda kind: f"ManifestType: {kind}\nManifestVersion: {SCHEMA}\n"  # noqa: E731
    return {
        f"{PACKAGE_ID}.yaml": _header("version") + common + "DefaultLocale: en-US\n" + tail("version"),
        f"{PACKAGE_ID}.installer.yaml": _header("installer") + common + f"""InstallerLocale: en-US
MinimumOSVersion: 10.0.17763.0
InstallerType: nullsoft
Scope: user
UpgradeBehavior: install
ReleaseDate: {release_date}
Installers:
  - Architecture: x64
    InstallerUrl: {url}
    InstallerSha256: {_sha256(installer)}
""" + tail("installer"),
        f"{PACKAGE_ID}.locale.en-US.yaml": _header("defaultLocale") + common + f"""PackageLocale: en-US
Publisher: Continuum AI Corp
PublisherUrl: https://www.orcarouter.ai
PublisherSupportUrl: {REPO}/issues
PrivacyUrl: {REPO}/blob/main/SECURITY.md
Author: Continuum AI Corp
PackageName: OrcaRouter Lite
PackageUrl: https://continuum-ai-corp.github.io/OrcaRouter-Lite/
License: MIT
LicenseUrl: {REPO}/blob/main/LICENSE
Copyright: Copyright (c) Continuum AI Corp
ShortDescription: Put a budget on every coding agent
Description: >-
  A menu-bar app that runs a local router for your coding agents (Claude Code,
  Codex, Gemini CLI, OpenCode and more), shows what each one spends, and can
  stop them at a daily budget. Works with your own provider keys or the hosted
  OrcaRouter gateway. No telemetry.
Moniker: orcarouter-lite
Tags:
  - ai
  - budget
  - coding-agents
  - llm
  - router
ReleaseNotesUrl: {REPO}/releases/tag/v{version}
""" + tail("defaultLocale"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--installer", required=True, type=Path, help="the release's x64 NSIS setup .exe")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--release-date", default=date.today().isoformat())
    a = p.parse_args(argv)
    if not a.installer.name.endswith("_x64-setup.exe"):
        print(f"{a.installer.name} isn't the x64 setup .exe; winget installs that one.", file=sys.stderr)
        return 2
    if f"_{a.version}_" not in a.installer.name:
        print(f"{a.installer.name} isn't a {a.version} build; pass the file from that release.", file=sys.stderr)
        return 2
    folder = a.out / "manifests" / "o" / "OrcaRouter" / "Lite" / a.version
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in render(a.version, a.installer, a.release_date).items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
        print(folder / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
