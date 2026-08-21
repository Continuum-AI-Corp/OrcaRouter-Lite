"""Authoritative list of OrcaRouter hosted-routable models.

Sourced from production O2 catalog (operator-curated, distinct from the
public /v1/models snapshot). Filtered by `chat_completions` in the model's
supported endpoint types — entries lacking that signal (image_generation,
video_generation) are excluded.

Provider counts: openai 37 / qwen 17 / google 16 / grok 11 / anthropic 9 /
                 deepseek 4 / minimax 4 / kimi 2

Format: (provider, bare_model_id) where provider matches the O2 wire prefix
(openai/anthropic/google/deepseek/grok/kimi/minimax/qwen) and bare_model_id
is what users put in model="...". Wire format = f"{provider}/{bare_id}".

HOSTED_CATALOG_SUPPLEMENT: catalog metadata for O2 models not in LiteLLM's
model_cost table. catalog.py merges these into CATALOG / CATALOG_BY_ID (but
NOT into PROVIDERS_TO_MODELS) so auto-routing sees O2-native bare IDs while
local provider routing continues using LiteLLM's canonical hyphenated IDs.

Format: (id, provider, litellm_prefix, tools, vision, json_mode,
         in_$/tok, out_$/tok)
Pricing: provider docs / inference APIs as of 2026-05. Intended as
scheduling weights, not billing truth; cost_usd from O2 response (via the
X-OrcaRouter-beta-usd header) is the authoritative per-request cost used
in RequestLog.
"""

from __future__ import annotations

