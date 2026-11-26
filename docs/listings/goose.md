# Goose: listing draft

Draft only; nothing has been submitted.

## Where

`block/goose`, the custom providers page of the docs (`documentation/docs/guides/config-files.md` or the "Custom providers" page, wherever `custom_providers/*.json` is documented).

## Pull request title

docs(custom-providers): add an OrcaRouter Lite example

## Pull request description

Adds a worked example of a custom OpenAI-engine provider whose key comes from a command, which the page doesn't show yet.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; apart from those requests and a once-a-day update check, nothing leaves the computer.

The snippet below is exactly what `orca connect` writes (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app) and `packages/desktop/agents.py`), so readers can also set it up by hand. The key is a per-agent key Orca creates; `sk-orca-…` stands for it.

## Proposed addition

### Example: OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) is a local router on
`127.0.0.1:8765`. `orca connect goose` writes `~/.config/goose/custom_providers/orca.json`:

```json
{
  "name": "orca",
  "engine": "openai",
  "display_name": "OrcaRouter Lite",
  "description": "Routes each request through OrcaRouter Lite on this computer.",
  "base_url": "http://127.0.0.1:8765/v1",
  "models": [{ "name": "auto", "context_limit": 200000 }],
  "supports_streaming": true,
  "requires_auth": true,
  "auth": { "command": "cat", "args": ["/Users/you/.orcarouter-lite/keys/goose.key"] },
  "dynamic_models": false
}
```

and selects it in `config.yaml`:

```yaml
GOOSE_PROVIDER: orca
GOOSE_MODEL: auto
```

The `auth` command prints the key, so it never sits in the config or the keychain. On Windows the
command is `cmd /d /c type <key file>`.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
