# OrcaRouter benchmark

_No published run yet._

The nightly job (`.github/workflows/benchmark.yml`) sends the prompts in
`bench/prompts.jsonl` to each model and ranks them by cost per answered
request. It needs provider keys (or an `ORCAROUTER_API_KEY`) as repository
secrets. Until those are configured, the job fails instead of publishing a
report, so this page stays empty rather than showing numbers nobody measured.

Reproduce locally against your own keys:

```bash
LITE_BASE_URL=http://localhost:8000 LITE_API_KEY=sk-orca-... \
MODELS=gpt-4o-mini,claude-3-5-haiku-latest \
python bench/run.py --prompts bench/prompts.jsonl --out BENCHMARK.md
```
