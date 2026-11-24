"""The build-time config that switches on in-app updates.

Release CI writes it when the updater's signing key is configured (pull
requests use a throwaway key) and passes it to `tauri build --config`. The
app only loads the updater when this config has a public key and an https
endpoint (desktop/src-tauri/src/logic.rs, updates_installable).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging" / "updater" / "updater_config.py"


def _run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def test_writes_the_key_endpoint_and_updater_artifacts(tmp_path):
    pub = tmp_path / "updater.pub"
    pub.write_text("dW50cnVzdGVkIGNvbW1lbnQ=\n")
    out = tmp_path / "tauri.updater.conf.json"
    r = _run("--pubkey-file", str(pub), "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text()) == {
        "bundle": {"createUpdaterArtifacts": True},
        "plugins": {"updater": {
            "pubkey": "dW50cnVzdGVkIGNvbW1lbnQ=",
            "endpoints": ["https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest/download/latest.json"],
        }},
    }


def test_an_empty_key_is_refused(tmp_path):
    pub = tmp_path / "updater.pub"
    pub.write_text("  \n")
    r = _run("--pubkey-file", str(pub), "--out", str(tmp_path / "c.json"))
    assert r.returncode != 0
    assert not (tmp_path / "c.json").exists()
