"""Static quality + latency baseline for routing strategies.

Covers both LiteLLM catalog models (hyphenated IDs) and O2-hosted models
(dotted IDs where no LiteLLM hyphenated equivalent exists). Serves as the
floor for routing decisions:

  - Pairs with dynamic Artificial Analysis fetch in quality_index.py.
  - AA data always wins on overlap (static = fallback, not override).
  - Models not in AA's dataset (new releases, O2-exclusive IDs) use static.

Three dicts, matching the three axes in QualityIndex:
  STATIC_QUALITY  — AA `artificial_analysis_intelligence_index`
                    (composite 0-100, higher = smarter)
  STATIC_TPS      — AA `median_output_tokens_per_second` (higher = faster)
  STATIC_TTFT     — AA `median_time_to_first_token_seconds` (lower = faster)

Source: All values pulled from artificialanalysis.ai/api/v2/data/llms/models
on 2026-05-06 and mapped to our model IDs. The mapping reconciles AA's slug
convention (`claude-4-1-opus`, `gpt-5-5`) with ours (`claude-opus-4-1`,
`gpt-5.5`). For models with effort tiers, we pick the highest/default variant
(e.g. `gpt-5-5` slug = "GPT-5.5 (xhigh)", which maps to our `gpt-5.5`).

Maintenance:
  - Re-pull AA + remap when notable scores shift or new models appear. The
    live AA fetch in quality_index.py overrides static on overlap, so this
    file's values only kick in for cold-start workspaces and AA-uncovered
    models (kimi, minimax, qwen3.5/3.6 dotted IDs occasionally).
  - When O2 adds models (`scripts/refresh_hosted_catalog.py`), check whether
    AA covers them; if yes, add a row here so cold-start routing has data.

AA normalization note: AA converts "Claude Opus 4.7" → slug `claude-opus-4-7`
(dots→hyphens, sometimes word-reordered). The `_lookup_score` helper in
auto_routing.py handles dotted→hyphenated for IDs that only appear here in
their O2-native dotted form. Models with ONLY dotted IDs and no LiteLLM
hyphenated equivalent (kimi, minimax, qwen3.5/3.6) are listed below with
their dotted IDs.
"""

from __future__ import annotations

