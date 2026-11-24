# Kimi Code: listing draft

Draft only; nothing has been submitted.

## Where

Kimi Code's provider examples page (the docs section that documents `[providers.*]` and `[models.*]` in `config.toml`).

## Pull request title

docs(providers): add an OrcaRouter Lite example

## Pull request description

Adds an OpenAI-type provider example for a local router.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; nothing is sent anywhere else.

The snippet below is exactly what `orca connect` writes (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app) and `packages/desktop/agents.py`), so readers can also set it up by hand. The key is a per-agent key Orca creates; `sk-orca-…` stands for it.

## Proposed addition

### OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) runs a router on
`127.0.0.1:8765`. `orca connect kimi-code` writes this to `~/.kimi-code/config.toml`:

```toml
default_model = "orca-auto"

[providers.orca]
type = "openai"
base_url = "http://127.0.0.1:8765/v1"
api_key = "sk-orca-…"

[models.orca-auto]
provider = "orca"
model = "auto"
max_context_size = 200000
capabilities = ["tool_use", "image_in"]
display_name = "Orca auto-routing"
```

Choose another model at any time with `/model`.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
