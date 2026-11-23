"""Render the Homebrew cask for a release from its two macOS .dmg files.

    python packaging/homebrew/render_cask.py --version 0.2.0 \
        --arm64 "OrcaRouter Lite_0.2.0_aarch64.dmg" \
        --x64 "OrcaRouter Lite_0.2.0_x64.dmg" > orcarouter-lite.rb

The release workflow attaches the result to the GitHub release; copy it to
`Casks/orcarouter-lite.rb` in the tap repository (see RELEASING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

CASK = """cask "orcarouter-lite" do
  arch arm: "aarch64", intel: "x64"

  version "{version}"
  sha256 arm:   "{arm}",
         intel: "{intel}"

  url "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/download/v#{{version}}/OrcaRouter%20Lite_#{{version}}_#{{arch}}.dmg"
  name "OrcaRouter Lite"
  desc "Put a budget on every coding agent"
  homepage "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite"

  depends_on macos: ">= :big_sur"

  app "OrcaRouter Lite.app"

  zap trash: "~/.orcarouter-lite"
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
    p.add_argument("--arm64", required=True, type=Path)
    p.add_argument("--x64", required=True, type=Path)
    a = p.parse_args(argv)
    for f in (a.arm64, a.x64):
        if f"_{a.version}_" not in f.name:
            print(f"{f.name} isn't a {a.version} build; pass the files from that release.", file=sys.stderr)
            return 2
    sys.stdout.write(CASK.format(version=a.version, arm=_sha256(a.arm64), intel=_sha256(a.x64)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
