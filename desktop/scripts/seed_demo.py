"""Fill a desktop engine with DEMO data for screenshots and UI work.

Never point this at a real ~/.orcarouter-lite: it stores fake provider keys,
connects agents in the HOME the engine runs with, and writes a week of
made-up request logs. Use a throwaway folder:

    export HOME=/tmp/orca-demo ORCA_HOME=/tmp/orca-demo/.orcarouter-lite
    mkdir -p "$HOME/.claude"
    orca up --port 8799 &
    python desktop/scripts/seed_demo.py

It refuses to run if ORCA_HOME is the default folder in your real home.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(os.environ.get("ORCA_HOME", ""))


def _guard() -> None:
    real_default = Path(os.path.expanduser("~")) / ".orcarouter-lite"
    if not os.environ.get("ORCA_HOME") or "demo" not in str(HOME) and "tmp" not in str(HOME):
        sys.exit("Set ORCA_HOME to a throwaway folder (its path must contain 'demo' or 'tmp').")
    if HOME.resolve() == real_default.resolve() and "tmp" not in str(real_default):
        sys.exit("Refusing to seed demo data into your real ~/.orcarouter-lite.")


def _api(method: str, path: str, body: dict | None = None) -> dict:
    info = json.loads((HOME / "engine.json").read_text())
    key = (HOME / "app.key").read_text().strip()
    req = urllib.request.Request(
        info["base_url"] + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def main() -> None:
    _guard()
    _api("PUT", "/v1/providers/anthropic", {"api_key": "sk-ant-demo-" + "x" * 40})
    _api("PUT", "/v1/providers/openai", {"api_key": "sk-demo-" + "y" * 40})
    _api("PUT", "/v1/app/settings", {"daily_budget_cents": 2000})
    _api("POST", "/v1/app/agents/claude-code/connect")
    _api("POST", "/v1/app/agents/codex/connect")

    db = sqlite3.connect(HOME / "orca.db")
    keys = dict(db.execute("select name, id from api_keys where revoked_at is null"))
    agent_key = keys["agent:claude-code"]
    codex_key = keys["agent:codex"]
    direct_key = keys["default"]
    now = datetime.now(timezone.utc)
    rnd = random.Random(7)
    rows = []

    def add(when, key_id, model, provider, cost, fallback=0, status=200):
        rows.append((
            str(uuid.uuid4()), "default", key_id, str(uuid.uuid4()), "auto", model, provider, "balanced",
            fallback, rnd.randint(2_000, 9_000), rnd.randint(200, 1_200), cost, rnd.randint(300, 2_400),
            status, None, 0, when.strftime("%Y-%m-%d %H:%M:%S.%f"), 0,
        ))

    # Today: $2.60 from Claude Code, $0.85 from Codex, $0.60 from direct use, one rescued request.
    for cost in (900_000, 700_000, 600_000, 400_000):
        add(now - timedelta(minutes=rnd.randint(5, 300)), agent_key, "claude-sonnet-4-5", "anthropic", cost)
    add(now - timedelta(minutes=40), direct_key, "gpt-4o-mini", "openai", 600_000)
    add(now - timedelta(minutes=55), agent_key, "claude-sonnet-4-5", "orcarouter", 0, fallback=1)
    # Codex, through /v1/responses.
    for cost in (500_000, 350_000):
        add(now - timedelta(minutes=rnd.randint(5, 300)), codex_key, "gpt-5.1-codex", "openai", cost)
    # Earlier this week.
    for day in range(1, 6):
        for _ in range(3):
            add(now - timedelta(days=day, minutes=rnd.randint(0, 600)), agent_key, "claude-haiku-4-5", "anthropic",
                rnd.randint(150_000, 400_000))
    db.executemany(
        "insert into requests_log (id, workspace_id, api_key_id, trace_id, model_requested, model_resolved, provider,"
        " routing_strategy, fallback_level, input_tokens, output_tokens, cost_microcents, latency_ms, status_code,"
        " error_type, is_streaming, created_at, is_deleted) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    db.commit()
    print(f"Seeded {len(rows)} demo requests into {HOME / 'orca.db'}")


if __name__ == "__main__":
    main()
