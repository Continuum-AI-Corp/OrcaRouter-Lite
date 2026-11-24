# Claude Code: listing draft

Draft only; nothing has been submitted.

## Where

Claude Code's **LLM gateway** documentation page (the one with the LiteLLM example). Claude Code's docs aren't in a public repository; submit through the docs page's feedback link or an issue on `anthropics/claude-code` with the text below.

## Pull request title

docs(llm-gateway): add OrcaRouter Lite as a local gateway example

## Pull request description

Adds a short example next to the existing gateway examples, for people who want a gateway on their own computer rather than a shared server.

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) ("Orca") is an MIT-licensed menu-bar app and CLI that runs an OpenAI-, Anthropic- and Gemini-compatible router on `127.0.0.1:8765`. It tracks spend per coding agent, can stop agents at a daily budget, and falls back to another provider when one fails. It works with the user's own provider keys or with a hosted gateway; apart from those requests and a once-a-day update check, nothing leaves the computer.

The snippet below is exactly what `orca connect` writes (see the agent table in the [README](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite#the-desktop-app) and `packages/desktop/agents.py`), so readers can also set it up by hand. The key is a per-agent key Orca creates; `sk-orca-…` stands for it.

## Proposed addition

### OrcaRouter Lite

[OrcaRouter Lite](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite) runs a gateway on your computer
(`127.0.0.1:8765`) that speaks the Anthropic Messages API and routes to the provider keys you add. It shows
spend per agent and can stop at a daily budget. `orca connect claude-code` sets this up; by hand, add to
`~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8765",
    "ANTHROPIC_AUTH_TOKEN": "sk-orca-…"
  }
}
```

No `/v1` suffix: Claude Code appends `/v1/messages` itself.

## Before submitting

- Check the target file still exists at that path and follow the repo's contributing guide (sign-off, changelog, docs build).
- Submit only after the first signed release is live, so the install link works.
- Keep it to one short section; drop the "Spend per agent" sentence if the maintainers prefer pure configuration docs.
- Don't open the pull request from this repo's automation; a maintainer submits it by hand.
