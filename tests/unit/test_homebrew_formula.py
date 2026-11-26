"""The Homebrew formula installs the `orca` CLI and engine alone, without the app.

`brew install --cask continuum-ai-corp/tap/orcarouter-lite` installs the app;
`brew install continuum-ai-corp/tap/orcarouter-lite` installs this formula: the
release's sdist from PyPI in a private virtualenv, with dependencies from the
hash-locked requirements.lock (LiteLLM had backdoored releases; see SECURITY.md).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "packaging" / "homebrew" / "render_formula.py"


@pytest.fixture
def sdist(tmp_path):
    p = tmp_path / "orcarouter_lite-0.2.0.tar.gz"
    p.write_bytes(b"sdist-bytes")
    return p


def _run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True)


def test_renders_a_formula_for_the_cli(sdist):
    r = _run("--version", "0.2.0", "--sdist", str(sdist))
    assert r.returncode == 0, r.stderr
    f = r.stdout
    assert "class OrcarouterLite < Formula" in f
    assert 'desc "Put a budget on every coding agent' in f
    assert (
        'url "https://files.pythonhosted.org/packages/source/o/orcarouter-lite/orcarouter_lite-0.2.0.tar.gz"' in f
    )
    assert f'sha256 "{hashlib.sha256(b"sdist-bytes").hexdigest()}"' in f
    assert 'license "MIT"' in f
    assert 'depends_on "python@3.12"' in f
    assert '"--require-hashes", "-r", buildpath/"requirements.lock"' in f
    assert '"--no-deps"' in f
    assert 'bin.install_symlink libexec/"bin/orca"' in f
    assert 'shell_output("#{bin}/orca --help")' in f
    assert f.rstrip().endswith("end")


def test_refuses_an_sdist_from_another_version(sdist):
    r = _run("--version", "0.3.0", "--sdist", str(sdist))
    assert r.returncode != 0
    assert "0.3.0" in r.stderr


def test_sdist_ships_the_lockfile_the_formula_installs_from():
    with (ROOT / "pyproject.toml").open("rb") as f:
        include = tomllib.load(f)["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "requirements.lock" in include


def test_release_workflow_renders_and_attaches_the_formula():
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "packaging/homebrew/render_formula.py" in wf
    assert "orcarouter-lite-formula.rb" in wf


def test_install_guide_documents_app_and_cli_paths():
    text = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    assert "brew install --cask continuum-ai-corp/tap/orcarouter-lite" in text
    assert "brew install continuum-ai-corp/tap/orcarouter-lite" in text
    assert "winget install OrcaRouter.Lite" in text



def test_only_intel_macs_build_cryptography_from_source(sdist):
    # on_intel alone also matches Linux x86_64 (Linuxbrew), which has
    # cryptography wheels and needs no Rust toolchain.
    f = _run("--version", "0.2.0", "--sdist", str(sdist)).stdout
    macos = f.index("on_macos do")
    intel = f.index("on_intel do")
    rust = f.index('depends_on "rust" => :build')
    assert macos < intel < rust
