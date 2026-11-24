# Zed: listing draft

Draft only; nothing has been submitted.

## Where

`zed-industries/zed`, `docs/src/ai/llm-providers.md`, in the OpenAI-compatible providers section.

## Pull request title

docs(llm-providers): add an OrcaRouter Lite example

## Pull request description

Adds an `openai_compatible` example for a local router. Zed keeps the key in the keychain, so the example only covers `settings.json` and the key variable.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; apart from those requests and a once-a-day update check, nothing leaves the computer.

Orca can't edit this agent's settings itself, so its setup shows a base URL and a per-agent key to paste; the steps below are the ones it shows (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app)). `sk-orca-…` stands for that key.

## Proposed addition

### OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) runs an OpenAI-compatible router on
`127.0.0.1:8765`. Add to `settings.json`:

```json
{
  "language_models": {
    "openai_compatible": {
      "Orca": {
        "api_url": "http://127.0.0.1:8765/v1",
        "available_models": [
          { "name": "auto", "display_name": "Orca auto-routing", "max_tokens": 200000 }
        ]
      }
    }
  }
}
```

Then paste the key Orca shows (`sk-orca-…`) in the Agent panel's Orca settings, or set `ORCA_API_KEY`
before starting Zed.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
