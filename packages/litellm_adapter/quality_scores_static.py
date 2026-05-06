"""Static quality + latency baseline for routing strategies.

Covers both LiteLLM catalog models (hyphenated IDs) and O2-hosted models
(dotted IDs where no LiteLLM hyphenated equivalent exists). Serves as the
floor for routing decisions:

  - Pairs with dynamic Artificial Analysis fetch in quality_index.py.
  - AA data always wins on overlap (static = fallback, not override).
  - Models not in AA's dataset (new releases, O2-exclusive IDs) use static.

Three dicts, matching the three axes in QualityIndex:
  STATIC_QUALITY  — AA intelligence_index (0-100+ scale, higher = smarter)
  STATIC_TPS      — median output tokens/second (higher = faster)
  STATIC_TTFT     — median time-to-first-token in seconds (lower = faster)

Sources for all three: AA public benchmarks (artificialanalysis.ai), 2026-05.
TPS/TTFT only included where AA has independent measurements — no provider
marketing numbers. Alias IDs (qwen3.5-flash = 35b-a3b) carry the same value.
Highspeed tier variants (minimax-m2.x-highspeed) omitted: MiniMax's "100 TPS"
is a guaranteed throughput tier, not a measured median.

Maintenance:
  - Run `scripts/refresh_hosted_catalog.py` when O2 adds models → update
    dotted-ID sections below.
  - LiteLLM hyphenated entries are refreshed by AA at runtime; only update
    here when AA loses coverage for a model you care about.

AA normalization note: AA converts "Claude Opus 4.7" → "claude-opus-4-7"
(dots→hyphens). The `_lookup_score` helper in auto_routing.py bridges
dotted→hyphenated for models that only appear here under their O2 dotted ID.
Models with ONLY dotted IDs and no LiteLLM hyphenated equivalent (kimi, minimax,
qwen3.5/3.6) are listed here with their dotted IDs.
"""

from __future__ import annotations

