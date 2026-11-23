"""Write the build-time Tauri config that switches on in-app updates.

    python packaging/updater/updater_config.py --pubkey-file updater.pub \
        --out desktop/src-tauri/tauri.updater.conf.json

The desktop workflow runs this when the updater's signing key is configured
(pull requests use a throwaway key) and builds with
`tauri build --config <out>`. The app loads the updater only when the config
carries a public key and an https endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LATEST_JSON = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest/download/latest.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pubkey-file", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args(argv)
    pubkey = a.pubkey_file.read_text().strip()
    if not pubkey:
        print(f"{a.pubkey_file} is empty; no updater public key to build with.", file=sys.stderr)
        return 2
    config = {
        "bundle": {"createUpdaterArtifacts": True},
        "plugins": {"updater": {"pubkey": pubkey, "endpoints": [LATEST_JSON]}},
    }
    a.out.write_text(json.dumps(config, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
