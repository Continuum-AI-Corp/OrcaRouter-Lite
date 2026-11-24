# Agents' own config schemas

Used by `tests/unit/test_agent_config_schemas.py` to check that what Orca
writes into each agent's config is valid by that agent's own schema. Fetched
on 2026-11-24; refresh them when an agent changes its config format.

| File | Source | Licence |
|---|---|---|
| `claude-code-settings.schema.json` | [SchemaStore `claude-code-settings.json`](https://json.schemastore.org/claude-code-settings.json) | Apache-2.0 |
| `gemini-cli-settings.schema.json` | [google-gemini/gemini-cli `schemas/settings.schema.json`](https://github.com/google-gemini/gemini-cli/blob/main/schemas/settings.schema.json) | Apache-2.0 |
| `codex-config.schema.json` | [openai/codex `codex-rs/core/config.schema.json`](https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json) | Apache-2.0 |
| `pi-models.schema.json`, `pi-settings.schema.json` | [badlogic/pi-mono `packages/coding-agent/schemas`](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/schemas) | MIT |
