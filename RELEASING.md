# Releasing

OrcaRouter Lite ships these artifacts. `.github/workflows/release.yml` and
`.github/workflows/desktop.yml` publish the automatable ones; the Railway
template and the Homebrew tap need accounts outside this repo. This file covers
the one-time setup each one needs and the steps to cut a release.

| Artifact | Where | Published by |
|---|---|---|
| Container image | `ghcr.io/continuum-ai-corp/orcarouter-lite` | `release.yml` — `image` job (cosign-signed, SBOM + provenance) |
| Python package | [pypi.org/p/orcarouter-lite](https://pypi.org/p/orcarouter-lite) | `release.yml` — `pypi` job |
| Desktop installers (`.dmg`, `.deb`, `.AppImage`, `.msi`, `.exe`) | GitHub release | `desktop.yml` — `bundle` job |
| Homebrew cask | GitHub release asset `orcarouter-lite.rb`, copied to the tap | `desktop.yml` — `homebrew-cask` job, then manual copy |
| Homebrew formula (CLI only) | GitHub release asset `orcarouter-lite-formula.rb`, copied to the tap | `release.yml` — `pypi` job, then manual copy |
| winget manifests | GitHub release assets `OrcaRouter.Lite*.yaml`, submitted to `microsoft/winget-pkgs` | `desktop.yml` — `winget-manifest` job, then a manual pull request |
| Landing page | <https://continuum-ai-corp.github.io/OrcaRouter-Lite/> | `pages.yml` on pushes to `site/` |
| Railway template | [railway.com](https://railway.com) marketplace | manual, see below |

Pull requests that touch `desktop/` build every installer unsigned, as
workflow artifacts, so a release never ships a platform that wasn't built.

---

## One-time setup

### 1. PyPI — trusted publishing

The `pypi` job authenticates over OIDC, so there is no API token to store or
rotate. It will fail until PyPI knows about this repo.

At <https://pypi.org/manage/account/publishing/>, add a **pending publisher**:

| Field | Value |
|---|---|
| PyPI project name | `orcarouter-lite` |
| Owner | `Continuum-AI-Corp` |
| Repository name | `OrcaRouter-Lite` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

The environment name has to match the `environment: name: pypi` block in the
workflow. GitHub creates that environment on the first run; add reviewers to it
under **Settings → Environments** if releases should need approval.

`orcarouter-lite` was unclaimed on PyPI as of the last check — confirm it still
is before the first publish, because the name cannot be changed afterwards
without renaming the distribution.

### 2. GHCR — package visibility and repo link

The first push creates the package as **private**, owned by the org. Make it
public once:

**github.com/orgs/Continuum-AI-Corp/packages → orcarouter-lite → Package
settings → Change visibility → Public.**

While there, under **Manage Actions access**, confirm the `OrcaRouter-Lite`
repository has `Write` — that is what lets `GITHUB_TOKEN` push on later runs.
The `org.opencontainers.image.source` label in the Dockerfile is what links the
package back to this repo on the GHCR page.

No secrets are needed: the job uses the built-in `GITHUB_TOKEN` with
`packages: write`.

### 3. Railway — publish the template

Not wired up yet, and the button the READMEs carry today is broken: it points at
`https://railway.app/new/template`, a URL with no template behind it, so it
lands the visitor on the generic marketplace page and deploys nothing. Railway
serves a real one-click deploy only for a published **template code**
(`https://railway.com/new/template/<code>`); the legacy `?template=<github-url>`
form no longer resolves either.

Codes cannot be minted from a repo URL — Railway's `templateGenerate` snapshots
an existing project, so the project has to be deployed by hand once:

1. **railway.com -> New Project -> Deploy from GitHub repo -> OrcaRouter-Lite.**
   `railway.json` already supplies the Dockerfile build, the `/health` check and
   the restart policy.
2. Add a **Volume** mounted at `/data` and set
   `DATABASE_URL=sqlite+aiosqlite:////data/orca.db`, plus
   `CREDENTIAL_ENCRYPTION_KEY` and `API_KEY_PEPPER` (`openssl rand -hex 32`).
   Without the volume every redeploy wipes provider keys, API keys and
   analytics — and whatever this project looks like is exactly what one-click
   deployers get, volume included.
3. **project -> ... -> Create Template from Project**, then publish. Railway
   returns a code, e.g. `ZweBXA`.
4. Replace the Railway cell in all twelve `README*.md` files with:

   ```md
   | Railway | [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template/YOURCODE?utm_medium=integration&utm_source=button&utm_campaign=orcarouter-lite) |
   ```

Steps 3 and 4 are scriptable against Railway's public API (`templateGenerate` +
`templatePublish` both accept an account token); that tooling is not part of
this change.

### 4. macOS signing and notarisation

Without these the `.dmg` is built unsigned and Gatekeeper warns on first open.
Add repository secrets (Settings → Secrets and variables → Actions):

| Secret | What it is |
|---|---|
| `APPLE_CERTIFICATE` | base64 of the "Developer ID Application" certificate exported as `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | the `.p12` export password |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: Continuum AI Corp (TEAMID)` |
| `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` | notarisation: Apple ID, an app-specific password, the team ID |

The workflow exports them only when set, so forks keep building unsigned.
`desktop/src-tauri/Entitlements.plist` carries the hardened-runtime exceptions
the bundled Python engine needs.

### 5. Homebrew tap

Create `Continuum-AI-Corp/homebrew-tap` once. After each release, copy the
`orcarouter-lite.rb` asset into `Casks/` there and the
`orcarouter-lite-formula.rb` asset to `Formula/orcarouter-lite.rb`. Users then
install the app with `brew install --cask continuum-ai-corp/tap/orcarouter-lite`
and the CLI alone with `brew install continuum-ai-corp/tap/orcarouter-lite`.
The formula installs the sdist from PyPI, so publish to PyPI first.

### 5b. winget

After each release, submit the three `OrcaRouter.Lite*.yaml` assets to
`microsoft/winget-pkgs`; see [packaging/winget/README.md](packaging/winget/README.md).

### 5c. Landing page

Settings → Pages → Build and deployment → Source: **GitHub Actions**, once.
`pages.yml` then publishes `site/` on every push to `main` that touches it.

### 6. Benchmark secrets

`benchmark.yml` needs provider keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GOOGLE_API_KEY`, `GROQ_API_KEY`) or one `ORCAROUTER_API_KEY`. Without them the
nightly job fails instead of publishing a report of failures.

### 7. Windows code signing

Without a certificate the `.msi` and `.exe` are built unsigned and SmartScreen
warns on first run. Add repository secrets:

| Secret | What it is |
|---|---|
| `WINDOWS_CERTIFICATE` | base64 of the code-signing certificate exported as `.pfx` |
| `WINDOWS_CERTIFICATE_PASSWORD` | the `.pfx` export password |

The Windows job imports it, signs both installers with SHA-256 and a DigiCert
timestamp, and checks each file carries a signature. Pull requests sign with a
throwaway self-signed certificate so that path stays tested.

### 8. In-app updates

Released apps announce new versions either way. To have them **install**
updates in place (download, verify the signature, restart), create the
updater's signing key once, on a trusted machine:

```bash
cd desktop && npx tauri signer generate -w ~/.tauri/orcarouter-lite.key
```

Then add the private key as the secret `TAURI_SIGNING_PRIVATE_KEY` (the file's
contents), its password as `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, and the
contents of the `.pub` file as the repository **variable**
`TAURI_UPDATER_PUBKEY`. Tagged releases then build the public key into the
app, sign each platform's update, and attach `latest.json`; the app fetches it
from `releases/latest/download/latest.json` and refuses anything not signed by
that key. Keep the private key backed up: losing it means shipped apps can't
take updates until users reinstall. Pull requests sign with a throwaway key so
the updater build stays tested.

---

## Cutting a release

Bump the version in all four places first (a test fails if they disagree):
`pyproject.toml`, `desktop/src-tauri/tauri.conf.json`,
`desktop/src-tauri/Cargo.toml` and `desktop/package.json`.

1. Bump `version` in `pyproject.toml`. The `pypi` job refuses to publish if it
   does not match the tag, so this is the only place the number lives.
2. Merge to `main`. That publishes `ghcr.io/…:edge` (amd64) — a good check that
   the image job is healthy before you tag.
3. Tag and push:

   ```bash
   git tag -a v0.1.1 -m "v0.1.1"
   git push origin v0.1.1
   ```

That produces:

- `ghcr.io/continuum-ai-corp/orcarouter-lite:latest`, `:0.1.1`, `:0.1`,
  `:sha-<short>` — linux/amd64 + linux/arm64, with a provenance attestation
  (`gh attestation verify oci://… --repo Continuum-AI-Corp/OrcaRouter-Lite`)
- `orcarouter-lite 0.1.1` on PyPI (wheel + sdist)
- both dists attached to the GitHub release

Before publishing, the `pypi` job installs the wheel into a clean venv, boots
it, and fails the release if `/health` or the dashboard at `/` does not answer.
The `image` job runs the same smoke test against the pushed image.

### What gates what

Nothing a consumer can pull is published before it has been executed, and the
whole run is safe to re-run:

- The build pushes **only** `:sha-<short>` — immutable and unadvertised. Every
  platform in that digest is then booted against `/health` (arm64 under qemu,
  with a longer timeout), and only after that does a `promote` step move
  `latest`/`X.Y.Z`/`X.Y`/`edge` onto the same digest with
  `docker buildx imagetools create`. A failed smoke leaves the old `latest`
  untouched. The provenance attestation is then made against the digest those
  tags actually resolve to — read back, not assumed — so
  `gh attestation verify oci://…:latest` verifies the image people pull.
- All tag releases share one concurrency group, so two versions tagged close
  together cannot both write `latest` and leave it pointing at the older one.
- `pypi` `needs: image`, so a container that never booted stops the PyPI
  release too — the two artifacts for a version ship together or not at all.
- Inside `pypi`, the GitHub release is created and the dists attached **before**
  the PyPI upload. That is the retryable order: a published PyPI version can
  never be replaced, so if the upload came first, a failure afterwards would be
  unrecoverable by re-run. `skip-existing: true` lets a re-run pass through a
  version that already landed.

### The already-tagged v0.1.0

`v0.1.0` was tagged before this workflow existed, and it cannot be released
as-is. `workflow_dispatch` runs the workflow file *from the ref you select*, and
that tag carries only `ci.yml` and `benchmark.yml` — there is no `release.yml`
at `v0.1.0` for the dispatch to run.

Cut `v0.1.1` instead. (Force-moving the `v0.1.0` tag onto a commit that has the
workflow would also work — nothing has consumed that tag yet — but re-pointing a
published tag is not a habit worth starting.)

### Rehearsing on a fork

The `image` job pushes to `ghcr.io/<whatever repo it runs in>`, so a fork can
exercise the whole thing against its own namespace with no secrets: enable
Actions on the fork, then either open a pull request (runs `ci.yml`, which
builds the image and boots it without pushing) or push to the fork's `main`
(runs `release.yml`, which publishes `:edge`). The `pypi` job is scoped to
`Continuum-AI-Corp`, so it skips on forks rather than failing at the OIDC
exchange.

Note that the **Run workflow** button only appears for workflows that exist on
the repository's default branch — until `release.yml` is merged to `main`, there
is nothing to dispatch.

## Local checks

CI's `package` job runs these on every PR, but to reproduce it:

```bash
python -m build
twine check --strict dist/*

python -m venv /tmp/verify
/tmp/verify/bin/pip install dist/*.whl
/tmp/verify/bin/orcarouter-lite --port 8123 &
curl -sf localhost:8123/health          # {"status":"ok"}
curl -sf localhost:8123/ | head -1      # <!DOCTYPE html> — dashboard came along
```

The last line is the one that matters: `design/` lives at the repo root but is
force-included into the wheel as `app/design/` (see the comment above
`[tool.hatch.build.targets.wheel]` in `pyproject.toml`). If that mapping is
dropped, everything still builds and boots — only the UI silently disappears.
