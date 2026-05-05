# OrcaRouter Lite

**Roteador LLM self-hosted com rede de segurança gerenciada.**
Compatível com OpenAI. BYOK. Workspace único. Streaming. `model="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![tests](https://img.shields.io/badge/tests-127_passing-brightgreen)](#testing)
[![models](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

## Idiomas

- [English](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Deutsch](./README.de.md)
- [Français](./README.fr.md)
- [Español](./README.es.md)
- [Italiano](./README.it.md)
- [Русский](./README.ru.md)
- [Português](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite é a edição open source single-workspace do [OrcaRouter](https://www.orcarouter.ai). Rode no seu laptop, embarque no seu produto, ou use diretamente o `api.orcarouter.ai` hospedado para a long tail de modelos cujas chaves você não quer gerenciar.

> **Por que nós?** LiteLLM é uma biblioteca; OpenRouter é closed-source e hospedado; Ollama é apenas local. Nós somos o **servidor self-hosted com fallback gerenciado** — uma frase que nenhum deles pode dizer.

## Quickstart de 60 segundos

Duas formas de usar o OrcaRouter:

### Caminho A — Self-hosted (BYOK)

Rode o Lite na sua própria máquina; traga suas próprias chaves de provider.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# adicione pelo menos uma: OPENAI_API_KEY=sk-...  (ou ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL base: `http://localhost:8000/v1`. Use a chave `sk-orca-*` impressa na inicialização.

### Caminho B — Hospedado (conta necessária)

Sem clone, sem docker. Registre-se, pegue uma chave, aponte qualquer SDK OpenAI para o hospedado.

```bash
# 1. Registre-se em https://www.orcarouter.ai e copie sua chave sk-orca-*
# 2. Use https://api.orcarouter.ai/v1 como URL base
```

**Conta necessária.** O hospedado cuida de roteamento, faturamento e da long tail de providers — cobrado por token na sua conta OrcaRouter. Veja [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Depois chame de qualquer SDK OpenAI

Os exemplos abaixo usam a URL base localhost do Caminho A — troque por `https://api.orcarouter.ai/v1` se estiver no Caminho B.

<details>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # ou "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
    messages=[{"role": "user", "content": "Hello!"}],
)
print(r.choices[0].message.content)
```
</details>

<details>
<summary><b>Node.js</b></summary>

```js
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:8000/v1",
  apiKey: "sk-orca-abc123...",
});

