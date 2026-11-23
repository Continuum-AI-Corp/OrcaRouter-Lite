"""Render latest.json, the manifest the desktop app's in-app updater reads.

    python packaging/updater/render_latest_json.py --version 0.2.0 updater/ > latest.json

`updater/` holds one release's updater files and their `.sig` signatures, as
the desktop workflow collects them:

    OrcaRouter Lite_<v>_aarch64.app.tar.gz   macOS, Apple silicon
    OrcaRouter Lite_<v>_x64.app.tar.gz       macOS, Intel
    OrcaRouter Lite_<v>_amd64.AppImage       Linux
    OrcaRouter Lite_<v>_x64-setup.exe        Windows (NSIS)

The release workflow attaches latest.json to the GitHub release; the app
fetches it from releases/latest/download/latest.json and installs an update
only if its signature matches the public key the app was built with.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

REPO = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite"

# (filename suffix, updater platform key)
PLATFORMS = (
    ("_aarch64.app.tar.gz", "darwin-aarch64"),
    ("_x64.app.tar.gz", "darwin-x86_64"),
    ("_amd64.AppImage", "linux-x86_64"),
    ("_x64-setup.exe", "windows-x86_64"),
)


def render(version: str, folder: Path) -> dict:
    platforms: dict[str, dict] = {}
    for path in sorted(folder.iterdir()):
        name = path.name
        match = next((key for suffix, key in PLATFORMS if name.endswith(suffix)), None)
        if match is None:
            continue
        if f"_{version}_" not in name:
            raise SystemExit(f"{name} isn't a {version} build; pass the files from that release.")
        sig = path.with_name(name + ".sig")
        if not sig.exists():
            raise SystemExit(f"{name} has no signature ({sig.name}); refusing to publish an unsigned update.")
        platforms[match] = {
            "signature": sig.read_text().strip(),
            "url": f"{REPO}/releases/download/v{version}/{quote(name)}",
        }
    if not platforms:
        raise SystemExit(f"No updater files for {version} in {folder}.")
    return {
        "version": version,
        "notes": f"{REPO}/releases/tag/v{version}",
        "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": platforms,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("folder", type=Path)
    a = p.parse_args(argv)
    try:
        manifest = render(a.version, a.folder)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(manifest, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
