#OrcaRouter Lite

**Roteador LLM auto-hospedado com rede de segurança gerenciada.**
Compatível com OpenAI. OK. Espaço de trabalho único. Transmissão. `modelo="auto"`.

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![testes](https://img.shields.io/badge/tests-127_passing-brightgreen)](#testing)
[![modelos](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![licença](https://img.shields.io/badge/license-MIT-blue)](#license)

## Idiomas

- [Inglês](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [Alemão](./README.de.md)
- [Français](./README.fr.md)
- [Espanhol](./README.es.md)
- [Italiano](./README.it.md)
- [Русский](./README.ru.md)
- [Português](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

OrcaRouter Lite é a edição de código aberto de espaço de trabalho único do [OrcaRouter](https://www.orcarouter.ai). Execute-o em seu laptop, envie-o em seu produto ou use `api.orcarouter.ai` hospedado diretamente para a longa lista de modelos para os quais você não deseja gerenciar chaves.

> **Por que nós?** LiteLLM é uma biblioteca; OpenRouter é hospedado em código fechado; Ollama é apenas local. Somos o **servidor auto-hospedado com substituto gerenciado** — uma frase que nenhum deles pode dizer.

## início rápido de 60 segundos

Duas maneiras de usar o OrcaRouter:

### Caminho A — Auto-hospedado (BYOK)

Execute o Lite em sua própria máquina; traga suas próprias chaves de provedor.

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

URL base: `http://localhost:8000/v1`. Use a tecla `sk-orca-*` impressa na inicialização.

### Caminho B — Hospedado (é necessária uma conta)

Sem clone, sem janela de encaixe. Registre-se, obtenha uma chave, aponte qualquer OpenAI SDK hospedado.

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**Conta necessária.** O Hosted lida com roteamento, cobrança e a longa cauda de provedores – cobrado por token em sua conta OrcaRouter. Consulte [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction).

### Em seguida, chame-o de qualquer OpenAI SDK

Os exemplos abaixo usam o URL base do host local do Caminho A - troque por `https://api.orcarouter.ai/v1` se você estiver no Caminho B.

<detalhes>
<summary><b>Python</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="sk-orca-abc123...",
)
r = client.chat.completions.create(
    model="auto",  # or "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
    messages=[{"role": "user", "content": "Hello!"}],
)
print(r.choices[0].message.content)
```
</detalhes>

<detalhes>
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
</detalhes>

<detalhes>
<summary><b>curl</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</detalhes>

Abra `http://localhost:8000/` para o painel – provedores, roteamento, análises, chaves (somente caminho A).

## Por que?

| | Leve | Biblioteca LiteLLM | OpenRouter | Ollama |
|---|---|---|---|---|
| Servidor auto-hospedado | ✓ | como biblioteca | ✗ | ✓ |
| Compatível com OpenAI | ✓ | ✓ | ✓ | ✓ |
| Multiprovedor (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
| Painel integrado | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (capacidade mais barata) | ✓ | ✗ | ✗ | n/a |
| Transmissão | ✓ | ✓ | ✓ | ✓ |
| BYOK | ✓ | ✓ | ✗ | n/a |
| Hospedado como substituto | ✓ | ✗ | n/a | ✗ |
| Não é necessário Postgres / Redis | ✓ | n/a | n/a | ✓ |

## `model="auto"` — o recurso do título

Envie `model="auto"` e o OrcaRouter escolhe o modelo **mais barato** em seus provedores configurados que atenda aos requisitos de capacidade da solicitação (ferramentas, visão, modo JSON). Sem regras de roteamento manual; sem ginástica com limite de taxa; não `if x: ...` otimização de custos em seu código.

```python
client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": "What's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:..."}},
    ]}],
)
# → routes to the cheapest VISION-capable model your keys cover
```

O modelo resolvido é exposto de volta aos chamadores por meio do cabeçalho de resposta `x-orca-resolved-model` para que você possa registrar/exibir o que foi realmente usado.

## Hospedado como upstream (Lite + hospedado)

Já está executando o Lite? Defina `ORCAROUTER_API_KEY` como seu `sk-orca-*` em [www.orcarouter.ai](https://www.orcarouter.ai), e hospedado se torna mais um provedor na cadeia de roteamento — cobrindo modelos que suas chaves locais não cobrem:

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

Casos de uso:
- **Experimente antes de comprar** — não são necessárias chaves de provedor local
- **Registro local** — hospedado controla o roteamento, o Lite armazena linhas RequestLog para o painel
- **Failover** — os provedores locais falham, hospedado é a rede de segurança

## Transmissão

Formato SSE compatível com OpenAI com o enquadramento padrão `data: ... \n\n` e um terminal `[DONE]` sentinela - drop-in para qualquer SDK que já transmita do OpenAI.

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## Catálogo de modelos

Mais de 100 modelos de chat são carregados na inicialização do [banco de dados de preços mantido pela comunidade do LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — nenhuma lista de modelos para manter manualmente. Cada entrada expõe:

- `id` (por exemplo, `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mapeado para suas chaves configuradas)
- Sinalizadores de capacidade: `supports_tools`, `supports_vision`, `supports_json_mode`
- Custo de entrada/saída por token (aciona o widget de economia + `model="auto"`)

`GET /v1/models` retorna o catálogo no formato OpenAI.

## Implante em outro lugar

| Plataforma | Um clique |
|---|---|
| Ferrovia | [![Implantar na ferrovia](https://railway.app/button.svg)](https://railway.app/new/template) |
| Voar.io | `fly launch --dockerfile Dockerfile` |
| Renderizar | Conecte o repositório, root dir = `.` |
| Docker nu | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (imagem em breve) |

## O que há na caixa

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache de prompt entre provedores
- `GET /v1/models` — catálogo de modelos detectáveis ​​(mais de 100 modelos de `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — definir/listar/revogar chaves criptografadas do provedor
- `GET/PUT /v1/routing` — mudança de estratégia (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET /v1/analytics/{recent,spend,latency, saving,unreachable}` — análise local, nenhuma telemetria sai da caixa
- `GET /v1/hosted` — status de fallback hospedado (aciona o cartão "Ganhe US$ 5 de crédito grátis" do painel)
- `GET/POST/DELETE /v1/keys/...` — listar/girar/revogar chaves de API
- Painel de página única em `/`
- SQLite por padrão; Aceitação do Postgres via `DATABASE_URL`; Redis opcional

### Cache de prompt entre provedores

Solicitações determinísticas (`temperatura = 0` ou `seed` fixada) são atendidas a partir do cache repetidamente - funcionam em **todos** provedores, não apenas na Anthropic. O back-end é Redis quando `REDIS_URL` está definido, caso contrário, LRU em processo. Os acessos ao cache retornam instantaneamente com `x-orca-cache: HIT` e custam US$ 0.

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### Widget de economia

`GET /v1/analytics/ savings?baseline=gpt-4o&days=7` informa quanto seu tráfego teria custado no Always-GPT-4 versus quanto realmente custaria. O painel mostra isso como um bloco.

### Integrações

Configurações drop-in para [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) e qualquer ferramenta que fale o protocolo OpenAI Chat Completions. Veja [`integrações/`](./integrations/).

## O que deliberadamente não é

Esta é a edição **espaço de trabalho único**. Por design, não:
- multilocação, RBAC, SSO
- faturamento, carteiras, pontos, programa de parceria
- console de administração, registros de auditoria, confiança e segurança
- implantação de vários pods / Kubernetes
- email / Slack / webhooks para alertas

Para aqueles, consulte o produto hospedado ou a edição (próxima) do Teams.

## Teste

Teste construído primeiro. Cada comportamento enviado aqui teve primeiro um teste com falha.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 127 passed
```

| Fatia | Testes | O que |
|---|---|---|
| 1. Configuração | 5 | carregamento de env, padrões, `env_provider_keys()` |
| 2. Semente | 3 | espaço de trabalho bootstrap + chave API + RoutingConfig, idempotente |
| 3. Middleware de autenticação | 4 | validação de token de portador, 401 em falta/inválido |
| 4. Fábrica de aplicativos | 3 | /health, envelope de erro, /v1/* gate |
| 5. Chaves do provedor CRUD | 5 | criptografado em repouso, texto simples nunca faz ida e volta |
| 6. Cache do roteador | 13 | env+DB+assembly de implantação hospedado com precedência |
| 7. Conclusão do bate-papo | 5 | Formato OpenAI, RequestLog, validação |
| 8. Análise | 4 | recente / gasto / latência p50/p99 |
| 9. /v1/{modelos,chaves,roteamento} | 8 | listar/criar/revogar + atualização de estratégia |
| 10. Transmissão | 4 | Formato SSE, sentinela `[DONE]`, writeback de log |
| 11. Catálogo | 7 | Mais de 100 modelos, sinalizadores de capacidade, preços |
| 12. `modelo="auto"` | 21 | detecção de capacidade, necessidades de atendimento mais barato (unidade + integração) |
| 13. Economia de custos | 9 | economia versus linha de base sempre GPT-4 + comparação automática hospedada |
| 14. Cache de prompt | 15 | cache de correspondência exata entre provedores + integração de chat |
| 15. Referência | 4 | resume() + render_markdown() agregação |
| 16. Status hospedado | 7 | `/v1/hosted` fonte de configuração + superfície de URL de inscrição |
| 17. Economia em automóveis hospedados | 3 | Casos extremos `_hosted_auto_ savings` em catálogos sintéticos |
| 18. Modelos inacessíveis | 7 | O bloco "modelos que você não pode alcançar" é limpo quando hospedado está ativado |
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

## Roteiro

- [x] Conclusões de bate-papo compatíveis com OpenAI
- [x] Transmissão (SSE)
- [x] `model="auto"` roteamento com capacidade mais barata
- [x] Hospedado como upstream
- [x] BYOK criptografado em repouso
- [x] Painel de análise local
- [x] CI (ações do GitHub)
- [x] Cache de prompt entre provedores
- [x] Integrações Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK
- [x] Referência pública + reivindicação de poupança
- [] Embeddings + proxy de geração de imagem

Consulte [DEMO.md](./DEMO.md) para ver a demonstração de failover.

## Licença

MIT. Consulte [LICENÇA](./LICENSE).