# fmt: off
STATIC_QUALITY: dict[str, float] = {

    # ── OpenAI ────────────────────────────────────────────────────────────
    # o-series reasoning models
    "o1":                          85.0,
    "o1-2024-12-17":               85.0,
    "o1-pro":                      92.0,
    "o1-pro-2025-03-19":           92.0,
    "o3":                          88.0,
    "o3-2025-04-16":               88.0,
    "o3-mini":                     78.0,
    "o3-mini-2025-01-31":          78.0,
    "o3-mini-high":                80.0,   # high-effort tier
    "o4-mini":                     81.0,
    "o4-mini-2025-04-16":          81.0,
    "o4-mini-high":                83.0,   # high-effort tier
    # GPT-4 family
    "gpt-4":                       68.0,
    "gpt-4-turbo":                 72.0,
    "gpt-4-turbo-2024-04-09":      72.0,
    "gpt-4o":                      75.0,
    "gpt-4o-2024-05-13":           74.0,
    "gpt-4o-2024-08-06":           75.0,
    "gpt-4o-2024-11-20":           75.0,
    "gpt-4o-mini":                 67.0,
    "gpt-4o-mini-2024-07-18":      67.0,
    "gpt-4o-mini-search-preview":  67.0,
    "gpt-4o-search-preview":       75.0,
    # GPT-4.1 family
    "gpt-4.1":                     77.0,
    "gpt-4.1-2025-04-14":          77.0,
    "gpt-4.1-mini":                70.0,
    "gpt-4.1-mini-2025-04-14":     70.0,
    "gpt-4.1-nano":                62.0,
    "gpt-4.1-nano-2025-04-14":     62.0,
    # GPT-5 base
    "gpt-5":                       79.0,
    "gpt-5-2025-08-07":            79.0,
    "gpt-5-chat":                  79.0,
    "gpt-5-chat-latest":           79.0,
    "gpt-5-mini":                  72.0,
    "gpt-5-mini-2025-08-07":       72.0,
    "gpt-5-nano":                  60.0,
    "gpt-5-nano-2025-08-07":       60.0,
    "gpt-5-search-api":            79.0,
    "gpt-5-search-api-2025-10-14": 79.0,
    "gpt-5-codex":                 79.0,   # code-specialized
    "gpt-5-pro":                   82.0,
    "gpt-5-pro-2025-10-06":        82.0,
    # GPT-5.1
    "gpt-5.1":                     80.0,
    "gpt-5.1-2025-11-13":          80.0,
    "gpt-5.1-chat-latest":         80.0,
    "gpt-5.1-codex":               80.0,
    "gpt-5.1-codex-max":           83.0,
    "gpt-5.1-codex-mini":          75.0,
    # GPT-5.2
    "gpt-5.2":                     82.0,
    "gpt-5.2-2025-12-11":          82.0,
    "gpt-5.2-chat-latest":         82.0,
    "gpt-5.2-codex":               82.0,
    "gpt-5.2-pro":                 84.0,
    "gpt-5.2-pro-2025-12-11":      84.0,
    # GPT-5.3
    "gpt-5.3-chat-latest":         83.0,
    "gpt-5.3-codex":               83.0,
    # GPT-5.4
    "gpt-5.4":                     85.0,
    "gpt-5.4-2026-03-05":          85.0,
    "gpt-5.4-mini":                77.0,
    "gpt-5.4-mini-2026-03-17":     77.0,
    "gpt-5.4-nano":                65.0,
    "gpt-5.4-nano-2026-03-17":     65.0,
    "gpt-5.4-pro":                 87.0,
    "gpt-5.4-pro-2026-03-05":      87.0,
    # GPT-5.5
    "gpt-5.5":                     90.0,
    "gpt-5.5-2026-04-23":          90.0,
    "gpt-5.5-pro":                 92.0,
    "gpt-5.5-pro-2026-04-23":      92.0,

    # ── Anthropic ──────────────────────────────────────────────────────────
    # Claude 3.5 (legacy, LiteLLM IDs)
    "claude-3-5-sonnet-latest":    77.0,
    "claude-3-5-haiku-latest":     65.0,
    # Claude 4 Sonnet family (LiteLLM hyphenated IDs)
    "claude-sonnet-4-20250514":    79.0,
    "claude-4-sonnet-20250514":    79.0,
    "claude-sonnet-4-5":           81.0,
    "claude-sonnet-4-5-20250929":  81.0,
    "claude-sonnet-4-6":           82.0,
    # Claude 4 Haiku
    "claude-haiku-4-5":            69.0,
    "claude-haiku-4-5-20251001":   69.0,
    # Claude 4 Opus family (LiteLLM hyphenated IDs)
    "claude-4-opus-20250514":      86.0,
    "claude-opus-4-20250514":      86.0,
    "claude-opus-4-1":             87.0,
    "claude-opus-4-1-20250805":    87.0,
    "claude-opus-4-5":             84.0,
    "claude-opus-4-5-20251101":    84.0,
    "claude-opus-4-6":             85.0,
    "claude-opus-4-6-20260205":    85.0,
    "claude-opus-4-7":             86.0,
    "claude-opus-4-7-20260416":    86.0,

    # ── Google ─────────────────────────────────────────────────────────────
    # Gemini 2.5
    "gemini-2.5-pro":                        80.0,
    "gemini-2.5-flash":                      72.0,
    "gemini-2.5-flash-lite":                 63.0,
    "gemini-2.5-flash-preview-09-2025":      72.0,
    "gemini-2.5-flash-lite-preview-09-2025": 63.0,
    "gemini-flash-latest":                   72.0,
    "gemini-flash-lite-latest":              63.0,
    "gemini-pro-latest":                     80.0,
    # Gemini 3.x
    "gemini-3-flash-preview":                76.0,
    "gemini-3-pro-preview":                  82.0,
    "gemini-3.1-flash-lite-preview":         74.0,
    "gemini-3.1-pro-preview":                84.0,
    "gemini-3.1-pro-preview-customtools":    84.0,
    # Gemma 3 open models
    "gemma-3-27b-it":              66.0,
    "gemma-3-12b-it":              62.0,
    "gemma-3-4b-it":               54.0,
    "gemma-3-1b-it":               44.0,
    "gemma-3n-e4b-it":             52.0,
    "gemma-3n-e2b-it":             44.0,
    # Gemma 4 open models
    "gemma-4-31b-it":              70.0,
    "gemma-4-26b-a4b-it":          68.0,

    # ── DeepSeek ───────────────────────────────────────────────────────────
    "deepseek-chat":               71.0,
    "deepseek-v3":                 79.0,
    "deepseek-v3.2":               81.0,
    "deepseek-r1":                 84.0,
    "deepseek-reasoner":           83.0,
    "deepseek-v4-flash":           73.0,
    "deepseek-v4-pro":             83.0,

    # ── xAI Grok ────────────────────────────────────────────────────────────
    # LiteLLM uses bare IDs without provider prefix for xai models
    "grok-3":                      79.0,
    "grok-3-mini":                 71.0,
    "grok-3-mini-high":            73.0,
    "grok-3-mini-low":             69.0,
    "grok-4":                      82.0,
    "grok-4-0709":                 82.0,
    "grok-4-1-fast-non-reasoning": 76.0,
    "grok-4-1-fast-reasoning":     78.0,
    "grok-4-fast-non-reasoning":   77.0,
    "grok-4-fast-reasoning":       79.0,
    "grok-code-fast-1":            74.0,
    "grok-code-fast-1-0825":       74.0,

    # ── Kimi (Moonshot AI) — dotted IDs; no LiteLLM hyphenated equivalent ──
    "kimi-k2.5":                   75.0,
    "kimi-k2.6":                   77.0,

    # ── MiniMax — dotted IDs; no LiteLLM hyphenated equivalent ─────────────
    "minimax-m2.5":                70.0,
    "minimax-m2.5-highspeed":      70.0,
    "minimax-m2.7":                73.0,
    "minimax-m2.7-highspeed":      73.0,

    # ── Qwen 3 (non-dotted) ────────────────────────────────────────────────
    "qwen3-max":                   79.0,
    "qwen3-max-preview":           79.0,
    "qwen3-vl-235b-a22b-instruct": 77.0,
    "qwen3-vl-235b-a22b-thinking": 80.0,
    "qwen3-vl-8b-instruct":        62.0,
    "qwen3-vl-8b-thinking":        65.0,

    # ── Qwen 3.5 / 3.6 — dotted IDs; no LiteLLM hyphenated equivalent ─────
    "qwen3.5-397b-a17b":           76.0,
    "qwen3.5-122b-a10b":           73.0,
    "qwen3.5-plus":                72.0,
    "qwen3.5-plus-2026-02-15":     72.0,
    "qwen3.5-27b":                 68.0,
    "qwen3.5-35b-a3b":             70.0,
    "qwen3.5-flash":               60.0,
    "qwen3.5-flash-2026-02-23":    60.0,
    "qwen3.6-plus":                74.0,
    "qwen3.6-plus-2026-04-02":     74.0,
    "qwen3.6-35b-a3b":             71.0,
    "qwen3.6-flash":               61.0,
    "qwen3.6-flash-2026-04-16":    61.0,
}
# fmt: on

