"""Spend reports, as Markdown to paste or CSV to save (`orca report`, H7).

Two shapes share the formatting here:

- `from_summary`: what `orca report` has always printed (today and the last
  seven days, by agent), built from `GET /v1/app/summary`;
- `weekly`: one Monday-to-Sunday week by agent and by model, for a manager
  (`GET /v1/app/report`, the panel's Team card).

Totals only: agents, models, providers, tokens and money. Never prompts.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

MODEL_NAMES = {"gpt-4o": "GPT-4o"}


def money(microcents: int) -> str:
    dollars = (Decimal(max(0, int(microcents))) / Decimal(1_000_000)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${dollars:,.2f}"


def _plain(microcents: int) -> str:
    """Dollars for a CSV cell: 1234.50, no symbol or separators."""
    return money(microcents)[1:].replace(",", "")


def _rescued_line(n: int) -> str:
    return f"{n} failed {'request was' if n == 1 else 'requests were'} retried on another provider."


# ── `orca report` (today and the last 7 days) ───────────────────────────


def from_summary(s: dict, fmt: str) -> str:
    agents = s.get("agents") or []
    if fmt == "csv":
        rows = ["agent,today_usd,last_7_days_usd,requests_last_7_days"]
        for a in agents:
            name = a["name"].replace(",", " ")
            rows.append(f"{name},{_plain(a['today_microcents'])},{_plain(a['week_microcents'])},"
                        f"{a.get('requests_week', 0)}")
        return "\n".join(rows) + "\n"
    week = s["week"]
    lines = [
        "# Coding-agent spend",
        "",
        f"Today: {money(s['today']['spend_microcents'])} · Last 7 days: {money(week['spend_microcents'])}",
    ]
    if week.get("saved_microcents", 0) > 0:
        vs = MODEL_NAMES.get(week["baseline_model"], week["baseline_model"])
        lines.append(f"Saved {money(week['saved_microcents'])} vs {vs} by routing simple calls to cheaper models.")
    n = week.get("failures_avoided") or 0
    if n:
        lines.append(_rescued_line(n))
    lines += ["", "| Agent | Today | Last 7 days | Requests (7 days) |", "|---|---:|---:|---:|"]
    for a in agents:
        lines.append(f"| {a['name']} | {money(a['today_microcents'])} | {money(a['week_microcents'])} | "
                     f"{a.get('requests_week', 0)} |")
    lines += ["", "_From OrcaRouter Lite (`orca report`)._"]
    return "\n".join(lines) + "\n"


# ── one week, by agent and model ────────────────────────────────────────


@dataclass
class Line:
    agent: str
    model: str
    provider: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    spend: int = 0
    rescued: int = 0


@dataclass
class Week:
    start: date
    lines: list[Line] = field(default_factory=list)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=6)


def build_week(start: date, rows: Iterable, agent_name) -> Week:
    """Group successful log rows (provider, model_resolved, tokens, cost,
    fallback_level, api_key_id) by agent and model. `agent_name(api_key_id)`
    names the agent behind a key."""
    by: dict[tuple[str, str, str], Line] = {}
    for r in rows:
        agent = agent_name(r.api_key_id)
        key = (agent, r.model_resolved, r.provider)
        line = by.setdefault(key, Line(agent, r.model_resolved, r.provider))
        line.requests += 1
        line.input_tokens += r.input_tokens or 0
        line.output_tokens += r.output_tokens or 0
        line.spend += int(r.cost_microcents or 0)
        line.rescued += 1 if (r.fallback_level or 0) > 0 else 0
    lines = sorted(by.values(), key=lambda x: (x.agent == "Other apps", x.agent, -x.spend, x.model))
    return Week(start, lines)


def filename(week: Week, fmt: str) -> str:
    return f"orca-week-{week.start.isoformat()}.{'csv' if fmt == 'csv' else 'md'}"


def weekly(week: Week, fmt: str) -> str:
    if fmt == "csv":
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["week_start", "agent", "model", "provider", "requests", "input_tokens", "output_tokens",
                    "spend_usd"])
        for x in week.lines:
            w.writerow([week.start.isoformat(), x.agent, x.model, x.provider, x.requests, x.input_tokens,
                        x.output_tokens, _plain(x.spend)])
        return out.getvalue()

    def _fmt_day(d: date) -> str:
        return f"{d.strftime('%b')} {d.day}"

    total = sum(x.spend for x in week.lines)
    count = sum(x.requests for x in week.lines)
    rescued = sum(x.rescued for x in week.lines)
    lines = [
        "# Coding-agent spend",
        "",
        f"Week of {_fmt_day(week.start)} to {_fmt_day(week.end)}, {week.end.year} (Monday to Sunday)",
        "",
        f"Total: {money(total)} across {count} request{'s' if count != 1 else ''}",
    ]
    if rescued:
        lines.append(_rescued_line(rescued))
    agents: dict[str, list[int]] = {}
    models: dict[tuple[str, str], list[int]] = {}
    for x in week.lines:
        a = agents.setdefault(x.agent, [0, 0])
        a[0] += x.spend
        a[1] += x.requests
        m = models.setdefault((x.model, x.provider), [0, 0])
        m[0] += x.spend
        m[1] += x.requests
    lines += ["", "## By agent", "", "| Agent | Spend | Requests |", "|---|---:|---:|"]
    for name, (spend, n) in sorted(agents.items(), key=lambda kv: (kv[0] == "Other apps", -kv[1][0])):
        lines.append(f"| {name} | {money(spend)} | {n} |")
    lines += ["", "## By model", "", "| Model | Provider | Spend | Requests |", "|---|---|---:|---:|"]
    for (model, provider), (spend, n) in sorted(models.items(), key=lambda kv: -kv[1][0]):
        lines.append(f"| {model} | {provider} | {money(spend)} | {n} |")
    lines += ["", "_From OrcaRouter Lite._"]
    return "\n".join(lines) + "\n"
