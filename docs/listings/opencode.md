# OpenCode: listing draft

Draft only; nothing has been submitted.

## Where

`sst/opencode`, the providers page of the docs site (`packages/web/src/content/docs/providers.mdx` at the time of writing), in the list of OpenAI-compatible providers.

## Pull request title

docs(providers): add OrcaRouter Lite

## Pull request description

Adds OrcaRouter Lite to the provider list as an `@ai-sdk/openai-compatible` entry.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; apart from those requests and a once-a-day update check, nothing leaves the computer.

The snippet below is exactly what `orca connect` writes (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app) and `packages/desktop/agents.py`), so readers can also set it up by hand. The key is a per-agent key Orca creates; `sk-orca-…` stands for it.

## Proposed addition

### OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) is a local router on
`127.0.0.1:8765` that tracks spend per agent and falls back between providers. `orca connect opencode`
writes this to `~/.config/opencode/opencode.json`; the key stays in a private file OpenCode reads:

```json
{
  "provider": {
    "orca": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "OrcaRouter Lite",
      "options": {
        "baseURL": "http://127.0.0.1:8765/v1",
        "apiKey": "{file:~/.orcarouter-lite/keys/opencode.key}"
      },
      "models": {
        "auto": { "name": "Orca auto-routing" }
      }
    }
  },
  "model": "orca/auto"
}
```

`auto` lets Orca pick a model per request; any model id your keys cover works too.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