# fmt: off
STATIC_QUALITY: dict[str, float] = {
    # ── Anthropic Claude ──
    'claude-3-5-haiku-latest':                 18.7,
    'claude-3-5-sonnet-latest':                15.9,
    'claude-4-opus-20250514':                  39.0,
    'claude-4-sonnet-20250514':                38.7,
    'claude-haiku-4-5':                        37.1,
    'claude-haiku-4-5-20251001':               37.1,
    'claude-opus-4':                           39.0,
    'claude-opus-4-1':                         42.0,
    'claude-opus-4-1-20250805':                42.0,
    'claude-opus-4-20250514':                  39.0,
    'claude-opus-4-5':                         49.7,
    'claude-opus-4-5-20251101':                49.7,
    'claude-opus-4-6':                         53.0,
    'claude-opus-4-6-20260205':                53.0,
    'claude-opus-4-7':                         57.3,
    'claude-opus-4-7-20260416':                57.3,
    'claude-sonnet-4':                         38.7,
    'claude-sonnet-4-20250514':                38.7,
    'claude-sonnet-4-5':                       43.0,
    'claude-sonnet-4-5-20250929':              43.0,
    'claude-sonnet-4-6':                       51.7,

    # ── OpenAI GPT-3.x / 4.x ──
    'gpt-4':                                   12.8,
    'gpt-4-turbo':                             13.7,
    'gpt-4-turbo-2024-04-09':                  13.7,
    'gpt-4.1':                                 26.3,
    'gpt-4.1-2025-04-14':                      26.3,
    'gpt-4.1-mini':                            22.9,
    'gpt-4.1-mini-2025-04-14':                 22.9,
    'gpt-4.1-nano':                            13.0,
    'gpt-4.1-nano-2025-04-14':                 13.0,
    'gpt-4o':                                  17.3,
    'gpt-4o-2024-05-13':                       14.5,
    'gpt-4o-2024-08-06':                       18.6,
    'gpt-4o-2024-11-20':                       17.3,
    'gpt-4o-mini':                             12.6,
    'gpt-4o-mini-2024-07-18':                  12.6,

    # ── OpenAI GPT-5.x ──
    'gpt-5':                                   44.6,
    'gpt-5-2025-08-07':                        44.6,
    'gpt-5-codex':                             44.6,
    'gpt-5-mini':                              41.2,
    'gpt-5-mini-2025-08-07':                   41.2,
    'gpt-5-nano':                              26.8,
    'gpt-5-nano-2025-08-07':                   26.8,
    'gpt-5.1':                                 47.7,
    'gpt-5.1-2025-11-13':                      47.7,
    'gpt-5.1-codex':                           43.1,
    'gpt-5.1-codex-max':                       43.1,
    'gpt-5.1-codex-mini':                      38.6,
    'gpt-5.2':                                 51.3,
    'gpt-5.2-2025-12-11':                      51.3,
    'gpt-5.2-codex':                           49.0,
    'gpt-5.3-codex':                           53.6,
    'gpt-5.4':                                 56.8,
    'gpt-5.4-2026-03-05':                      56.8,
    'gpt-5.4-mini':                            48.9,
    'gpt-5.4-nano':                            44.0,
    'gpt-5.5':                                 60.2,
    'gpt-5.5-2026-04-23':                      60.2,

    # ── OpenAI o-series ──
    'o1':                                      30.8,
    'o1-2024-12-17':                           30.8,
    'o1-pro':                                  25.8,
    'o1-pro-2025-03-19':                       25.8,
    'o3':                                      38.4,
    'o3-2025-04-16':                           38.4,
    'o3-mini':                                 25.9,
    'o3-mini-2025-01-31':                      25.9,
    'o3-mini-high':                            25.2,
    'o4-mini':                                 33.1,
    'o4-mini-2025-04-16':                      33.1,

    # ── Google Gemini ──
    'gemini-2.5-flash':                        20.6,
    'gemini-2.5-flash-lite':                   12.7,
    'gemini-2.5-pro':                          34.6,
    'gemini-3-flash-preview':                  35.0,
    'gemini-3-pro-preview':                    48.4,
    'gemini-3.1-flash-lite-preview':           33.5,
    'gemini-3.1-pro-preview':                  57.2,
    'gemini-3.1-pro-preview-customtools':      57.2,
    'gemini-flash-latest':                     20.6,
    'gemini-flash-lite-latest':                12.7,
    'gemini-pro-latest':                       34.6,

    # ── Google Gemma ──
    'gemma-3-12b-it':                          8.8,
    'gemma-3-1b-it':                           5.5,
    'gemma-3-27b-it':                          10.3,
    'gemma-3-4b-it':                           6.3,
    'gemma-3n-e2b-it':                         4.8,
    'gemma-3n-e4b-it':                         6.4,
    'gemma-4-26b-a4b-it':                      31.2,
    'gemma-4-31b-it':                          39.2,

    # ── DeepSeek ──
    'deepseek-chat':                           32.1,
    'deepseek-r1':                             27.1,
    'deepseek-reasoner':                       27.1,
    'deepseek-v3':                             16.5,
    'deepseek-v3.2':                           32.1,
    'deepseek-v4-flash':                       46.5,
    'deepseek-v4-pro':                         51.5,

    # ── xAI Grok ──
    'grok-3':                                  21.6,
    'grok-3-mini':                             32.1,
    'grok-3-mini-high':                        32.1,
    'grok-3-mini-low':                         32.1,
    'grok-4':                                  41.5,
    'grok-4-0709':                             41.5,
    'grok-4-1-fast-non-reasoning':             23.6,
    'grok-4-1-fast-reasoning':                 38.6,
    'grok-4-fast-non-reasoning':               23.1,
    'grok-4-fast-reasoning':                   35.1,
    'grok-code-fast-1':                        28.7,
    'grok-code-fast-1-0825':                   28.7,

    # ── Kimi (Moonshot) ──
    'kimi-k2.5':                               46.8,
    'kimi-k2.6':                               53.9,

    # ── MiniMax ──
    'minimax-m2.5':                            41.9,
    'minimax-m2.5-highspeed':                  41.9,
    'minimax-m2.7':                            49.6,
    'minimax-m2.7-highspeed':                  49.6,

    # ── Qwen (Alibaba) ──
    'qwen3-max':                               39.9,
    'qwen3-max-preview':                       26.1,
    'qwen3-vl-235b-a22b-instruct':             20.8,
    'qwen3-vl-235b-a22b-thinking':             27.6,
    'qwen3-vl-8b-instruct':                    14.3,
    'qwen3-vl-8b-thinking':                    16.7,
    'qwen3.5-122b-a10b':                       41.6,
    'qwen3.5-27b':                             42.1,
    'qwen3.5-35b-a3b':                         37.1,
    'qwen3.5-397b-a17b':                       45.0,
    'qwen3.5-flash':                           25.9,
    'qwen3.5-flash-2026-02-23':                25.9,
    'qwen3.5-plus':                            38.6,
    'qwen3.5-plus-2026-02-15':                 38.6,
    'qwen3.6-35b-a3b':                         43.5,
    'qwen3.6-flash':                           43.5,
    'qwen3.6-flash-2026-04-16':                43.5,
    'qwen3.6-plus':                            50.0,
    'qwen3.6-plus-2026-04-02':                 50.0,
}
# fmt: on

