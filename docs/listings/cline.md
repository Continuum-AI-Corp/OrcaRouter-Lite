# Cline: listing draft

Draft only; nothing has been submitted.

## Where

`cline/cline`, `docs/provider-config/openai-compatible.mdx`, as an example under the OpenAI Compatible provider.

## Pull request title

docs(openai-compatible): add an OrcaRouter Lite example

## Pull request description

Adds a local-router example to the OpenAI Compatible provider page.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; nothing is sent anywhere else.

Orca can't edit this agent's settings itself, so its setup shows a base URL and a per-agent key to paste; the steps below are the ones it shows (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app)). `sk-orca-…` stands for that key.

## Proposed addition

### Example: OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) runs an OpenAI-compatible router on
`127.0.0.1:8765`. In Cline's settings choose **API Provider → OpenAI Compatible** and enter:

```text
Base URL: http://127.0.0.1:8765/v1
API Key:  sk-orca-…   (the key Orca shows for Cline)
Model ID: auto
```

`auto` lets Orca pick a model per request; any model id your provider keys cover works as well.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
