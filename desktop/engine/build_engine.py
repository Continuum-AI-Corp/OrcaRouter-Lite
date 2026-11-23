"""Build the `orca-engine` sidecar the desktop installer bundles.

    pip install -e ".[desktop-build]"
    python desktop/engine/build_engine.py

Produces desktop/src-tauri/binaries/orca-engine-<rust target triple>[.exe],
the name Tauri's `externalBin` expects. Run it on each platform you ship.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEP = os.pathsep  # PyInstaller's --add-data separator


def target_triple() -> str:
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    return next(line.split(": ", 1)[1] for line in out.splitlines() if line.startswith("host: "))


def main() -> int:
    work = ROOT / "build" / "orca-engine"
    dist = work / "dist"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--noconfirm", "--clean",
        "--name", "orca-engine",
        "--distpath", str(dist), "--workpath", str(work / "build"), "--specpath", str(work),
        "--paths", str(ROOT),
        # Served pages: the dashboard and the desktop UI.
        "--add-data", f"{ROOT / 'design'}{SEP}app/design",
        "--add-data", f"{ROOT / 'desktop' / 'ui'}{SEP}app/desktop_ui",
        # Loaded by name at runtime, so static analysis can't see them:
        # uvicorn imports the app, SQLAlchemy imports its async SQLite driver,
        # passlib imports its hash handlers.
        "--hidden-import", "app.main",
        "--hidden-import", "aiosqlite",
        "--collect-submodules", "sqlalchemy.dialects.sqlite",
        "--collect-submodules", "passlib.handlers",
        "--collect-submodules", "app",
        "--collect-submodules", "packages",
        "--collect-submodules", "uvicorn",
        "--collect-data", "litellm",
        "--collect-submodules", "litellm",
        "--collect-submodules", "tiktoken_ext",
        "--copy-metadata", "orcarouter-lite",
        str(ROOT / "desktop" / "engine" / "orca_engine.py"),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = ".exe" if os.name == "nt" else ""
    out = ROOT / "desktop" / "src-tauri" / "binaries" / f"orca-engine-{target_triple()}{exe}"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dist / f"orca-engine{exe}", out)
    # ASCII only: Windows consoles default to cp1252.
    print(f"built {out} ({out.stat().st_size // (1024 * 1024)} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
