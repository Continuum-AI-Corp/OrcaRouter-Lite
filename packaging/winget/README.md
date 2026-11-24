# winget

`winget install OrcaRouter.Lite` installs the Windows app from the release's
NSIS setup `.exe` (per user; its uninstaller restores the agents Orca
connected).

On every `v*` tag the `winget-manifest` job in `.github/workflows/desktop.yml`
runs `render_manifest.py` against the built setup `.exe` and attaches three
files to the GitHub release:

- `OrcaRouter.Lite.yaml` (version)
- `OrcaRouter.Lite.installer.yaml` (installer URL, SHA-256, scope, type)
- `OrcaRouter.Lite.locale.en-US.yaml` (name, publisher, description, license)

To publish a version, open a pull request on
[microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs) that adds
them under `manifests/o/OrcaRouter/Lite/<version>/`. Validate first on Windows:

```powershell
winget validate --manifest manifests\o\OrcaRouter\Lite\0.2.0
winget install --manifest manifests\o\OrcaRouter\Lite\0.2.0
```

`wingetcreate update OrcaRouter.Lite --version <v> --urls <setup .exe URL> --submit`
does the same for later versions once the first one is merged.

Ship it signed: winget-pkgs runs SmartScreen and antivirus checks on the
installer, and an unsigned one is likely to be held for manual review.
