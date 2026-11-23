"""Aggregation + markdown rendering for the public benchmark."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone


def summarize(results: list[dict]) -> list[dict]:
    """Group raw per-request rows into per-model summaries."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        groups[r["model"]].append(r)

    out: list[dict] = []
    for model, rows in groups.items():
        successes = [r for r in rows if r.get("ok")]
        success_rate = len(successes) / len(rows) if rows else 0.0
        total_cost = sum(r["cost_usd"] for r in successes)
        avg_latency = (
            sum(r["latency_ms"] for r in successes) / len(successes)
            if successes else 0
        )
        out.append({
            "model": model,
            "request_count": len(rows),
            "total_cost_usd": total_cost,
            "avg_latency_ms": int(avg_latency),
            "success_rate": success_rate,
        })
    return out


def should_publish(summary: list[dict]) -> tuple[bool, str]:
    """A report is only worth committing if at least one model answered.

    The nightly job once ran without provider keys, every request failed, and
    it committed a table of 0% success rows under a "~0% saved" headline.
    """
    if not any(r["success_rate"] > 0 for r in summary):
        return False, (
            "no model answered: check the provider keys (or ORCAROUTER_API_KEY) "
            "the benchmark job runs with"
        )
    return True, ""


def _cost_per_answer(row: dict) -> float:
    answered = row["request_count"] * row["success_rate"]
    return row["total_cost_usd"] / answered if answered else 0.0


def render_markdown(summary: list[dict], *, total_prompts: int) -> str:
    """Public-facing benchmark report, ranked by cost per answered request.

    Models that never answered are listed separately and never used for the
    savings headline; with fewer than two answering models there is nothing
    to compare, so no savings claim is made.
    """
    if not summary:
        return "# OrcaRouter benchmark\n\n_no benchmark results yet._\n"

    answered = sorted((r for r in summary if r["success_rate"] > 0), key=_cost_per_answer)
    silent = [r for r in summary if r["success_rate"] == 0]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# OrcaRouter benchmark",
        "",
        f"_{total_prompts} prompts × {len(summary)} models · last run {now}_",
        "",
    ]
    if len(answered) >= 2:
        cheapest, priciest = answered[0], answered[-1]
        top = _cost_per_answer(priciest)
        pct = round(100 * (top - _cost_per_answer(cheapest)) / top) if top > 0 else 0
        lines.append(
            f"**TL;DR**: per answered request, the cheapest capable model cost **~{pct}%** "
            f"less than the most expensive (`{priciest['model']}` → `{cheapest['model']}`)"
        )
    elif len(answered) == 1:
        lines.append("**TL;DR**: Only one model answered, so there is nothing to compare this run.")
    else:
        lines.append("**TL;DR**: No model answered this run.")
    lines += [
        "",
        "| Model | Requests | Total cost | Cost per answer | Avg latency | Success |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in answered:
        lines.append(
            f"| `{row['model']}` "
            f"| {row['request_count']} "
            f"| ${row['total_cost_usd']:.2f} "
            f"| ${_cost_per_answer(row):.5f} "
            f"| {row['avg_latency_ms']} ms "
            f"| {row['success_rate'] * 100:.0f}% |"
        )
    if silent:
        names = ", ".join(f"`{r['model']}`" for r in silent)
        lines += ["", f"Did not answer this run: {names}."]
    lines.extend([
        "",
        "_Run nightly via GitHub Actions; see `.github/workflows/benchmark.yml`._",
        "_Reproduce: `python bench/run.py --prompts bench/prompts.jsonl`_",
        "",
    ])
    return "\n".join(lines)
