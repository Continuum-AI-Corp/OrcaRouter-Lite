"""The container must boot on platform volumes mounted over /data.

Fly volumes, Railway volumes and Render disks are mounted root-owned over
/data, hiding the image's `chown`, so a non-root process can't create the
SQLite file and the service never passes /health. The image starts as root,
hands /data to the `orca` user when it isn't already, and then drops to that
user before starting the server. Under a platform that already runs the
container as a non-root user, it starts the server directly.

The script runs here against stub `id`, `stat`, `chown` and `setpriv`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "docker-entrypoint.sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")


def _stub(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(0o755)


def _run(tmp_path, *, uid: str, owner: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _stub(bin_dir, "id", f'[ "$1" = "-u" ] && echo {uid}')
    _stub(bin_dir, "stat", f"echo {owner}")
    _stub(bin_dir, "chown", f'echo "chown $*" >> {log}')
    _stub(bin_dir, "setpriv", f'echo "setpriv $*" >> {log}')
    data = tmp_path / "data"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "ORCA_DATA_DIR": str(data)}
    r = subprocess.run(["sh", str(SCRIPT), "echo", "server-started"], env=env, capture_output=True, text=True)
    return r, (log.read_text() if log.exists() else ""), data


def test_as_root_it_hands_a_root_owned_volume_to_orca_then_drops_privileges(tmp_path):
    r, calls, data = _run(tmp_path, uid="0", owner="root")
    assert r.returncode == 0, r.stderr
    assert data.is_dir()
    assert f"chown -R orca:orca {data}" in calls
    assert re.search(r"setpriv --reuid=orca --regid=orca --init-groups .*echo server-started", calls)


def test_as_root_it_leaves_an_orca_owned_volume_alone(tmp_path):
    _r, calls, _data = _run(tmp_path, uid="0", owner="orca")
    assert "chown" not in calls
    assert "setpriv" in calls


def test_as_a_non_root_user_it_just_starts_the_server(tmp_path):
    r, calls, _data = _run(tmp_path, uid="1000", owner="root")
    assert r.returncode == 0, r.stderr
    assert calls == ""
    assert r.stdout.strip() == "server-started"


def test_the_image_uses_the_entrypoint():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]' in dockerfile
    assert "\nUSER orca" not in dockerfile  # the entrypoint drops to orca itself
    assert os.access(SCRIPT, os.X_OK)


def test_railway_needs_no_run_as_root_override():
    assert "RAILWAY_RUN_UID" not in (ROOT / "README.md").read_text()
