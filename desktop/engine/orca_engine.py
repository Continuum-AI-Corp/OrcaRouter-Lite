"""Entry point frozen by PyInstaller into the desktop app's `orca-engine` sidecar."""

from app.orca_cli import entrypoint

if __name__ == "__main__":
    entrypoint()
