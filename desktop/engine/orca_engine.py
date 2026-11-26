"""Entry point frozen by PyInstaller into the desktop app's `orca-engine` sidecar."""

import sys

# The app redirects the engine's output to engine.log. On Windows that stream
# defaults to cp1252, and one non-ASCII log line would crash the engine, so
# write UTF-8 and replace anything unencodable instead.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from app.orca_cli import entrypoint  # noqa: E402

if __name__ == "__main__":
    entrypoint()