# fmt: off
# TPS = median output tokens/second. Higher = faster. Sourced from AA same as
# STATIC_QUALITY above. Live AA fetch wins on overlap.
STATIC_TPS: dict[str, float] = {
    # ── Anthropic Claude ──
    'claude-4-opus-20250514':                  44.3,
    'claude-4-sonnet-20250514':                55.7,
    'claude-haiku-4-5':                        153.5,
    'claude-haiku-4-5-20251001':               153.5,
    'claude-opus-4':                           44.3,
    'claude-opus-4-1':                         38.7,
    'claude-opus-4-1-20250805':                38.7,
    'claude-opus-4-20250514':                  44.3,
    'claude-opus-4-5':                         67.2,
    'claude-opus-4-5-20251101':                67.2,
    'claude-opus-4-6':                         56.6,
    'claude-opus-4-6-20260205':                56.6,
    'claude-opus-4-7':                         62.1,
    'claude-opus-4-7-20260416':                62.1,
    'claude-sonnet-4':                         55.7,
    'claude-sonnet-4-20250514':                55.7,
    'claude-sonnet-4-5':                       57.5,
    'claude-sonnet-4-5-20250929':              57.5,
    'claude-sonnet-4-6':                       66.1,

    # ── OpenAI GPT-3.x / 4.x ──
    'gpt-4':                                   28.3,
    'gpt-4-turbo':                             34.2,
    'gpt-4-turbo-2024-04-09':                  34.2,
    'gpt-4.1':                                 127.4,
    'gpt-4.1-2025-04-14':                      127.4,
    'gpt-4.1-mini':                            86.3,
    'gpt-4.1-mini-2025-04-14':                 86.3,
    'gpt-4.1-nano':                            126.7,
    'gpt-4.1-nano-2025-04-14':                 126.7,
    'gpt-4o':                                  159.7,
    'gpt-4o-2024-05-13':                       107.6,
    'gpt-4o-2024-08-06':                       108.8,
    'gpt-4o-2024-11-20':                       159.7,
    'gpt-4o-mini':                             62.2,
    'gpt-4o-mini-2024-07-18':                  62.2,

    # ── OpenAI GPT-5.x ──
    'gpt-5':                                   95.9,
    'gpt-5-2025-08-07':                        95.9,
    'gpt-5-codex':                             179.1,
    'gpt-5-mini':                              78.4,
    'gpt-5-mini-2025-08-07':                   78.4,
    'gpt-5-nano':                              140.2,
    'gpt-5-nano-2025-08-07':                   140.2,
    'gpt-5.1':                                 154.6,
    'gpt-5.1-2025-11-13':                      154.6,
    'gpt-5.1-codex':                           194.8,
    'gpt-5.1-codex-max':                       194.8,
    'gpt-5.1-codex-mini':                      212.3,
    'gpt-5.2':                                 74.0,
    'gpt-5.2-2025-12-11':                      74.0,
    'gpt-5.2-codex':                           102.3,
    'gpt-5.3-codex':                           87.1,
    'gpt-5.4':                                 84.8,
    'gpt-5.4-2026-03-05':                      84.8,
    'gpt-5.4-mini':                            177.8,
    'gpt-5.4-nano':                            163.7,
    'gpt-5.5':                                 78.7,
    'gpt-5.5-2026-04-23':                      78.7,

    # ── OpenAI o-series ──
    'o1':                                      122.2,
    'o1-2024-12-17':                           122.2,
    'o3':                                      117.3,
    'o3-2025-04-16':                           117.3,
    'o3-mini':                                 144.1,
    'o3-mini-2025-01-31':                      144.1,
    'o3-mini-high':                            159.6,
    'o4-mini':                                 134.0,
    'o4-mini-2025-04-16':                      134.0,

    # ── Google Gemini ──
    'gemini-2.5-flash':                        199.8,
    'gemini-2.5-flash-lite':                   292.9,
    'gemini-2.5-pro':                          132.5,
    'gemini-3-flash-preview':                  189.8,
    'gemini-3-pro-preview':                    141.5,
    'gemini-3.1-flash-lite-preview':           338.0,
    'gemini-3.1-pro-preview':                  137.6,
    'gemini-3.1-pro-preview-customtools':      137.6,
    'gemini-flash-latest':                     199.8,
    'gemini-flash-lite-latest':                292.9,
    'gemini-pro-latest':                       132.5,

    # ── Google Gemma ──
    'gemma-3-12b-it':                          29.4,
    'gemma-3-1b-it':                           60.7,
    'gemma-3-27b-it':                          31.7,
    'gemma-3-4b-it':                           30.7,
    'gemma-3n-e2b-it':                         59.9,
    'gemma-3n-e4b-it':                         20.0,
    'gemma-4-31b-it':                          35.1,

    # ── DeepSeek ──
    'deepseek-v4-flash':                       75.4,
    'deepseek-v4-pro':                         33.3,

    # ── xAI Grok ──
    'grok-3-mini':                             135.1,
    'grok-3-mini-high':                        135.1,
    'grok-3-mini-low':                         135.1,
    'grok-4':                                  45.2,
    'grok-4-0709':                             45.2,
    'grok-4-1-fast-non-reasoning':             109.2,
    'grok-4-1-fast-reasoning':                 84.9,
    'grok-4-fast-non-reasoning':               66.7,
    'grok-4-fast-reasoning':                   61.8,
    'grok-code-fast-1':                        83.1,
    'grok-code-fast-1-0825':                   83.1,

    # ── Kimi (Moonshot) ──
    'kimi-k2.5':                               45.5,
    'kimi-k2.6':                               28.2,

    # ── MiniMax ──
    'minimax-m2.5':                            103.6,
    'minimax-m2.5-highspeed':                  103.6,
    'minimax-m2.7':                            49.8,
    'minimax-m2.7-highspeed':                  49.8,

    # ── Qwen (Alibaba) ──
    'qwen3-max':                               46.2,
    'qwen3-max-preview':                       52.2,
    'qwen3-vl-235b-a22b-instruct':             51.2,
    'qwen3-vl-235b-a22b-thinking':             33.4,
    'qwen3-vl-8b-instruct':                    146.5,
    'qwen3-vl-8b-thinking':                    137.1,
    'qwen3.5-122b-a10b':                       148.5,
    'qwen3.5-27b':                             84.6,
    'qwen3.5-35b-a3b':                         127.8,
    'qwen3.5-397b-a17b':                       51.7,
    'qwen3.5-flash':                           248.1,
    'qwen3.5-flash-2026-02-23':                248.1,
    'qwen3.5-plus':                            56.1,
    'qwen3.5-plus-2026-02-15':                 56.1,
    'qwen3.6-35b-a3b':                         189.4,
    'qwen3.6-flash':                           189.4,
    'qwen3.6-flash-2026-04-16':                189.4,
    'qwen3.6-plus':                            52.8,
    'qwen3.6-plus-2026-04-02':                 52.8,
}
# fmt: on