const r = await client.chat.completions.create({
  model: "auto",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(r.choices[0].message.content);
```
</details>

<details>
<summary><b>curl</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</details>

Abra `http://localhost:8000/` para o dashboard — providers, roteamento, analytics, chaves (apenas Caminho A).

## Por quê?

| | OrcaRouter Lite | Biblioteca LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Servidor self-hosted | ✓ | como biblioteca | ✗ | ✓ |
| Compatível com OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multi-provider (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Dashboard embutido | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (mais barato capaz) | ✓ | ✗ | ✗ | n/a |
| Streaming | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hospedado como fallback | ✓ | ✗ | n/a | ✗ |
| Sem Postgres / sem Redis necessário | ✓ | n/a | n/a | ✓ |

## `model="auto"` — a feature destaque

Envie `model="auto"` e o OrcaRouter escolhe o modelo **mais barato** entre os providers configurados que atende aos requisitos de capacidade da requisição (tools, vision, modo JSON). Nada de regras de roteamento manuais; nada de ginástica com rate-limits; nada de otimização de custo `if x: ...` no seu código.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → roteia para o modelo mais barato com VISION coberto pelas suas chaves
```

O modelo resolvido é exposto de volta para quem chamou via header de resposta `x-orca-resolved-model`, para que você possa logar/exibir o que foi realmente usado.

## Hospedado como upstream (Lite + hospedado)

Já está rodando o Lite? Defina `ORCAROUTER_API_KEY` com seu `sk-orca-*` de [www.orcarouter.ai](https://www.orcarouter.ai), e o hospedado vira mais um provider na cadeia de roteamento — cobrindo modelos que suas chaves locais não têm:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casos de uso:
- **Teste-antes-de-comprar** — sem precisar de chaves de provider locais
- **Logging local** — o hospedado cuida do roteamento, o Lite armazena linhas de RequestLog para o dashboard
- **Failover** — providers locais falham, o hospedado é a rede de segurança

## Streaming

Formato SSE compatível com OpenAI, com framing padrão `data: ... \n\n` e um sentinel terminal `[DONE]` — drop-in para qualquer SDK que já faz streaming a partir da OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catálogo de modelos

Mais de 100 modelos de chat são carregados na inicialização a partir do [banco de preços mantido pela comunidade do LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — sem lista de modelos para manter manualmente. Cada entrada expõe:

- `id` (ex.: `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mapeado para suas chaves configuradas)
- Flags de capacidade: `supports_tools`, `supports_vision`, `supports_json_mode`
- Custo por token de entrada/saída (alimenta o widget de economia + `model="auto"`)

`GET /v1/models` retorna o catálogo no formato OpenAI.

## Deploy em outro lugar

| Plataforma | One-click |
|---|---|
| Railway | [![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template) |
| Fly.io | `fly launch --dockerfile Dockerfile` |
| Render | Conecte o repo, root dir = `.` |
| Docker puro | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (imagem em breve) |

## O que vem na caixa

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache de prompt cross-provider
- `GET  /v1/models` — catálogo de modelos descobrível (100+ modelos de `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — define / lista / revoga chaves de provider criptografadas
- `GET/PUT /v1/routing` — muda a estratégia (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analytics locais, nenhuma telemetria sai da caixa
- `GET  /v1/hosted` — status do fallback hospedado (alimenta o card "Get $5 free credit" do dashboard)
- `GET/POST/DELETE /v1/keys/...` — lista / rotaciona / revoga chaves API
- Dashboard single-page em `/`
- SQLite por padrão; Postgres opt-in via `DATABASE_URL`; Redis opcional

### Cache de prompt cross-provider

Requisições determinísticas (`temperature=0` ou `seed` fixada) são servidas do cache em repetições — funciona em **todos** os providers, não só Anthropic. O backend é Redis se `REDIS_URL` estiver definido, caso contrário um LRU in-process. Cache hits voltam instantaneamente com `x-orca-cache: HIT` e custam $0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # mesmo payload de novo
HTTP/1.1 200 OK
x-orca-cache: HIT          ← servido do cache, sem chamada upstream
```

### Widget de economias

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` reporta quanto seu tráfego teria custado em sempre-GPT-4 versus o que custou de fato. O dashboard mostra como um tile.

### Integrações

Configurações drop-in para [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) e qualquer ferramenta que fale o protocolo OpenAI Chat Completions. Veja [`integrations/`](./integrations/).

## O que deliberadamente não tem

Esta é a edição **single-workspace**. Por design, sem:
- multi-tenancy, RBAC, SSO
- faturamento, wallets, pontos, programa de parceiros
- console admin, logs de auditoria, trust & safety
- deploy multi-pod / Kubernetes
- e-mail / Slack / webhooks para alertas

Para isso, veja o produto hospedado ou a (futura) edição Teams.

## Testes

Construído test-first. Cada comportamento entregue aqui teve antes um teste falhando.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Slice | Testes | O quê |
|---|---|---|
| 1. Config | 5 | carregamento de env, defaults, `env_provider_keys()` |
| 2. Seed | 3 | bootstrap workspace + chave API + RoutingConfig, idempotente |
| 3. Middleware de auth | 4 | validação de bearer-token, 401 em ausente/inválido |
| 4. App factory | 3 | /health, envelope de erro, gating /v1/* |
| 5. CRUD de chaves de provider | 5 | criptografado em repouso, plaintext nunca faz round-trip |
| 6. Cache do router | 13 | montagem de deployment env+DB+hospedado com precedência |
| 7. Chat completion | 5 | formato OpenAI, RequestLog, validação |
| 8. Analytics | 4 | recent / spend / latency p50/p99 |
| 9. /v1/{models,keys,routing} | 8 | list/create/revoke + atualização de estratégia |
| 10. Streaming | 4 | formato SSE, sentinel `[DONE]`, log writeback |
| 11. Catálogo | 7 | 100+ modelos, flags de capacidade, pricing |
| 12. `model="auto"` | 21 | detecção de capacidade, mais-barato-que-atende (unit + integração) |
| 13. Economia de custo | 9 | economias vs baseline sempre-GPT-4 + comparação hosted-auto |
| 14. Cache de prompt | 15 | cache exact-match cross-provider + integração chat |
| 15. Benchmark | 4 | agregação summarize() + render_markdown() |
| 16. Status do hospedado | 7 | `/v1/hosted` config-source + superfície da URL de signup |
| 17. Economias hosted-auto | 3 | edge cases de `_hosted_auto_savings` em catálogos sintéticos |
| 18. Modelos inalcançáveis | 7 | o tile "modelos que você não pode alcançar" se esvazia quando hosted está ligado |
| **Total** | **127** | |

## Arquitetura

```
app/
├── main.py             FastAPI factory + lifespan + SPA mount
├── config.py           Settings (~15 fields)
├── deps.py             DI helpers
├── seed.py             First-run bootstrap
├── auto_routing.py     model="auto" capability + cost scoring
├── router_cache.py     Single-workspace router
├── prompt_cache.py     Cross-provider exact-match cache (Redis or in-memory LRU)
├── schemas.py          OpenAI-compatible request schema
├── middleware/auth.py  sk-orca-* validation
└── routes/
    ├── chat.py         /v1/chat/completions  (blocking + streaming)
    ├── models.py       /v1/models
    ├── providers.py    BYOK CRUD
    ├── routing.py      strategy config
    ├── analytics.py    recent / spend / latency / savings / unreachable
    ├── keys.py         list / rotate / revoke API keys
    ├── hosted.py       /v1/hosted — hosted-fallback status for the dashboard
    └── health.py

packages/
├── litellm_adapter/    Router wrapper + 100+ model catalog
├── auth/               hashing + AES-256-GCM
└── db/                 models + engine + session
```

## Roadmap

- [x] Chat completions compatíveis com OpenAI
- [x] Streaming (SSE)
- [x] Roteamento `model="auto"` mais-barato-capaz
- [x] Hospedado-como-upstream
- [x] BYOK criptografado em repouso
- [x] Dashboard de analytics local
- [x] CI (GitHub Actions)
- [x] Caching de prompt cross-provider
- [x] Integrações Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Benchmark público + reivindicação de economia
- [ ] Proxy de embeddings + image-gen

Veja [DEMO.md](./DEMO.md) para o demo de failover.

## Licença

MIT. Veja [LICENSE](./LICENSE).
