# Show HN draft

**Title** (80 characters max; the roadmap's "…and 17 other coding agents" is 83):

> Show HN: Orca – a menu-bar budget for Claude Code, Codex and 17 more agents

**URL:** https://github.com/Continuum-AI-Corp/OrcaRouter-Lite

**Text:**

Hi HN, I work on Orca (OrcaRouter Lite), a free, MIT-licensed menu-bar app for macOS, Windows and Linux
that shows what your coding agents spend and can stop them at a daily budget.

Coding agents make a lot of model calls, and the bill arrives per provider, not per agent. Orca runs a
small OpenAI-, Anthropic- and Gemini-compatible router on 127.0.0.1 and points each agent at it with its
own key, so spend splits by agent: Claude Code, Codex, Gemini CLI, OpenCode, Cline, Cursor, Aider, Goose,
Zed and ten more.

What it does:

- Today's spend in the menu bar, split by agent; a weekly summary on Monday.
- A daily budget: notifications at 80% and 100%, and an optional switch that pauses the agents at the limit.
- One-click connect: it edits each agent's own config, keeps a backup and restores it when you disconnect.
- Fallback: when a provider errors or rate-limits, the request goes to another provider your keys cover,
  and Orca counts the rescues.
- `orca status`, `orca report` and a Claude Code status line from the CLI.

Prompts go from your agents to the providers you configure; there's no telemetry, just a daily update
check. It uses your own provider keys. Disclosure: we also run OrcaRouter, a hosted gateway (one key for
every model, failover between providers, free models to start, pay per request for paid models). Orca can
use it, and setup offers it first, but it's optional and own keys are a full alternative.

The same engine runs as a self-hosted server for a team (Docker, SQLite by default).

Landing page with downloads: https://continuum-ai-corp.github.io/OrcaRouter-Lite/

I'd love feedback on which agents or providers are missing, and on how you budget agent spend today.

## Prepared answers

- **Why not just the provider dashboards?** They show spend per key or per project, not per agent, and
  they don't stop an agent mid-day.
- **Does it see my prompts?** They pass through the local router on your machine to the provider. The
  request log in a local SQLite file keeps metadata (model, tokens, cost, latency), not prompt text.
- **What happens to my agent config?** Orca backs up each file it edits and restores it on disconnect,
  including from the uninstaller. `orca disconnect --all` works without the app.
- **Subscriptions (Claude Pro/Max)?** While connected, Claude Code uses your provider keys instead of the
  subscription; setup says so before connecting.
- **How does it make money?** Lite stays MIT and free. Hosted OrcaRouter is a paid product for paid
  models and for organizations (SSO, fleet budgets).
