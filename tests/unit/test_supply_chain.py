"""Supply-chain guarantees that the release process depends on.

A gateway holds every provider key its users own. LiteLLM, our largest
dependency, shipped backdoored PyPI releases twice in 2026 (1.82.7/1.82.8 in
March, 1.107.0 in October). These tests keep the pin exact, the lockfile
hashed, and the release pipeline signing what it publishes.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KNOWN_COMPROMISED_LITELLM = {"1.82.7", "1.82.8", "1.107.0"}


def _deps() -> list[str]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]


def _litellm_pin() -> str:
    spec = next(d for d in _deps() if re.match(r"litellm\b", d))
    m = re.fullmatch(r"litellm==([0-9][0-9.]*)", spec.replace(" ", ""))
    assert m, f"litellm must be pinned exactly (==X.Y.Z), got {spec!r}"
    return m.group(1)


def test_litellm_is_pinned_exactly():
    _litellm_pin()


def test_litellm_pin_is_not_a_known_compromised_release():
    assert _litellm_pin() not in KNOWN_COMPROMISED_LITELLM


def _lock_entries() -> dict[str, str]:
    text = (ROOT / "requirements.lock").read_text()
    entries: dict[str, str] = {}
    for block in re.split(r"\n(?=[A-Za-z0-9])", text):
        first = block.strip().splitlines()[0] if block.strip() else ""
        m = re.match(r"([A-Za-z0-9_.\-\[\]]+)==([^\s;\\]+)", first)
        if m:
            entries[m.group(1).lower()] = block
    return entries


def test_lockfile_exists_and_every_entry_is_hashed():
    entries = _lock_entries()
    assert len(entries) > 20, "requirements.lock looks empty"
    unhashed = [name for name, block in entries.items() if "--hash=sha256:" not in block]
    assert unhashed == [], f"entries without hashes: {unhashed}"


def test_lockfile_pins_the_same_litellm():
    block = _lock_entries()["litellm"]
    assert block.startswith(f"litellm=={_litellm_pin()}")


def test_docker_image_installs_from_the_hashed_lockfile():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "requirements.lock" in dockerfile
    assert "--require-hashes" in dockerfile


def _release_steps() -> list[dict]:
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
    return wf["jobs"]["image"]["steps"]


def test_release_signs_the_published_image_with_cosign():
    steps = _release_steps()
    assert any(str(s.get("uses", "")).startswith("sigstore/cosign-installer@") for s in steps)
    assert any("cosign sign" in str(s.get("run", "")) for s in steps)


def test_release_publishes_an_sbom_attestation():
    steps = _release_steps()
    assert any(str(s.get("uses", "")).startswith("anchore/sbom-action@") for s in steps)
    assert any(str(s.get("uses", "")).startswith("actions/attest-sbom@") for s in steps)


def test_release_keeps_build_provenance():
    assert any(str(s.get("uses", "")).startswith("actions/attest-build-provenance@") for s in _release_steps())


def test_security_policy_exists_and_is_linked_from_the_readme():
    policy = (ROOT / "SECURITY.md").read_text()
    assert "Reporting a vulnerability" in policy
    assert "cosign verify" in policy
    assert "gh attestation verify" in policy
    assert "SECURITY.md" in (ROOT / "README.md").read_text()


def test_signing_and_sbom_actions_are_pinned_to_commits():
    # These run with id-token and packages: write, so a moved tag could sign
    # or push anything: pin them to full commit SHAs.
    sensitive = ("sigstore/cosign-installer@", "anchore/sbom-action@", "actions/attest-sbom@")
    for step in _release_steps():
        uses = str(step.get("uses", ""))
        if uses.startswith(sensitive):
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses), f"{uses} is not pinned to a commit"


def test_desktop_engine_build_tools_are_hash_locked():
    lock = (ROOT / "desktop" / "engine" / "requirements-build.lock").read_text()
    assert "pyinstaller==" in lock and "--hash=sha256:" in lock
    wf = (ROOT / ".github" / "workflows" / "desktop.yml").read_text()
    assert "requirements-build.lock" in wf
    assert '"pyinstaller>=' not in wf


def test_every_artifact_carries_the_same_version():
    import json

    py = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    tauri = json.loads((ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text())["version"]
    cargo = tomllib.loads((ROOT / "desktop" / "src-tauri" / "Cargo.toml").read_text())["package"]["version"]
    npm = json.loads((ROOT / "desktop" / "package.json").read_text())["version"]
    assert py == tauri == cargo == npm, f"pyproject {py}, tauri {tauri}, cargo {cargo}, npm {npm}"
