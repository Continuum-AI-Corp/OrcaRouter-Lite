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

- It listens on `127.0.0.1` only. `orca up --host 0.0.0.0` is refused.
- The `/v1/app/*` endpoints that read and edit coding-agent settings exist
  only in desktop mode. A server started with `orcarouter-lite` or Docker does
  not have them.
- They need the desktop app's own key, which is stored in
  `~/.orcarouter-lite/app.key` with mode 0600. Agent keys and keys limited by a
  model allowlist or a budget are refused.
- Connecting an agent edits only the settings it needs (for Claude Code,
  `env.ANTHROPIC_BASE_URL` and `env.ANTHROPIC_AUTH_TOKEN` in
  `~/.claude/settings.json`). The original file is backed up first in
  `~/.orcarouter-lite/agents/` (mode 0600, because it may contain earlier
  credentials). Disconnecting restores it, and keeps any change you made in
  the meantime.
- Each connected agent gets its own key. Disconnecting revokes it.
- The app sends no telemetry. Prompts and request logs stay in
  `~/.orcarouter-lite/orca.db` unless you configure a hosted provider, in
  which case requests go to that provider.