HOSTED_MODELS: tuple[tuple[str, str], ...] = (
    ('anthropic', 'claude-haiku-4.5'),
    ('anthropic', 'claude-opus-4'),
    ('anthropic', 'claude-opus-4.1'),
    ('anthropic', 'claude-opus-4.5'),
    ('anthropic', 'claude-opus-4.6'),
    ('anthropic', 'claude-opus-4.7'),
    ('anthropic', 'claude-sonnet-4'),
    ('anthropic', 'claude-sonnet-4.5'),
    ('anthropic', 'claude-sonnet-4.6'),
    ('deepseek', 'deepseek-chat'),
    ('deepseek', 'deepseek-reasoner'),
    ('deepseek', 'deepseek-v4-flash'),
    ('deepseek', 'deepseek-v4-flash-free'),
    ('deepseek', 'deepseek-v4-pro'),
    ('deepseek', 'deepseek-v4-pro-free'),
    ('google', 'gemini-2.5-flash-image'),
    ('google', 'gemini-2.5-pro'),
    ('google', 'gemini-3-flash-preview'),
    ('google', 'gemini-3-pro-image-preview'),
    ('google', 'gemini-3-pro-preview'),
    ('google', 'gemini-3.1-flash-image-preview'),
    ('google', 'gemini-3.1-flash-lite-preview'),
    ('google', 'gemini-3.1-pro-preview'),
    ('google', 'gemini-3.1-pro-preview-customtools'),
    ('google', 'gemini-flash-latest'),
    ('google', 'gemini-flash-lite-latest'),
    ('google', 'gemini-pro-latest'),
    ('google', 'gemini-robotics-er-1.5-preview'),
    ('google', 'gemini-robotics-er-1.6-preview'),
    ('google', 'gemma-4-26b-a4b-it'),
    ('google', 'gemma-4-31b-it'),
    ('grok', 'grok-3-mini'),
    ('grok', 'grok-3-mini-high'),
    ('grok', 'grok-3-mini-low'),
    ('grok', 'grok-4-0709'),
    ('grok', 'grok-4-1-fast-non-reasoning'),
    ('grok', 'grok-4-1-fast-reasoning'),
    ('grok', 'grok-4-fast-non-reasoning'),
    ('grok', 'grok-4-fast-reasoning'),
    ('grok', 'grok-code-fast-1'),
    ('grok', 'grok-imagine-image'),
    ('grok', 'grok-imagine-image-pro'),
    ('kimi', 'kimi-k2.5'),
    ('kimi', 'kimi-k2.6'),
    ('minimax', 'minimax-m2.5'),
    ('minimax', 'minimax-m2.5-highspeed'),
    ('minimax', 'minimax-m2.7'),
    ('minimax', 'minimax-m2.7-highspeed'),
    ('openai', 'gpt-4-0613'),
    ('openai', 'gpt-5'),
    ('openai', 'gpt-5-2025-08-07'),
    ('openai', 'gpt-5-chat-latest'),
    ('openai', 'gpt-5-codex'),
    ('openai', 'gpt-5-mini'),
    ('openai', 'gpt-5-mini-2025-08-07'),
    ('openai', 'gpt-5-pro'),
    ('openai', 'gpt-5-pro-2025-10-06'),
    ('openai', 'gpt-5-search-api'),
    ('openai', 'gpt-5-search-api-2025-10-14'),
    ('openai', 'gpt-5.1'),
    ('openai', 'gpt-5.1-2025-11-13'),
    ('openai', 'gpt-5.1-chat-latest'),
    ('openai', 'gpt-5.1-codex'),
    ('openai', 'gpt-5.1-codex-max'),
    ('openai', 'gpt-5.1-codex-mini'),
    ('openai', 'gpt-5.2'),
    ('openai', 'gpt-5.2-2025-12-11'),
    ('openai', 'gpt-5.2-chat-latest'),
    ('openai', 'gpt-5.2-codex'),
    ('openai', 'gpt-5.2-pro'),
    ('openai', 'gpt-5.2-pro-2025-12-11'),
    ('openai', 'gpt-5.3-chat-latest'),
    ('openai', 'gpt-5.3-codex'),
    ('openai', 'gpt-5.4'),
    ('openai', 'gpt-5.4-2026-03-05'),
    ('openai', 'gpt-5.4-mini'),
    ('openai', 'gpt-5.4-mini-2026-03-17'),
    ('openai', 'gpt-5.4-nano'),
    ('openai', 'gpt-5.4-nano-2026-03-17'),
    ('openai', 'gpt-5.4-pro'),
    ('openai', 'gpt-5.4-pro-2026-03-05'),
    ('openai', 'gpt-5.5'),
    ('openai', 'gpt-5.5-2026-04-23'),
    ('openai', 'gpt-5.5-pro'),
    ('openai', 'gpt-5.5-pro-2026-04-23'),
    ('orcarouter', 'free'),
    ('qwen', 'qwen3-max'),
    ('qwen', 'qwen3-max-preview'),
    ('qwen', 'qwen3-vl-235b-a22b-instruct'),
    ('qwen', 'qwen3-vl-235b-a22b-thinking'),
    ('qwen', 'qwen3.5-122b-a10b'),
    ('qwen', 'qwen3.5-27b'),
    ('qwen', 'qwen3.5-35b-a3b'),
    ('qwen', 'qwen3.5-397b-a17b'),
    ('qwen', 'qwen3.5-flash'),
    ('qwen', 'qwen3.5-flash-2026-02-23'),
    ('qwen', 'qwen3.5-plus'),
    ('qwen', 'qwen3.5-plus-2026-02-15'),
    ('qwen', 'qwen3.6-35b-a3b'),
    ('qwen', 'qwen3.6-flash'),
    ('qwen', 'qwen3.6-flash-2026-04-16'),
    ('qwen', 'qwen3.6-plus'),
    ('qwen', 'qwen3.6-plus-2026-04-02'),
    ('qwen', 'qwen3.8-27b-free'),
)

# O2's public API uses provider-qualified IDs for its zero-credit models.
# Keep the normal bare model group for compatibility, and additionally expose
# these exact wire IDs so OpenAI-compatible clients can copy an ID directly
# from api.orcarouter.ai/v1/models into their local Lite request unchanged.
HOSTED_MODEL_ALIASES: frozenset[str] = frozenset({
    'deepseek/deepseek-v4-flash-free',
    'deepseek/deepseek-v4-pro-free',
    'orcarouter/free',
    'qwen/qwen3.8-27b-free',
})

