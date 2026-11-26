# Product Hunt draft

**Name:** OrcaRouter Lite

**Tagline** (60 characters max):

> Put a budget on every coding agent

**Website:** https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-share

**Topics:** Developer Tools, Artificial Intelligence, Open Source, Mac

**Pricing:** Free (MIT, open source)

**Description** (260 characters max):

> A free menu-bar app that shows what Claude Code, Codex, Gemini CLI and 16 more coding agents spend,
> split by agent, and stops them at a daily budget. Falls back to another provider when one fails.
> Your keys, your machine, no telemetry.

## Gallery

1. `demo.gif`: the 30-second storyboard (install, connect, spend, alert).
2. The menu-bar panel, light (`docs/screenshots/desktop-panel.png`).
3. The menu-bar panel, dark (`docs/screenshots/desktop-panel-dark.png`).
4. First-run setup (`docs/screenshots/desktop-setup.png`).
5. The savings card (V2), if it has shipped: "This week, across Claude Code and Codex, Orca saved me …",
   with example numbers marked as such.
6. The landing page's logo strip ("Works with" 19 agents).

## Maker's first comment

Hi Product Hunt! Coding agents bill per provider, so it's hard to tell which agent spent what, or to stop
one before the bill surprises you. Orca runs a small router on your computer, gives each agent its own
key, and shows today's spend per agent in the menu bar. Set a daily budget and get notified at 80% and
100%, or have Orca pause the agents at the limit.

It connects 19 agents (Claude Code, Codex, Gemini CLI, OpenCode, Cursor, Cline, Aider, Goose, Zed…),
backs up their settings and restores them when you disconnect. When a provider fails, requests fall back
to another one.

It works with your own provider keys. If you'd rather have one key for every model, OrcaRouter's hosted
gateway is built in: free models to start, failover between providers, and pay per request for paid
models, only when you choose them. Full disclosure: we make both.

MIT licensed, no telemetry. Feedback on missing agents and providers is very welcome.

## Notes

- Schedule for 12:01 a.m. Pacific on the release day; link the release notes in the first comment's replies.
- Use the `?ref=lite-share` link everywhere on Product Hunt so visits from it can be told apart. Never add a
  personal or user identifier.
