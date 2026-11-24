# Security

OrcaRouter Lite sits between your tools and every model provider you use, so
it holds your provider keys. This page covers how to report a problem, how to
check that what you installed is what we built, and what the desktop app is
allowed to touch on your computer.

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/security/advisories/new)
rather than a public issue. Include the version (`orcarouter-lite --version`),
how you run it (desktop app, Docker, pip) and steps to reproduce.

We acknowledge reports within 3 working days and aim to ship a fix for
high-severity issues within 14 days. We credit reporters in the release notes
unless you ask us not to.

Only the latest release receives security fixes.

## Verifying a release

Every container image is built in GitHub Actions from a tagged commit, booted
against `/health` on each platform, and only then tagged. The release job then:

- signs the image digest with [cosign](https://docs.sigstore.dev/) using
  GitHub's OIDC identity (no long-lived signing key exists),
- attaches SLSA build provenance, and
- attaches an SPDX SBOM as an attestation.

Check the signature:

```bash
cosign verify ghcr.io/continuum-ai-corp/orcarouter-lite:latest \
  --certificate-identity-regexp '^https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/\.github/workflows/release\.yml@refs/tags/v' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Check the provenance and the SBOM:

```bash
gh attestation verify oci://ghcr.io/continuum-ai-corp/orcarouter-lite:latest \
  --repo Continuum-AI-Corp/OrcaRouter-Lite
```

PyPI releases are published with
[trusted publishing](https://docs.pypi.org/trusted-publishers/), so there is no
PyPI API token to leak, and PyPI shows the GitHub workflow that uploaded each
file.

Pin images by digest (`@sha256:…`) rather than by tag if you need a release
to never change under you.

## Dependencies

LiteLLM, our largest dependency, shipped backdoored releases on PyPI twice in
2026 (1.82.7 and 1.82.8 in March, 1.107.0 in October). So:

- `litellm` is pinned to an exact version in `pyproject.toml`, and a test fails
  if the pin is loosened or points at a known-compromised release.
- `requirements.lock` records a sha256 hash for every runtime dependency. The
  Docker image installs with `pip install --require-hashes`, so a re-uploaded
  or hijacked wheel fails the build instead of shipping.
- Dependency bumps are reviewed by a person; we read the upstream release
  before moving the pin, and regenerate the lockfile with the command at the
  top of `requirements.lock`.

## What the desktop app and `orca` CLI can touch

The desktop engine (`orca up`, started by the desktop app) is built for one
person on one computer:

- **Loopback only.** It listens on `127.0.0.1`; `orca up --host 0.0.0.0` is
  refused, and an engine started in desktop mode on any other host doesn't
  mount the desktop API at all.
- **Encryption key in the OS keychain.** Provider keys you save are encrypted
  (AES-256-GCM) with a key the engine keeps in the macOS Keychain, Windows
  Credential Manager or the Linux Secret Service. Where there's no keychain
  (headless Linux, or `ORCA_KEYCHAIN=0`) it's in
  `~/.orcarouter-lite/secrets.json` with mode 0600. A secrets file from an
  earlier version moves into the keychain and is deleted only after the
  keychain returns the same values. If the keychain later can't be read
  (locked, switched off, no desktop session), the engine refuses to start
  rather than create a new key that would orphan your saved keys.
- **Desktop API, desktop key.** The `/v1/app/*` endpoints that read and edit
  coding-agent settings exist only in desktop mode, and only the desktop app's
  own key (`~/.orcarouter-lite/app.key`, mode 0600) may call them. A server
  started with `orcarouter-lite` or Docker has no such endpoints.
- **Agent keys can only call models.** Each connected agent gets its own key.
  That key is accepted on the model endpoints (`/v1/chat/completions`,
  `/v1/messages`, `/v1/models`, `/v1beta/…`) and refused everywhere else, so a
  key read out of an agent's config can't mint keys, change providers, read
  spend or rewire other agents. Disconnecting revokes it.
- **No impostors on the port.** `orca up` writes a per-launch secret to
  `engine.json` (0600). Before sending its key anywhere, the app and the CLI
  challenge the listener at `/health/identity` and check an HMAC of that
  secret, so another program that grabs the port first gets nothing.
- **No third-party scripts.** In desktop mode the interactive API docs (which
  load from a CDN) are switched off, and the app injects its key only into its
  own pages under `/desktop/`. Those pages may call only the app's own native
  commands. No admin key is printed to the engine log.
- **Agent settings are edited, not replaced.** Connecting an agent changes only
  the settings it needs (for Claude Code, `env.ANTHROPIC_BASE_URL` and
  `env.ANTHROPIC_AUTH_TOKEN` in `~/.claude/settings.json`), writes through
  symlinks, and keeps the file's permissions and comments. The original file is
  backed up first in `~/.orcarouter-lite/agents/` (mode 0600, because it may
  contain earlier credentials). Disconnecting restores it, and keeps any change
  you made in the meantime.
- **Where each agent's key lives.** OpenCode, Kilo Code, Command Code and Goose
  read their key from a private file (`~/.orcarouter-lite/agents/keys/<agent>.key`,
  mode 0600), so it never appears in their config. Claude Code, Codex, Gemini
  CLI, Aider, Hermes Agent, Pi, OMP, OpenClaw and Kimi Code take the key inside
  their own config file, because that's the only place they read it from. That
  key can only call models (see above) and stops working when you disconnect.
  For the one-paste-step agents (Cline, Cursor, Zed, OpenHands, DeepSeek
  Harness, ZCode) nothing is written; you paste the key into the agent.
- **Keys are checked only with their own provider.** Before setup saves a
  provider key it asks that provider to list its models (no tokens spent),
  sending the key only to that provider's own API. Only the desktop app's key
  can run a check, so a key read out of an agent's config can't probe others.
- **Start at login.** On by default, so connected agents keep working after a
  restart. It adds one login item (a macOS LaunchAgent, a Windows `Run`
  registry entry, or `~/.config/autostart/OrcaRouter Lite.desktop` on Linux)
  that starts the app in the tray with `--background`; turning the setting off
  removes it.
- **Uninstalling restores your agents.** "Disconnect all" in the panel (or
  `orca disconnect --all`) restores every agent and revokes its key; the
  Windows uninstaller runs it itself (but not during an update).
- **Agents get an answer, not an error.** If a desktop agent asks for a model
  none of your keys covers, the engine serves it with the best model your keys
  do cover and names both in the `x-orca-requested-model` and
  `x-orca-resolved-model` headers. Dashboard and server keys keep strict
  pinned models.
- **Agent logos are bundled.** The app shows each agent's logo from files it
  ships with, loaded as images, so showing them never contacts anyone.
- **Team gateways only over https.** `orca login` and "Join my company's
  gateway" accept an https address, or plain http only to a loopback or
  private-network address, and check the key against the gateway before any
  agent setting changes. The team key is never shown back in the app.
- **The engine stops with the app.** The app holds a pipe to the engine; when
  the app exits for any reason, the engine exits too.
- **No telemetry.** Prompts and request logs stay in
  `~/.orcarouter-lite/orca.db` unless you configure a hosted provider, in which
  case requests go to that provider.
- **One update check a day.** The engine asks GitHub's API for this
  repository's latest release (`api.github.com/repos/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest`)
  with a generic user agent and nothing about you, and the app links only to
  this repository's release pages. The check itself downloads nothing. In
  releases built with the project's updater key, choosing "Install and
  restart" downloads the update and installs it only if its signature matches
  the public key built into the app; other builds just link to the download.
  Set `ORCA_NO_UPDATE_CHECK=1` to switch the check off.

Desktop installers are built in GitHub Actions from tagged commits. macOS
builds are signed and notarised when the project's Apple credentials are
configured; Windows and Linux installers are not signed yet.
