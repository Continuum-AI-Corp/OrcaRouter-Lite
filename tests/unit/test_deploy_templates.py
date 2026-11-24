"""One-click deploy templates (Render, Fly, Railway) must actually boot.

Each one builds the repo's Dockerfile, health-checks /health, keeps the
SQLite database on a persistent disk, and never ships a fixed secret: the
encryption key and key pepper are generated per deploy (Render) or set by the
operator (Fly, Railway), so two deploys never share a key.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPO_URL = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite"
SECRETS = ("CREDENTIAL_ENCRYPTION_KEY", "API_KEY_PEPPER")


def _db_dir(database_url: str) -> str:
    m = re.fullmatch(r"sqlite\+aiosqlite:///(/.+)/[^/]+\.db", database_url)
    assert m, f"expected an absolute SQLite path, got {database_url}"
    return m.group(1)


def _render():
    return yaml.safe_load((ROOT / "render.yaml").read_text())


def test_render_blueprint_builds_the_dockerfile_and_checks_health():
    [svc] = _render()["services"]
    assert svc["type"] == "web"
    assert svc["runtime"] == "docker"
    assert (ROOT / svc["dockerfilePath"]).is_file()
    assert svc["healthCheckPath"] == "/health"


def test_render_keeps_the_database_on_its_disk():
    [svc] = _render()["services"]
    env = {e["key"]: e for e in svc["envVars"]}
    assert _db_dir(env["DATABASE_URL"]["value"]) == svc["disk"]["mountPath"]


def test_render_generates_secrets_per_deploy_and_asks_for_provider_keys():
    [svc] = _render()["services"]
    env = {e["key"]: e for e in svc["envVars"]}
    for name in SECRETS:
        assert env[name] == {"key": name, "generateValue": True}
    # Provider keys are entered by the person deploying, never committed.
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        assert env[name] == {"key": name, "sync": False}


def test_fly_mounts_the_volume_where_the_database_lives():
    fly = tomllib.loads((ROOT / "fly.toml").read_text())
    assert _db_dir(fly["env"]["DATABASE_URL"]) == fly["mounts"]["destination"]
    assert fly["http_service"]["internal_port"] == int(fly["env"]["PORT"])
    assert fly["http_service"]["checks"][0]["path"] == "/health"
    assert not any(k in fly["env"] for k in SECRETS)


def test_railway_builds_the_dockerfile_and_checks_health():
    rw = json.loads((ROOT / "railway.json").read_text())
    assert (ROOT / rw["build"]["dockerfilePath"]).is_file()
    assert rw["deploy"]["healthcheckPath"] == "/health"


def test_readme_offers_working_deploy_buttons_and_no_placeholder():
    readme = (ROOT / "README.md").read_text()
    assert f"https://render.com/deploy?repo={REPO_URL}" in readme
    assert "fly launch" in readme
    assert "railway up" in readme
    assert "Template coming" not in readme


def test_platforms_run_the_images_entrypoint():
    # A custom start command can bypass the entrypoint that makes a mounted
    # /data volume writable; let the image's ENTRYPOINT and CMD run.
    rw = json.loads((ROOT / "railway.json").read_text())
    assert "startCommand" not in rw["deploy"]
    [svc] = _render()["services"]
    assert "dockerCommand" not in svc