# Supplemental catalog metadata for O2 models absent from LiteLLM's model_cost.
# Subset of HOSTED_MODELS — only entries whose bare_id LiteLLM doesn't ship.
# Models in HOSTED_MODELS but absent from this supplement (image-preview,
# robotics-er, grok-imagine-*) are deployable via explicit pin but skipped
# by auto-routing (no cost metadata → eligibility filter drops them).
HOSTED_CATALOG_SUPPLEMENT: tuple[tuple, ...] = (
    ('claude-haiku-4.5'          , 'anthropic', 'anthropic/', True, True, True, 1.00e-06, 5.00e-06),
    ('claude-opus-4'             , 'anthropic', 'anthropic/', True, True, True, 1.50e-05, 7.50e-05),
    ('claude-opus-4.1'           , 'anthropic', 'anthropic/', True, True, True, 1.50e-05, 7.50e-05),
    ('claude-opus-4.5'           , 'anthropic', 'anthropic/', True, True, True, 5.00e-06, 2.50e-05),
    ('claude-opus-4.6'           , 'anthropic', 'anthropic/', True, True, True, 5.00e-06, 2.50e-05),
    ('claude-opus-4.7'           , 'anthropic', 'anthropic/', True, True, True, 5.00e-06, 2.50e-05),
    ('claude-sonnet-4'           , 'anthropic', 'anthropic/', True, True, True, 3.00e-06, 1.50e-05),
    ('claude-sonnet-4.5'         , 'anthropic', 'anthropic/', True, True, True, 3.00e-06, 1.50e-05),
    ('claude-sonnet-4.6'         , 'anthropic', 'anthropic/', True, True, True, 3.00e-06, 1.50e-05),
    ('deepseek-v4-flash'         ,  'deepseek', 'deepseek/', True, False, True, 2.80e-07, 4.00e-07),
    ('deepseek-v4-pro'           ,  'deepseek', 'deepseek/', True, False, True, 2.70e-07, 1.10e-06),
    ('gemini-3-pro-preview'      ,    'google',   'gemini/', True, True, True, 2.00e-06, 1.20e-05),
    ('gemma-4-26b-a4b-it'        ,    'google',   'gemini/', True, True, True, 7.50e-08, 3.00e-07),
    ('gemma-4-31b-it'            ,    'google',   'gemini/', True, True, True, 7.50e-08, 3.00e-07),
    ('grok-3-mini'               ,       'xai',      'xai/', True, False, True, 3.00e-07, 5.00e-07),
    ('grok-3-mini-high'          ,       'xai',      'xai/', True, False, True, 3.00e-07, 5.00e-07),
    ('grok-3-mini-low'           ,       'xai',      'xai/', True, False, True, 3.00e-07, 5.00e-07),
    ('kimi-k2.5'                 ,      'kimi',   'openai/', True, True, True, 6.00e-07, 2.50e-06),
    ('kimi-k2.6'                 ,      'kimi',   'openai/', True, True, True, 6.00e-07, 2.50e-06),
    ('minimax-m2.5'              ,   'minimax',   'openai/', True, True, True, 1.50e-07, 6.00e-07),
    ('minimax-m2.5-highspeed'    ,   'minimax',   'openai/', True, True, True, 1.50e-07, 6.00e-07),
    ('minimax-m2.7'              ,   'minimax',   'openai/', True, True, True, 1.50e-07, 6.00e-07),
    ('minimax-m2.7-highspeed'    ,   'minimax',   'openai/', True, True, True, 1.50e-07, 6.00e-07),
    ('gpt-5-codex'               ,    'openai',   'openai/', True, True, True, 1.25e-06, 1.00e-05),
    ('gpt-5-pro'                 ,    'openai',   'openai/', True, True, True, 5.00e-06, 3.00e-05),
    ('gpt-5-pro-2025-10-06'      ,    'openai',   'openai/', True, True, True, 5.00e-06, 3.00e-05),
    ('gpt-5.1-codex'             ,    'openai',   'openai/', True, True, True, 1.25e-06, 1.00e-05),
    ('gpt-5.1-codex-max'         ,    'openai',   'openai/', True, True, True, 2.50e-06, 1.50e-05),
    ('gpt-5.1-codex-mini'        ,    'openai',   'openai/', True, True, True, 5.00e-07, 2.50e-06),
    ('gpt-5.2-codex'             ,    'openai',   'openai/', True, True, True, 1.75e-06, 1.40e-05),
    ('gpt-5.2-pro'               ,    'openai',   'openai/', True, True, True, 3.50e-06, 2.80e-05),
    ('gpt-5.2-pro-2025-12-11'    ,    'openai',   'openai/', True, True, True, 3.50e-06, 2.80e-05),
    ('gpt-5.3-codex'             ,    'openai',   'openai/', True, True, True, 1.75e-06, 1.40e-05),
    ('gpt-5.4-pro'               ,    'openai',   'openai/', True, True, True, 5.00e-06, 3.00e-05),
    ('gpt-5.4-pro-2026-03-05'    ,    'openai',   'openai/', True, True, True, 5.00e-06, 3.00e-05),
    ('gpt-5.5-pro'               ,    'openai',   'openai/', True, True, True, 1.00e-05, 6.00e-05),
    ('gpt-5.5-pro-2026-04-23'    ,    'openai',   'openai/', True, True, True, 1.00e-05, 6.00e-05),
    ('qwen3-max'                 ,      'qwen',   'openai/', True, False, True, 1.60e-06, 6.40e-06),
    ('qwen3-max-preview'         ,      'qwen',   'openai/', True, False, True, 1.60e-06, 6.40e-06),
    ('qwen3-vl-235b-a22b-instruct',      'qwen',   'openai/', True, True, True, 4.00e-07, 1.60e-06),
    ('qwen3-vl-235b-a22b-thinking',      'qwen',   'openai/', True, True, True, 4.00e-07, 4.00e-06),
    ('qwen3.5-122b-a10b'         ,      'qwen',   'openai/', True, False, True, 4.00e-07, 2.00e-06),
    ('qwen3.5-27b'               ,      'qwen',   'openai/', True, False, True, 3.00e-07, 2.40e-06),
    ('qwen3.5-35b-a3b'           ,      'qwen',   'openai/', True, False, True, 2.50e-07, 2.00e-06),
    ('qwen3.5-397b-a17b'         ,      'qwen',   'openai/', True, False, True, 6.00e-07, 3.60e-06),
    ('qwen3.5-flash'             ,      'qwen',   'openai/', True, False, True, 1.00e-07, 4.00e-07),
    ('qwen3.5-flash-2026-02-23'  ,      'qwen',   'openai/', True, False, True, 1.00e-07, 4.00e-07),
    ('qwen3.5-plus'              ,      'qwen',   'openai/', True, False, True, 4.00e-07, 2.40e-06),
    ('qwen3.5-plus-2026-02-15'   ,      'qwen',   'openai/', True, False, True, 4.00e-07, 2.40e-06),
    ('qwen3.6-35b-a3b'           ,      'qwen',   'openai/', True, False, True, 2.50e-07, 2.00e-06),
    ('qwen3.6-flash'             ,      'qwen',   'openai/', True, False, True, 1.00e-07, 4.00e-07),
    ('qwen3.6-flash-2026-04-16'  ,      'qwen',   'openai/', True, False, True, 1.00e-07, 4.00e-07),
    ('qwen3.6-plus'              ,      'qwen',   'openai/', True, False, True, 4.00e-07, 2.40e-06),
    ('qwen3.6-plus-2026-04-02'   ,      'qwen',   'openai/', True, False, True, 4.00e-07, 2.40e-06),
)
