# OrcaRouter Lite

**すべてのコーディングエージェントに予算を。**
Claude Code、Codex、Gemini CLI、OpenCode、そして自作アプリの支出を、あらゆるモデルプロバイダーを横断して確認し、上限を設定できます。
プロンプトが手元のマシンから外に出ることはありません。開発者 1 人ならメニューバーアプリとして、
チーム全体ならセルフホスト型ルーターとして使えます。MIT ライセンスです。

[![ci](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/ci.yml)
[![desktop](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml/badge.svg)](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
[![ライセンス](https://img.shields.io/badge/license-MIT-blue)](#license)

<p>
  <img src="docs/screenshots/desktop-panel.png" alt="OrcaRouter Lite のメニューバーパネル: 1 日の予算に対する今日の支出、接続中のコーディングエージェント、プロバイダーの稼働状況" width="340">
  <img src="docs/screenshots/desktop-setup.png" alt="初回セットアップ: 検出されたコーディングエージェント、リクエストの送信先、1 日の予算" width="420">
</p>

## 言語

- [英語](./README.md)
- [日本語](./README.ja.md)
- [中文](./README.zh.md)
- [한국어](./README.ko.md)
- [ドイツ語](./README.de.md)
- [フランス語](./README.fr.md)
- [スペイン語](./README.es.md)
- [イタリア語](./README.it.md)
- [Русский](./README.ru.md)
- [ポルトガル語](./README.pt.md)
- [Tiếng Việt](./README.vi.md)
- [हिन्दी](./README.hi.md)

**関連プロダクト：**[すべてのモデル API](https://www.orcarouter.ai/models) · [OrcaCode Review](https://www.orcarouter.ai/code-review) · [OrcaReplay](https://github.com/Continuum-AI-Corp/OrcaReplay) · [OrcaPromptVault](https://github.com/Continuum-AI-Corp/OrcaPromptVault)

OrcaRouter Lite は [OrcaRouter](https://www.orcarouter.ai) のオープンソース版です。手元のコンピューターでもサーバーでも動作し、OpenAI・Anthropic・Gemini の API に対応します。また、障害時や、キーを持っていないモデルを使うときのセーフティネットとして、ホスト型の `api.orcarouter.ai` を利用できます。

**OrcaRouter** は Lite のセーフティネットを支えるホスト型ゲートウェイです。1 つのキーですべてのモデルを使え、プロバイダー間でフェイルオーバーし、まずは無料モデルから始められ、有料モデルはリクエストごとの支払いです。デスクトップアプリは最初にこれを提案し、エージェントを無料モデルで開始します。自分のプロバイダーキーも、OrcaRouter の有無にかかわらず、完全な代替手段として使えます。

## デスクトップアプリ

Orca アプリはメニューバーに常駐します。ルーターを `127.0.0.1` で起動し、コーディングエージェントを
そこに接続して、各エージェントの支出を表示します。

- **今日の支出をエージェント別に。** 今日の合計は時計の横に表示され、パネルではエージェントごとの内訳を確認できます。毎週月曜日には 1 週間のまとめを通知します。
- **1 日の予算。** 設定した金額の 80% と 100% に達すると通知します。デフォルトではアラートのみで、チェックボックスを 1 つオンにすると、上限に達した時点で Orca がコーディングエージェントを一時停止します。
- **ワンクリック接続。** Orca がエージェント自身の設定を書き換え、バックアップを取っておき、接続を解除すると元に戻します。
- **止まらない。** プロバイダーで障害が起きたりレート制限に達したりすると、リクエストは別のプロバイダーまたはホスト型 OrcaRouter にフォールバックし、アプリは救済したリクエストの数を記録します。アカウントは `orca link --key sk-orca-…` またはセットアップ画面で連携できます。
- **デフォルトでプライベート。** プロンプトはエージェントから選択したプロバイダーへ直接送られます。テレメトリはありません。
- **チームのゲートウェイでも使える。** `orca login https://ai-gw.example.com --key …`（またはセットアップの "Join my company's gateway"）で、プラットフォームチームが運用するゲートウェイにエージェントを向けます。`orca logout` で元に戻ります。

**インストール。** インストーラー（`.dmg`、`.deb`、`.AppImage`、`.msi`）は
[`desktop.yml`](./.github/workflows/desktop.yml) でビルドされ、次のタグ付きバージョン以降の各リリースに
添付されます。それまでは、同じエンジンと CLI をコマンド 1 つで使えます:

**必要なのはアプリだけ:** エンジンとローカルの SQLite ファイルを内蔵しているので、サーバーやデータベースの用意は不要です。ダウンロード、初回起動、ログイン時の起動、アンインストールは [INSTALL.md](./INSTALL.md)（英語）を参照してください。

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca up
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca connect claude-code
```

```bash
uvx --from git+https://github.com/Continuum-AI-Corp/OrcaRouter-Lite orca status
```

`orca up` はパネルを `http://127.0.0.1:8765/desktop/panel.html` で配信します。
メニューバーアプリ本体のビルド方法は [`desktop/`](./desktop/README.md) を参照してください。最初のリリースが出たら、
macOS ユーザーは `brew install --cask continuum-ai-corp/tap/orcarouter-lite` でもインストールできます。

Claude Code のステータスバーに今日の支出を表示するには、`~/.claude/settings.json` に次を追加します。

```json
"statusLine": { "type": "command", "command": "orca statusline" }
```

`orca report` はその週の内容を Markdown（または `--format csv`）で出力するので、チャットやスプレッドシートにそのまま貼り付けられます。

| エージェント | 接続方法 |
|---|---|
| Claude Code | 自動: `~/.claude/settings.json` に `ANTHROPIC_BASE_URL` と専用キーを設定 |
| Codex | 自動: `~/.codex/config.toml` に `orca` プロバイダー（Responses API）を追加し、`model = "auto"` で選択 |
| Gemini CLI | 自動: `~/.gemini/.env` に `GOOGLE_GEMINI_BASE_URL` と専用キーを、`~/.gemini/settings.json` に Gemini CLI のゲートウェイ サインインを設定 |
| OpenCode | 自動: `~/.config/opencode/opencode.json` に `orca` プロバイダーを追加して `orca/auto` を選択。キーは OpenCode が読み取る非公開ファイルに保存 |
| Command Code | 自動: `~/.commandcode/providers.json` に `orca` プロバイダーを追加。キーは非公開ファイルから読み込み（Command Code はこのファイルに生のキーを書くことを受け付けないため） |
| Cline | 貼り付け 1 回: Cline で API Provider → OpenAI Compatible を選び、アプリが表示するベース URL とキーを貼り付け |
| Aider | 自動: `~/.aider.conf.yml` に `openai-api-base`、専用キー、`model: openai/auto` を設定 |
| Cursor | 貼り付け 1 回: Cursor のモデル設定に入力するベース URL とキーをアプリが表示 |
| Hermes Agent | 自動: `~/.hermes/config.yaml` (Windows: `%LOCALAPPDATA%\hermes`) → `providers.orca`, `model.provider: custom:orca` |
| Pi | 自動: `~/.pi/agent/models.json` → `providers.orca`; `settings.json` → `defaultProvider: orca`, `defaultModel: auto` |
| OMP | 自動: `~/.omp/agent/models.yml` → `providers.orca`; `config.yml` → `modelRoles.default: orca/auto` |
| Kilo Code | 自動: `~/.config/kilo/kilo.json` → `provider.orca`, `model: orca/auto` (`{file:…}` key) |
| OpenClaw | 自動: `~/.openclaw/openclaw.json` → `models.providers.orca`, `agents.defaults.model.primary: orca/auto` |
| Kimi Code | 自動: `~/.kimi-code/config.toml` → `[providers.orca]`, `[models.orca-auto]`, `default_model` |
| Goose | 自動: `~/.config/goose/custom_providers/orca.json` (`auth.command` key) + `config.yaml` → `GOOSE_PROVIDER: orca` |
| Zed | 貼り付け 1 回: `settings.json` → `language_models.openai_compatible.Orca` (`api_url`, model `auto`) + key in Zed / `ORCA_API_KEY` |
| OpenHands | 貼り付け 1 回: `/settings` → Advanced: model `openai/auto`, base URL, key |
| DeepSeek Harness | 貼り付け 1 回: Settings → Models → custom OpenAI-compatible provider, model `auto` |
| ZCode | 貼り付け 1 回: Add provider → Create custom provider → OpenAI chat completions, model `auto` |

接続した各エージェントには専用のキーが割り当てられます。これによってエージェントごとに支出を分けられ、
接続を解除すると即座にアクセスが取り消されます。アプリがコンピューター上で触れる可能性のある範囲は
[SECURITY.md](./SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch) に明記しています。

<a id="free-and-open-for-good"></a>
## ずっと無料でオープン

- **永続的に MIT。** 開発者 1 人、チーム 1 つに必要なものはすべて、MIT ライセンスのままこのリポジトリに残ります: ルーティング、`model="auto"`、予算、ダッシュボード、デスクトップアプリ。Lite の機能を有料プランに移すことはありません。
- **有料版は組織向け。** 複数チームの統制（SSO/SCIM、ロールベースのアクセス制御、組織全体の予算とポリシー、監査ログの保持、Slack やメールへのアラート）は [ホスト型 OrcaRouter](https://www.orcarouter.ai) で提供します。
- **検証可能。** リリースは署名済みで、来歴情報（provenance）と SBOM が付属します。[SECURITY.md](./SECURITY.md) を参照してください。

## 比較

| | 向いている用途 | 動作形態 |
|---|---|---|
| **OrcaRouter Lite** | 新たなインフラなしで、エージェント別の支出、予算、フェイルオーバーが欲しい個人開発者からチームまで | デスクトップアプリ、`uvx`/`pip`、または Docker。デフォルトは SQLite |
| LiteLLM proxy | 豊富な設定項目と Python SDK が欲しいチーム | セルフホスト型サーバー。支出の追跡には Postgres |
| OpenRouter | 1 つの API キーで多数のモデルを使いたい場合（請求は OpenRouter から） | ホスト型のみ。プロンプトは OpenRouter のサービスを経由 |
| Claude Code 自体のゲートウェイ対応 | Claude だけを使う企業 | 自前で運用するゲートウェイに Claude Code を向ける。Claude モデルのみ |

## サーバーとして動かす（60 秒）

OrcaRouter を使用する 2 つの方法:

### パス A — セルフホスト型 (BYOK)

自分のマシンで Lite を実行します。独自のプロバイダー キーを持参してください。

```bash
git clone https://github.com/Continuum-AI-Corp/OrcaRouter-Lite.git
cd OrcaRouter-Lite
cp .env.example .env
# add at least one: OPENAI_API_KEY=sk-...  (or ORCAROUTER_API_KEY=...)

docker compose up
# logs: ✓ orcarouter-lite ready. API key: sk-orca-abc123...
```

ベース URL: `http://localhost:8000/v1`。起動時に出力される `sk-orca-*` キーを使用します。

### パス B — ホスト型 (アカウントが必要)

クローンもドッカーもありません。登録し、キーを取得し、ホストされた OpenAI SDK を指定します。

```bash
# 1. Register at https://www.orcarouter.ai and copy your sk-orca-* key
# 2. Use https://api.orcarouter.ai/v1 as the base URL
```

**アカウントが必要です。** まずは無料モデルから。有料モデルは OrcaRouter アカウントでリクエストごとに請求されます。Hosted はルーティング、プロバイダー間のフェイルオーバー、モデルのロングテールを処理します。[docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction) を参照してください。

### 次に、任意の OpenAI SDK から呼び出します。

以下の例では、パス A のローカルホストのベース URL を使用しています。パス B を使用している場合は、「https://api.orcarouter.ai/v1」に置き換えてください。

<details>
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
<summary><b>カール</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</details>

ダッシュボードの「http://localhost:8000/」を開きます (プロバイダー、ルーティング、分析、キー (パス A のみ))。

## `model="auto"`

`model="auto"` を送信すると、OrcaRouter は、リクエストの機能要件 (ツール、ビジョン、JSON モード) を満たす構成済みプロバイダーの中で **最も安価** のモデルを選択します。手動ルーティング ルールはありません。レートリミットの体操はありません。コード内の「if x: ...」コストの最適化はありません。

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

解決されたモデルは「x-orca-resolved-model」応答ヘッダーを介して呼び出し元に公開されるため、実際に使用されたものをログ/表示できます。

## アップストリームとしてホスト (ライト + ホスト)

すでに Lite を実行していますか? [www.orcarouter.ai](https://www.orcarouter.ai) から `ORCAROUTER_API_KEY` を `sk-orca-*` に設定すると、hosted はルーティング チェーン内のもう 1 つのプロバイダーになります。ローカル キーに含まれないモデルをカバーします。

```bash
# .env
ORCAROUTER_API_KEY=sk-orca-hosted-abc...
```

使用例:
- **無料で始める** — 無料モデルにはプロバイダーキーは不要です。有料モデルは自分で選んだときだけ使われます
- **ローカル ログ** - ホストされたルーティング処理、Lite はダッシュボードの RequestLog 行を保存します
- **フェイルオーバー** — ローカルプロバイダーに障害が発生し、ホストされているのがセーフティネットです

## ストリーミング

標準の `data: ... \n\n` フレーミングとターミナル `[DONE]` センチネルを備えた OpenAI 互換の SSE 形式 — OpenAI からすでにストリーミングしている SDK のドロップイン。

```python
for chunk in client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Tell me a story"}],
    stream=True,
):
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

## ネイティブ プロトコル エンドポイント (Anthropic + Gemini)

Lite は 1 つのルーティング パイプラインに対して 3 つのインバウンド プロトコルを話します。Anthropic または Gemini のワイヤー フォーマットしか話さないクライアントも直接接続できます。OpenAI SDK は不要です:

```bash
# Claude Code, pointed at Lite (no /v1 suffix in the base URL)
export ANTHROPIC_BASE_URL=http://localhost:8000
export ANTHROPIC_API_KEY=sk-orca-...
claude
```

```python
# google-genai SDK, pointed at Lite
from google import genai
from google.genai.types import HttpOptions
client = genai.Client(api_key="sk-orca-...",
                      http_options=HttpOptions(base_url="http://localhost:8000"))
client.models.generate_content(model="auto", contents="Hello!")
```

リクエストはエッジで同じ内部パイプラインに変換されるため、`model="auto"`、クロスプロバイダー プロンプト キャッシュ (プロトコル間で共有)、ルーティング戦略、分析ダッシュボードはすべて同じように機能します。ガイド: [integrations/claude-code.md](./integrations/claude-code.md)、[integrations/gemini-sdk.md](./integrations/gemini-sdk.md) を参照してください。

## モデルカタログ

100 を超えるチャット モデルが起動時に [LiteLLM のコミュニティが管理する価格設定データベース](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json) からロードされます。手動で管理するモデル リストはありません。各エントリは以下を公開します。

- `id` (例: `gpt-4o`、`claude-3-5-sonnet-latest`)
- `provider` (設定されたキーにマッピングされます)
- 機能フラグ: `supports_tools`、`supports_vision`、`supports_json_mode`
- トークンごとの入出力コスト (節約ウィジェット + `model="auto"` を推進)

`GET /v1/models` returns the OpenAI-format catalogue.

## 別の場所にデプロイする

| プラットフォーム | 方法 |
|---|---|
| Docker | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/continuum-ai-corp/orcarouter-lite:<version>`（次のタグ付きリリースから公開。[SECURITY.md](./SECURITY.md) のコマンドで検証できます） |
| Render | [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Continuum-AI-Corp/OrcaRouter-Lite): [`render.yaml`](./render.yaml) を使用し、シークレットを生成、データベースはディスク上に保持 |
| Fly.io | `fly launch --no-deploy`、次に [`fly.toml`](./fly.toml) 冒頭にあるボリュームと `fly secrets set` の手順、最後に `fly deploy` |
| Railway | `railway init`、`railway volume add --mount-path /data`、`railway variables --set CREDENTIAL_ENCRYPTION_KEY=$(openssl rand -hex 32) --set API_KEY_PEPPER=$(openssl rand -hex 32) --set DATABASE_URL=sqlite+aiosqlite:////data/orca.db`、最後に `railway up`（[`railway.json`](./railway.json) でビルド） |

## 箱の中身は何ですか

- `POST /v1/chat/completions` — プロキシ + ストリーミング + `model="auto"` + クロスプロバイダー プロンプト キャッシュ
- `POST /v1/messages` — **Anthropic Messages API イングレス** (Claude Code / Anthropic SDK が直接接続。`+ /count_tokens`)
- `POST /v1/responses` — **OpenAI Responses API イングレス** (Codex と Responses SDK クライアント向け。ストリーミング、function ツール、custom ツールに対応)
- `POST /v1beta/models/{model}:generateContent` — **Gemini API イングレス** (google-genai SDK が直接接続。`+ :streamGenerateContent`、`GET /v1beta/models`)
- `GET /v1/models` — 検出可能なモデル カタログ (`litellm.model_cost` からの 100 以上のモデル)
- `GET/PUT/DELETE /v1/providers/{provider}` — 暗号化されたプロバイダー キーを設定 / リスト / 取り消し
- `GET/PUT /v1/routing` — 戦略の変更 (`バランス` / `最安` / `最速` / `品質`)
- `GET /v1/analytics/{recent,spend,latency, Savingss,unreachable}` — ローカル分析、テレメトリはボックスから出ません
- `GET /v1/hosted` — ホスト型ゲートウェイのステータス (ダッシュボードの OrcaRouter カードを駆動します)
- `GET/POST/DELETE /v1/keys/...` — API キーのリスト化、回転、取り消し
- `/v1/app/*` — デスクトップアプリ用のエージェント、支出サマリー、予算（`orca up` で起動した場合のみ。[SECURITY.md](./SECURITY.md) を参照）
- `/` の単一ページのダッシュボード
- デフォルトでは SQLite。 Postgres は「DATABASE_URL」経由でオプトインします。 Redis はオプション

### クロスプロバイダープロンプトキャッシュ

確定的なリクエスト (「温度=0」または固定された「シード」) はキャッシュから繰り返し処理されます。これは、Anthropic だけでなく **すべて** プロバイダーにわたって機能します。 「REDIS_URL」が設定されている場合はバックエンドが Redis で、それ以外の場合はインプロセス LRU です。キャッシュ ヒットは「x-orca-cache: HIT」で即座に返され、コストは $0 です。

```bash
$ curl ... -d '{"model":"auto","messages":[...], "temperature": 0}' -i
HTTP/1.1 200 OK
x-orca-cache: MISS
x-orca-resolved-model: gpt-4o-mini

$ curl ...  # same payload again
HTTP/1.1 200 OK
x-orca-cache: HIT          ← served from cache, no upstream call
```

### 節約ウィジェット

`GET /v1/analytics/savings?baseline=gpt-4o&days=7` reports what your traffic would have cost on always-GPT-4 vs what it actually cost. The dashboard shows it as a tile.

### 統合

[Claude Code](./integrations/claude-code.md)、[Gemini SDK](./integrations/gemini-sdk.md)、[Continue.dev](./integrations/continue.json)、[Aider](./integrations/aider.md)、[Cursor](./integrations/cursor.md)、[LangChain](./integrations/langchain_orcarouter.py)、[LlamaIndex](./integrations/llamaindex_orcarouter.py)、[Vercel AI SDK](./integrations/vercel_ai.ts)、および OpenAI Chat Completions プロトコルを使用するツール向けのドロップイン構成 — さらにネイティブの Anthropic および Gemini ワイヤー フォーマットにも対応します。 [`integrations/`](./integrations/) を参照してください。

## 意図的にそうでないもの

これは **単一ワークスペース** エディションです。設計上、いいえ:
- マルチテナント、RBAC、SSO
- 請求、ウォレット、ポイント、パートナー プログラム
- 管理コンソール、監査ログ、信頼性と安全性
- マルチポッド展開 / Kubernetes
- アラート用の電子メール / Slack / Webhook

これらは組織向けの機能で、[ホスト型 OrcaRouter](https://www.orcarouter.ai) で提供しています。[ずっと無料でオープン](#free-and-open-for-good) を参照してください。

## テスト

テストファーストで構築しています: ここに含まれるすべての動作には、先に失敗するテストがありました。

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest                          # router, protocols, desktop API, CLI, supply-chain checks
cd desktop && npm test                       # desktop view logic (node --test)
cd desktop/src-tauri && cargo test --lib     # menu-bar title and notification rules
```

## アーキテクチャ

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

## ロードマップ

- [x] OpenAI 互換のチャット補完、ストリーミング、`model="auto"`
- [x] Anthropic と Gemini のネイティブエンドポイント
- [x] ホスト型アップストリームへのフォールバック、暗号化された BYOK、ローカルダッシュボード
- [x] プロバイダー横断のプロンプトキャッシュ
- [x] デスクトップアプリ: メニューバーでの支出表示、1 日の予算アラート、ワンクリックでのエージェント接続
- [x] 来歴情報と SBOM 付きの署名済みリリース、ハッシュで固定した依存関係
- [x] アラートを出すか、上限でコーディングエージェントを一時停止する 1 日の予算
- [x] `orca login` / "Join my company's gateway": アプリからチームのゲートウェイを利用
- [x] Codex を接続するための `/v1/responses`、Gemini CLI・OpenCode・Command Code・Cline にも対応
- [x] OS のキーチェーンに保存する暗号化キー、1 日 1 回の更新チェック
- [ ] 共有のチームゲートウェイで強制される開発者ごとの予算
- [ ] 埋め込み、Ollama/vLLM プロバイダー、カスタムフォールバックチェーン

フェイルオーバーのデモについては、[DEMO.md](./DEMO.md) を参照してください。

<a id="license"></a>
## ライセンス

MIT。[ライセンス](./LICENSE) を参照してください。