# fmt: off
# TTFT = median time-to-first-token in seconds. Lower = faster. Sourced from AA
# same as STATIC_QUALITY above. Live AA fetch wins on overlap.
STATIC_TTFT: dict[str, float] = {
    # ── Anthropic Claude ──
    'claude-4-opus-20250514':                  9.81,
    'claude-4-sonnet-20250514':                8.65,
    'claude-haiku-4-5':                        11.78,
    'claude-haiku-4-5-20251001':               11.78,
    'claude-opus-4':                           9.81,
    'claude-opus-4-1':                         8.17,
    'claude-opus-4-1-20250805':                8.17,
    'claude-opus-4-20250514':                  9.81,
    'claude-opus-4-5':                         11.60,
    'claude-opus-4-5-20251101':                11.60,
    'claude-opus-4-6':                         15.72,
    'claude-opus-4-6-20260205':                15.72,
    'claude-opus-4-7':                         24.73,
    'claude-opus-4-7-20260416':                24.73,
    'claude-sonnet-4':                         8.65,
    'claude-sonnet-4-20250514':                8.65,
    'claude-sonnet-4-5':                       7.32,
    'claude-sonnet-4-5-20250929':              7.32,
    'claude-sonnet-4-6':                       74.80,

    # ── OpenAI GPT-3.x / 4.x ──
    'gpt-4':                                   0.90,
    'gpt-4-turbo':                             0.87,
    'gpt-4-turbo-2024-04-09':                  0.87,
    'gpt-4.1':                                 0.59,
    'gpt-4.1-2025-04-14':                      0.59,
    'gpt-4.1-mini':                            0.52,
    'gpt-4.1-mini-2025-04-14':                 0.52,
    'gpt-4.1-nano':                            0.54,
    'gpt-4.1-nano-2025-04-14':                 0.54,
    'gpt-4o':                                  0.54,
    'gpt-4o-2024-05-13':                       0.66,
    'gpt-4o-2024-08-06':                       0.71,
    'gpt-4o-2024-11-20':                       0.54,
    'gpt-4o-mini':                             0.60,
    'gpt-4o-mini-2024-07-18':                  0.60,

    # ── OpenAI GPT-5.x ──
    'gpt-5':                                   71.67,
    'gpt-5-2025-08-07':                        71.67,
    'gpt-5-codex':                             6.61,
    'gpt-5-mini':                              71.90,
    'gpt-5-mini-2025-08-07':                   71.90,
    'gpt-5-nano':                              74.72,
    'gpt-5-nano-2025-08-07':                   74.72,
    'gpt-5.1':                                 17.00,
    'gpt-5.1-2025-11-13':                      17.00,
    'gpt-5.1-codex':                           3.51,
    'gpt-5.1-codex-max':                       3.51,
    'gpt-5.1-codex-mini':                      4.79,
    'gpt-5.2':                                 53.30,
    'gpt-5.2-2025-12-11':                      53.30,
    'gpt-5.2-codex':                           2.00,
    'gpt-5.3-codex':                           51.60,
    'gpt-5.4':                                 148.07,
    'gpt-5.4-2026-03-05':                      148.07,
    'gpt-5.4-mini':                            4.14,
    'gpt-5.4-nano':                            2.46,
    'gpt-5.5':                                 32.17,
    'gpt-5.5-2026-04-23':                      32.17,

    # ── OpenAI o-series ──
    'o1':                                      16.40,
    'o1-2024-12-17':                           16.40,
    'o3':                                      5.87,
    'o3-2025-04-16':                           5.87,
    'o3-mini':                                 8.75,
    'o3-mini-2025-01-31':                      8.75,
    'o3-mini-high':                            18.67,
    'o4-mini':                                 19.20,
    'o4-mini-2025-04-16':                      19.20,

    # ── Google Gemini ──
    'gemini-2.5-flash':                        0.50,
    'gemini-2.5-flash-lite':                   0.58,
    'gemini-2.5-pro':                          22.71,
    'gemini-3-flash-preview':                  0.83,
    'gemini-3-pro-preview':                    31.78,
    'gemini-3.1-flash-lite-preview':           4.92,
    'gemini-3.1-pro-preview':                  30.75,
    'gemini-3.1-pro-preview-customtools':      30.75,
    'gemini-flash-latest':                     0.50,
    'gemini-flash-lite-latest':                0.58,
    'gemini-pro-latest':                       22.71,

    # ── Google Gemma ──
    'gemma-3-12b-it':                          1.78,
    'gemma-3-1b-it':                           0.65,
    'gemma-3-27b-it':                          0.71,
    'gemma-3-4b-it':                           1.19,
    'gemma-3n-e2b-it':                         0.43,
    'gemma-3n-e4b-it':                         0.48,
    'gemma-4-31b-it':                          1.05,

    # ── DeepSeek ──
    'deepseek-v4-flash':                       0.85,
    'deepseek-v4-pro':                         1.13,

    # ── xAI Grok ──
    'grok-3-mini':                             0.43,
    'grok-3-mini-high':                        0.43,
    'grok-3-mini-low':                         0.43,
    'grok-4':                                  11.82,
    'grok-4-0709':                             11.82,
    'grok-4-1-fast-non-reasoning':             0.47,
    'grok-4-1-fast-reasoning':                 15.78,
    'grok-4-fast-non-reasoning':               0.39,
    'grok-4-fast-reasoning':                   7.70,
    'grok-code-fast-1':                        5.93,
    'grok-code-fast-1-0825':                   5.93,

    # ── Kimi (Moonshot) ──
    'kimi-k2.5':                               1.27,
    'kimi-k2.6':                               1.35,

    # ── MiniMax ──
    'minimax-m2.5':                            1.14,
    'minimax-m2.5-highspeed':                  1.14,
    'minimax-m2.7':                            1.39,
    'minimax-m2.7-highspeed':                  1.39,

    # ── Qwen (Alibaba) ──
    'qwen3-max':                               1.43,
    'qwen3-max-preview':                       1.82,
    'qwen3-vl-235b-a22b-instruct':             1.08,
    'qwen3-vl-235b-a22b-thinking':             1.29,
    'qwen3-vl-8b-instruct':                    1.10,
    'qwen3-vl-8b-thinking':                    1.05,
    'qwen3.5-122b-a10b':                       1.12,
    'qwen3.5-27b':                             1.40,
    'qwen3.5-35b-a3b':                         1.12,
    'qwen3.5-397b-a17b':                       1.40,
    'qwen3.5-flash':                           1.05,
    'qwen3.5-flash-2026-02-23':                1.05,
    'qwen3.5-plus':                            1.30,
    'qwen3.5-plus-2026-02-15':                 1.30,
    'qwen3.6-35b-a3b':                         1.29,
    'qwen3.6-flash':                           1.29,
    'qwen3.6-flash-2026-04-16':                1.29,
    'qwen3.6-plus':                            1.49,
    'qwen3.6-plus-2026-04-02':                 1.49,
}
# fmt: on
