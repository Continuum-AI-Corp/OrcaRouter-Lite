"""Public benchmark runner.

Usage:
    python bench/run.py --prompts bench/prompts.jsonl --out BENCHMARK.md

Reads JSONL prompts, sends each to every configured model via the OrcaRouter
Lite API, records cost+latency, writes a Markdown report. Designed to run
against a freshly-booted lite server with the right provider keys in env.

Skipped automatically when the required env vars (LITE_BASE_URL,
LITE_API_KEY, MODELS) are missing — keeps CI happy on PRs that don't have
secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

from bench.report import render_markdown, should_publish, summarize


def _env_or_skip(*keys: str) -> dict[str, str] | None:
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        print(f"⊘ benchmark skipped — missing env: {missing}", file=sys.stderr)
        return None
    return {k: os.environ[k] for k in keys}


def _run_one(client: httpx.Client, *, model: str, prompt: str) -> dict:
    started = time.perf_counter()
    try:
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 256,
            },
            timeout=60.0,
        )
        r.raise_for_status()
        body = r.json()
    except Exception as exc:
        return {
            "model": model, "ok": False, "error": str(exc)[:120],
            "cost_usd": 0.0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "output_tokens": 0,
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = body.get("usage", {})
    # Cost lives on the response only when the lite server enriches it;
    # we don't trust it here. The pricing comes from the catalogue.
    from packages.litellm_adapter.catalog import CATALOG_BY_ID
    m = CATALOG_BY_ID.get(model)
    cost = 0.0
    if m:
        cost = (
            usage.get("prompt_tokens", 0) * m.input_cost_per_token
            + usage.get("completion_tokens", 0) * m.output_cost_per_token
        )
    return {
        "model": model,
        "ok": True,
        "cost_usd": cost,
        "latency_ms": latency_ms,
        "output_tokens": usage.get("completion_tokens", 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompts", default="bench/prompts.jsonl")
    parser.add_argument("--out", default="BENCHMARK.md")
    args = parser.parse_args()

    env = _env_or_skip("LITE_BASE_URL", "LITE_API_KEY", "MODELS")
    if env is None:
        return 0

    base_url = env["LITE_BASE_URL"].rstrip("/")
    api_key = env["LITE_API_KEY"]
    models = [m.strip() for m in env["MODELS"].split(",") if m.strip()]

    prompts_path = Path(args.prompts)
    if not prompts_path.exists():
        print(f"prompts file not found: {prompts_path}", file=sys.stderr)
        return 1
    prompts = [json.loads(line) for line in prompts_path.read_text().splitlines() if line.strip()]
    print(f"Running {len(prompts)} prompts × {len(models)} models = {len(prompts) * len(models)} requests")

    results: list[dict] = []
    with httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}) as client:
        for p in prompts:
            for model in models:
                row = _run_one(client, model=model, prompt=p["prompt"])
                results.append(row)
                marker = "✓" if row["ok"] else "✗"
                print(f"  {marker} {model:<40} ${row['cost_usd']:.5f}  {row['latency_ms']}ms")

    summary = summarize(results)
    publish, reason = should_publish(summary)
    if not publish:
        # Fail the job loudly instead of committing a report of failures.
        print(f"\n✗ not writing {args.out}: {reason}", file=sys.stderr)
        return 1
    md = render_markdown(summary, total_prompts=len(prompts))
    Path(args.out).write_text(md)
    print(f"\n✓ wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
