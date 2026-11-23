# OrcaRouter Lite

**Coloque um orçamento em cada agente de código.**
Veja e limite quanto Claude Code, Codex, Gemini CLI, OpenCode e seus próprios apps gastam, em todos os provedores de modelos, sem que seus prompts saiam da sua máquina. Um app de barra de menus para um desenvolvedor, e um roteador self-hosted para um time inteiro. Licença MIT.

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="O painel do OrcaRouter Lite na barra de menus: gasto de hoje frente a um orçamento diário, agentes de código conectados e saúde dos provedores" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="Configuração inicial: agentes de código detectados, para onde vão as requisições e um orçamento diário" width="420">
</p>

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

**Encontre-nos:** [Todas as APIs de modelos](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite é a edição open source do [OrcaRouter](https://www.orcarouter.ai). Ele roda no seu computador ou no seu servidor, fala as APIs da OpenAI, da Anthropic e do Gemini, e pode usar o `api.orcarouter.ai` hospedado como rede de segurança para quedas e para modelos dos quais você não tem chaves.

## O app desktop

O app Orca fica na sua barra de menus. Ele roda o roteador em `127.0.0.1`, conecta seus agentes de código a ele e mostra quanto eles gastam.

- **Gasto de hoje, por agente.** O total do dia fica ao lado do relógio; o painel o divide por agente, e toda segunda-feira uma notificação resume a semana.
- **Um orçamento diário.** Notificações em 80% e 100% do valor que você definir. Por padrão, só alerta; marque uma caixa e o Orca pausa seus agentes de código quando o valor for atingido.
- **Conexão com um clique.** O Orca edita as configurações do próprio agente, guarda um backup e o restaura quando você desconecta.
- **Nunca fora do ar.** Quando um provedor falha ou aplica rate limit em você, as requisições fazem fallback para outro provedor ou para o OrcaRouter hospedado, e o app conta quantas ele salvou. Vincule sua conta com `orca link --key sk-orca-…` ou na configuração inicial.
- **Privado por padrão.** Os prompts vão direto dos seus agentes para o provedor que você escolher. Sem telemetria.
- **Funciona com o gateway do seu time.** `orca login https://ai-gw.example.com --key …` (ou "Join my company's gateway" na configuração inicial) aponta seus agentes para o gateway que o seu time de plataforma mantém; `orca logout` os restaura.

**Instalação.** Os instaladores (`.dmg`, `.deb`, `.AppImage`, `.msi`) são gerados pelo [`desktop.yml`](./.github/workflows/desktop.yml) e anexados a cada release, a partir da próxima versão com tag. Até lá, o mesmo engine e a mesma CLI estão a um comando de distância:

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` serve o painel em `http://127.0.0.1:8765/desktop/panel.html`; para buildar o app de barra de menus em si, veja [`desktop/`](./desktop/README.md). Assim que sair a primeira release, usuários de macOS também poderão rodar `brew install --cask continuum-ai-corp/tap/orcarouter-lite`.

O gasto de hoje na barra de status do Claude Code: adicione isto ao `~/.claude/settings.json`.

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` imprime a semana em Markdown (ou `--format csv`) para colar em um chat ou em uma planilha.

| Agente | Como se conecta |
|---|---|
| Claude Code | Automático: define `ANTHROPIC_BASE_URL` e uma chave dedicada em `~/.claude/settings.json` |
| Codex | Automático: adiciona um provedor `orca` (Responses API) em `~/.codex/config.toml` e o seleciona com `model = "auto"` |
| Gemini CLI | Automático: define `GOOGLE_GEMINI_BASE_URL` e uma chave dedicada em `~/.gemini/.env`, e o login via gateway do Gemini CLI em `~/.gemini/settings.json` |
| OpenCode | Automático: adiciona um provedor `orca` em `~/.config/opencode/opencode.json` e seleciona `orca/auto`; a chave fica em um arquivo privado que o OpenCode lê |
| Command Code | Automático: adiciona um provedor `orca` em `~/.commandcode/providers.json` cuja chave vem de um arquivo privado (o Command Code recusa chaves em texto puro ali) |
| Cline | Um passo de copiar e colar: escolha API Provider → OpenAI Compatible no Cline e cole a base URL e a chave que o app mostra |
| Aider | Automático: define `openai-api-base`, uma chave dedicada e `model: openai/auto` em `~/.aider.conf.yml` |
| Cursor | Um passo de copiar e colar: o app mostra uma base URL e uma chave para as configurações de modelo do Cursor |

Cada agente conectado recebe sua própria chave: é assim que o gasto é dividido por agente, e é por isso que desconectar revoga o acesso na hora. O que o app pode mexer no seu computador está detalhado em [SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch).

<a id="free-and-open-for-good"></a>
## Gratuito e aberto, para sempre

- **MIT, permanentemente.** Tudo o que um desenvolvedor ou um time precisa fica neste repositório sob MIT: roteamento, `model="auto"`, orçamentos, o dashboard, o app desktop. Não vamos mover nenhuma feature do Lite para um plano pago.
- **O pago é para organizações.** Governar muitos times (SSO/SCIM, controle de acesso baseado em papéis, orçamentos e políticas para toda a organização, retenção de auditoria, alertas para Slack e e-mail) fica no [OrcaRouter hospedado](https://www.orcarouter.ai).
- **Verificável.** As releases são assinadas e vêm com provenance e SBOM. Veja [SECURITY.md](./SECURITY.md).

## Como se compara

| | Ideal para | Como roda |
|---|---|---|
| **OrcaRouter Lite** | De um desenvolvedor a um time que quer gasto por agente, orçamentos e failover sem infraestrutura nova | App desktop, `uvx`/`pip` ou Docker; SQLite por padrão |
| LiteLLM proxy | Times que querem uma grande superfície de configuração e um SDK Python | Servidor self-hosted; Postgres para rastrear gastos |
| OpenRouter | Uma chave de API para muitos modelos, com cobrança feita por eles | Apenas hospedado; os prompts passam pelo serviço deles |
| Suporte nativo do Claude Code a gateways | Empresas que só usam Claude | Aponta o Claude Code para um gateway que você roda; apenas modelos Claude |

## Rode como servidor (60 segundos)

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

## `model="auto"`

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

## Endpoints de protocolo nativos (Anthropic + Gemini)

O Lite fala três protocolos de entrada sobre um único pipeline de roteamento. Clientes que só falam os wire formats da Anthropic ou do Gemini se conectam diretamente — sem necessidade de SDK OpenAI:

```bash
# Claude Code, apontado para o Lite (sem o sufixo /v1 na URL base)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# SDK google-genai, apontado para o Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

As requisições são traduzidas na borda para o mesmo pipeline interno, então `model="auto"`, o cache de prompt cross-provider (compartilhado entre protocolos), as estratégias de roteamento e o dashboard de analytics funcionam de forma idêntica. Guias: [integrations/claude-code.md](./integrations/claude-code.md), [integrations/gemini-sdk.md](./integrations/gemini-sdk.md).

## Catálogo de modelos

Mais de 100 modelos de chat são carregados na inicialização a partir do [banco de preços mantido pela comunidade do LiteLLM](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) — sem lista de modelos para manter manualmente. Cada entrada expõe:

- `id` (ex.: `gpt-4o`, `claude-3-5-sonnet-latest`)
- `provider` (mapeado para suas chaves configuradas)
- Flags de capacidade: `supports_tools`, `supports_vision`, `supports_json_mode`
- Custo por token de entrada/saída (alimenta o widget de economia + `model="auto"`)

`GET /v1/models` retorna o catálogo no formato OpenAI.

## Deploy em outro lugar

| Plataforma | Como |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>` (publicada a partir da próxima release com tag; verifique-a com os comandos do [SECURITY.md](./SECURITY.md)) |
| Render | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Continuum-AI-Corp/OrcaRouter-Lite): usa o [`render.yaml`](./render.yaml), gera os secrets, mantém o banco de dados em um disco |
| Fly.io | `fly launch --no-deploy`, depois os passos de volume e `fly secrets set` no topo do [`fly.toml`](./fly.toml), depois `fly deploy` |
| Railway | `railway init`, `railway volume add --mount-path /data`, `railway variables --set CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32) --set API_KEY_PEPPER=$(openssl rand -hex 32) --set DATABASE_URL=sqlite+aiosqlite:////data/orca.db`, depois `railway up` (faz o build com o [`railway.json`](./railway.json)) |

## O que vem na caixa

- `POST /v1/chat/completions` — proxy + streaming + `model="auto"` + cache de prompt cross-provider
- `POST /v1/messages` — **ingress da Anthropic Messages API** (Claude Code / SDKs Anthropic se conectam diretamente; `+ /count_tokens`)
- `POST /v1/responses` — **ingress da OpenAI Responses API** (Codex e clientes de SDKs da Responses API; streaming, ferramentas de função e personalizadas)
- `POST /v1beta/models/{model}:generateContent` — **ingress da Gemini API** (o SDK google-genai se conecta diretamente; `+ :streamGenerateContent`, `GET /v1beta/models`)
- `GET  /v1/models` — catálogo de modelos descobrível (100+ modelos de `litellm.model_cost`)
- `GET/PUT/DELETE /v1/providers/{provider}` — define / lista / revoga chaves de provider criptografadas
- `GET/PUT /v1/routing` — muda a estratégia (`balanced` / `cheapest` / `fastest` / `quality`)
- `GET  /v1/analytics/{recent,spend,latency,savings,unreachable}` — analytics locais, nenhuma telemetria sai da caixa
- `GET  /v1/hosted` — status do fallback hospedado (alimenta o card "Get $5 free credit" do dashboard)
- `GET/POST/DELETE /v1/keys/...` — lista / rotaciona / revoga chaves API
- `/v1/app/*` — agentes, resumo de gastos e orçamento para o app desktop (apenas quando iniciado com `orca up`; veja [SECURITY.md](./SECURITY.md))
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

Configurações drop-in para [Claude Code](./integrations/claude-code.md), [Gemini SDK](./integrations/gemini-sdk.md), [Continue.dev](./integrations/continue.json), [Aider](./integrations/aider.md), [Cursor](./integrations/cursor.md), [LangChain](./integrations/langchain_orcarouter.py), [LlamaIndex](./integrations/llamaindex_orcarouter.py), [Vercel AI SDK](./integrations/vercel_ai.ts) e qualquer ferramenta que fale o protocolo OpenAI Chat Completions — além dos wire formats nativos da Anthropic e do Gemini. Veja [`integrations/`](./integrations/).

## O que deliberadamente não tem

Esta é a edição **single-workspace**. Por design, sem:
- multi-tenancy, RBAC, SSO
- faturamento, wallets, pontos, programa de parceiros
- console admin, logs de auditoria, trust & safety
- deploy multi-pod / Kubernetes
- e-mail / Slack / webhooks para alertas

Esses são recursos para organizações e ficam no [OrcaRouter hospedado](https://www.orcarouter.ai); veja [Gratuito e aberto, para sempre](#free-and-open-for-good).

## Testes

Construído test-first: cada comportamento entregue aqui teve antes um teste falhando.

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

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

desktop/
├── ui/                 Menu-bar panel + setup pages (served by the engine at /desktop/)
├── src-tauri/          Native shell: tray title, notifications, starts the engine
└── engine/             PyInstaller build of the bundled `orca-engine`

packages/
├── desktop/            Agent connectors (backup/restore) + desktop home folder
├── litellm_adapter/    Router wrapper + 100+ model catalog
├── auth/               hashing + AES-256-GCM
└── db/                 models + engine + session
```

## Roadmap

- [x] Chat completions compatíveis com OpenAI, streaming, `model="auto"`
- [x] Endpoints nativos da Anthropic e do Gemini
- [x] Fallback hospedado-como-upstream, BYOK criptografado, dashboard local
- [x] Cache de prompt cross-provider
- [x] App desktop: gasto na barra de menus, alertas de orçamento diário, conexão de agentes com um clique
- [x] Releases assinadas com provenance e SBOM; dependências travadas por hash
- [x] Orçamento diário que alerta, ou pausa os agentes de código no limite
- [x] `orca login` / "Join my company's gateway": usar o gateway de um time pelo app
- [x] `/v1/responses`, para que o Codex se conecte; Gemini CLI, OpenCode, Command Code e Cline também
- [x] Chave de criptografia no keychain do sistema operacional; uma verificação de atualização por dia
- [ ] Orçamentos por desenvolvedor aplicados em um gateway compartilhado do time
- [ ] Embeddings, providers Ollama/vLLM, cadeias de fallback personalizadas

Veja [DEMO.md](./DEMO.md) para o demo de failover.

<a id="license"></a>
## Licença

MIT. Veja [LICENSE](./LICENSE).
