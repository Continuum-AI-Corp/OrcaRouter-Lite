# Hermes Agent: listing draft

Draft only; nothing has been submitted.

## Where

`NousResearch/hermes-agent`, the custom provider section of the configuration docs.

## Pull request title

docs(providers): add an OrcaRouter Lite custom provider example

## Pull request description

Adds a custom provider example pointing Hermes at a local OpenAI-compatible router.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; nothing is sent anywhere else.

The snippet below is exactly what `orca connect` writes (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app) and `packages/desktop/agents.py`), so readers can also set it up by hand. The key is a per-agent key Orca creates; `sk-orca-…` stands for it.

## Proposed addition

### OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) runs a router on
`127.0.0.1:8765`. `orca connect hermes` adds this to `~/.hermes/config.yaml`
(Windows: `%LOCALAPPDATA%\hermes\config.yaml`):

```yaml
providers:
  orca:
    api: http://127.0.0.1:8765/v1
    api_key: sk-orca-…
    transport: chat_completions
    default_model: auto
model:
  provider: custom:orca
  default: auto
  base_url: http://127.0.0.1:8765/v1
```

`model.base_url` is set too, because one left by another provider would otherwise win.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
