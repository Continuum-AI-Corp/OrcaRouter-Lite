# Cursor: listing draft

Draft only; nothing has been submitted.

## Where

Cursor's docs aren't in a public repository. Post the text below on the Cursor forum's "OpenAI-compatible / custom API" thread or send it through the docs feedback link for the Models page.

## Pull request title

Using a local OpenAI-compatible router (OrcaRouter Lite) with Cursor

## Pull request description

A short how-to for the existing "Override OpenAI Base URL" setting with a local router.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; apart from those requests and a once-a-day update check, nothing leaves the computer.

Orca can't edit this agent's settings itself, so its setup shows a base URL and a per-agent key to paste; the steps below are the ones it shows (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app)). `sk-orca-…` stands for that key.

## Proposed addition

### OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) runs an OpenAI-compatible router on
`127.0.0.1:8765`. In Cursor:

1. **Settings → Models**, open the OpenAI API key section.
2. Turn on **Override OpenAI Base URL** and enter `http://127.0.0.1:8765/v1`.
3. Paste the key Orca shows for Cursor (`sk-orca-…`) as the OpenAI API key.
4. Add a custom model named `auto` and select it.

```text
Base URL: http://127.0.0.1:8765/v1
API key:  sk-orca-…
Model:    auto
```

Some Cursor features run on Cursor's own servers and can't reach `127.0.0.1`; those keep using Cursor's models.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