# fmt: off
# TPS = median output tokens/second. Higher = faster.
# Only O2-exclusive dotted-ID models are listed here; mainstream models
# (OpenAI, Anthropic, Google, Grok, DeepSeek) are covered by the live AA fetch.
# Source: artificialanalysis.ai, 2026-05. AA wins on overlap.
STATIC_TPS: dict[str, float] = {
    # ── Kimi (Moonshot AI) ─────────────────────────────────────────────────
    "kimi-k2.5":                    37.3,
    "kimi-k2.6":                    34.3,

    # ── MiniMax ────────────────────────────────────────────────────────────
    "minimax-m2.5":                 93.5,
    "minimax-m2.7":                 52.7,
    # highspeed variants omitted — MiniMax's "100 TPS" is a guaranteed
    # throughput tier, not an independently measured median.

    # ── Qwen 3.5 (AA uses parameter-count names; alias IDs share the value) ─
    "qwen3.5-35b-a3b":             164.4,
    "qwen3.5-flash":               164.4,   # alias for 35b-a3b
    "qwen3.5-flash-2026-02-23":    164.4,
    "qwen3.5-397b-a17b":            52.4,
    "qwen3.5-plus":                 52.4,   # alias for 397b-a17b
    "qwen3.5-plus-2026-02-15":      52.4,
    "qwen3.5-122b-a10b":           148.8,
    "qwen3.5-27b":                  86.8,

    # ── Qwen 3.6 ────────────────────────────────────────────────────────────
    "qwen3.6-35b-a3b":             200.4,
    "qwen3.6-plus":                 52.4,
    "qwen3.6-plus-2026-04-02":      52.4,
    # qwen3.6-flash: no AA data yet (released 2026-04-27)
}

# TTFT = median time-to-first-token in seconds. Lower = faster.
# Same sourcing rules as STATIC_TPS above.
STATIC_TTFT: dict[str, float] = {
    # ── Kimi ───────────────────────────────────────────────────────────────
    "kimi-k2.5":                     3.03,
    "kimi-k2.6":                     3.09,

    # ── MiniMax ────────────────────────────────────────────────────────────
    "minimax-m2.5":                  1.70,
    "minimax-m2.7":                  1.91,

    # ── Qwen 3.5 ────────────────────────────────────────────────────────────
    "qwen3.5-35b-a3b":               2.16,
    "qwen3.5-flash":                 2.16,
    "qwen3.5-flash-2026-02-23":      2.16,
    "qwen3.5-397b-a17b":             2.48,
    "qwen3.5-plus":                  2.48,
    "qwen3.5-plus-2026-02-15":       2.48,
    "qwen3.5-122b-a10b":             2.49,
    "qwen3.5-27b":                   5.77,

    # ── Qwen 3.6 ────────────────────────────────────────────────────────────
    "qwen3.6-35b-a3b":               2.43,
    "qwen3.6-plus":                  2.68,
    "qwen3.6-plus-2026-04-02":       2.68,
}
# fmt: on
