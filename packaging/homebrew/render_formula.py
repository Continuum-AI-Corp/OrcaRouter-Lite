"""Render the Homebrew formula for the `orca` CLI from a release's sdist.

    python packaging/homebrew/render_formula.py --version 0.2.0 \
        --sdist dist/orcarouter_lite-0.2.0.tar.gz > orcarouter-lite-formula.rb

The formula is the CLI-only path (`brew install continuum-ai-corp/tap/orcarouter-lite`):
the engine and `orca` in a private virtualenv, no menu-bar app. The app is the
cask (render_cask.py). Dependencies come from the sdist's hash-locked
requirements.lock, the same pins the desktop build and Docker image use.

The release workflow attaches the result to the GitHub release; copy it to
`Formula/orcarouter-lite.rb` in the tap repository (see RELEASING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

FORMULA = """class OrcarouterLite < Formula
  desc "Put a budget on every coding agent (orca CLI and local router)"
  homepage "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite"
  url "https://files.pythonhosted.org/packages/source/o/orcarouter-lite/orcarouter_lite-{version}.tar.gz"
  sha256 "{sha256}"
  license "MIT"

  depends_on "python@3.12"

  on_macos do
    on_intel do
      # cryptography ships no Intel macOS wheels, so pip builds it from source.
      depends_on "openssl@3"
      depends_on "rust" => :build
    end
  end

  def install
    python = Formula["python@3.12"].opt_bin/"python3.12"
    system python, "-m", "venv", libexec
    pip = libexec/"bin/pip"
    system pip, "install", "--no-cache-dir", "--require-hashes", "-r", buildpath/"requirements.lock"
    system pip, "install", "--no-cache-dir", "--no-deps", buildpath
    bin.install_symlink libexec/"bin/orca"
    bin.install_symlink libexec/"bin/orcarouter-lite"
  end

  def caveats
    <<~EOS
      This is the command-line tool alone. For the menu-bar app:
        brew install --cask continuum-ai-corp/tap/orcarouter-lite
      Start the router with `orca up`, then `orca connect claude-code`.
    EOS
  end

  test do
    assert_match "orca", shell_output("#{{bin}}/orca --help")
  end
end
"""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--sdist", required=True, type=Path)
    a = p.parse_args(argv)
    if a.sdist.name != f"orcarouter_lite-{a.version}.tar.gz":
        print(f"{a.sdist.name} isn't the {a.version} sdist; pass orcarouter_lite-{a.version}.tar.gz.", file=sys.stderr)
        return 2
    sys.stdout.write(FORMULA.format(version=a.version, sha256=_sha256(a.sdist)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
