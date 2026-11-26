"""What Orca writes into an agent's config passes that agent's own schema.

The schemas are the agents' published ones (tests/fixtures/agent_schemas).
Each case connects the agent over a config the user already had, so the
merged file is checked, not just Orca's part of it.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import jsonschema
import pytest

from packages.desktop import agents as ag

SCHEMAS = Path(__file__).resolve().parents[1] / "fixtures" / "agent_schemas"
BASE = "http://127.0.0.1:8765"
KEY = "sk-orca-0123456789abcdef0123456789abcdef"

CASES = [
    ("claude-code", ".claude/settings.json", "claude-code-settings", '{"theme": "dark", "permissions": {"allow": ["Bash(ls:*)"]}}'),
    ("gemini-cli", ".gemini/settings.json", "gemini-cli-settings", '{"ui": {"theme": "GitHub"}}'),
    ("codex", ".codex/config.toml", "codex-config", 'model = "gpt-5.1-codex"\n\n[projects."/home/me/app"]\ntrust_level = "trusted"\n'),
    ("pi", ".pi/agent/models.json", "pi-models", '{"providers": {"ollama": {"baseUrl": "http://localhost:11434/v1", "api": "openai-completions", "models": [{"id": "qwen3"}]}}}'),
    ("pi", ".pi/agent/settings.json", "pi-settings", '{"theme": "dark"}'),
]


def _load(path: Path):
    return tomllib.loads(path.read_text()) if path.suffix == ".toml" else json.loads(path.read_text())


@pytest.mark.parametrize("agent_id, rel, schema, existing", CASES, ids=[f"{c[0]}:{c[1]}" for c in CASES])
def test_the_written_config_is_valid_for_the_agent(tmp_path, agent_id, rel, schema, existing):
    home, state = tmp_path / "home", tmp_path / "state"
    (home / rel).parent.mkdir(parents=True)
    (home / rel).write_text(existing)
    ag.connect_agent(agent_id, home=home, state_dir=state, base_url=BASE, api_key=KEY)
    spec = json.loads((SCHEMAS / f"{schema}.schema.json").read_text())
    validator = jsonschema.validators.validator_for(spec)(spec)
    errors = [f"{list(e.path)}: {e.message[:200]}" for e in validator.iter_errors(_load(home / rel))]
    assert errors == []
