# OrcaRouter Lite

**マネージド セーフティ ネットを備えたセルフホスト型 LLM ルーター。**
OpenAI対応。ビヨク。単一のワークスペース。ストリーミング中。 `モデル="自動"`。

![OrcaRouter Lite Logo](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/design/OrcaRouter%20Lite.png?raw=true)

[![テスト](https://img.shields.io/badge/tests-403_passing-brightgreen)](#testing)
[![モデル](https://img.shields.io/badge/models-100%2B-blue)](#model-catalog)
[![ライセンス](https://img.shields.io/badge/license-MIT-blue)](#license)

![OrcaRouter Lite フェイルオーバーデモ](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/blob/main/demo.gif?raw=true)

*`model="auto"` がプロバイダー障害をリアルタイムで吸収 — コード変更なし。収録手順: [DEMO.md](./DEMO.md)。*

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

OrcaRouter Lite は、[OrcaRouter](https://www.orcarouter.ai) のオープンソースの単一ワークスペース エディションです。ラップトップで実行するか、製品に同梱するか、キーを管理したくないモデルのロングテールに対してホストされた「api.orcarouter.ai」を直接使用します。

> **なぜ当社なのか?** LiteLLM はライブラリです。 OpenRouter はクローズドソースでホストされています。オラマは地元限定です。私たちは**管理されたフォールバックを備えた自己ホスト型サーバー**です。これは誰にも言えない言葉です。

## 60 秒のクイックスタート

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

**アカウントが必要です。** Hosted はルーティング、請求、プロバイダーのロングテールを処理します。OrcaRouter アカウントのトークンごとに請求されます。 [docs.orcarouter.ai/introduction](https://docs.orcarouter.ai/introduction) を参照してください。

### 次に、任意の OpenAI SDK から呼び出します。

以下の例では、パス A のローカルホストのベース URL を使用しています。パス B を使用している場合は、「https://api.orcarouter.ai/v1」に置き換えてください。

<詳細>
<概要><b>Python</b></summary>

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

<詳細>
<概要><b>Node.js</b></summary>

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

<詳細>
<概要><b>カール</b></summary>

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-orca-abc123..." \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Hello!"}]}'
```
</details>

ダッシュボードの「http://localhost:8000/」を開きます (プロバイダー、ルーティング、分析、キー (パス A のみ))。

＃＃ なぜ？

| |ライト | LiteLLM ライブラリ |オープンルーター |オラマ |
|---|---|---|---|---|
|セルフホスト型サーバー | ✓ |図書館として | ✗ | ✓ |
| OpenAI対応 | ✓ | ✓ | ✓ | ✓ |
|マルチプロバイダー (OpenAI/Anthropic/Google/…) | ✓ | ✓ | ✓ | ✗ |
|内蔵ダッシュボード | ✓ | ✗ | ✓ | ✗ |
| `model="auto"` (最も安価な機能) | ✓ | ✗ | ✗ |該当なし |
|ストリーミング | ✓ | ✓ | ✓ | ✓ |
|ビヨク | ✓ | ✓ | ✗ |該当なし |
|フォールバックとしてホスト | ✓ | ✗ |該当なし | ✗ |
| Postgres や Redis は不要 | ✓ |該当なし |該当なし | ✓ |

## `model="auto"` — 見出し機能

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
- **購入前に試してください** — ローカルプロバイダーキーは必要ありません
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

|プラットフォーム |ワンクリック |
|---|---|
|鉄道 | [![鉄道へのデプロイ](https://railway.app/button.svg)](https://railway.app/new/template) |
|フライアイオ | `フライ起動 --dockerfile Dockerfile` |
|レンダリング |リポジトリに接続します。ルート ディレクトリ = `.` |
|ベア・ドッカー | `docker run -p 8000:8000 -e OPENAI_API_KEY=... ghcr.io/...` (イメージは近日公開予定) |

## 箱の中身は何ですか

- `POST /v1/chat/completions` — プロキシ + ストリーミング + `model="auto"` + クロスプロバイダー プロンプト キャッシュ
- `POST /v1/messages` — **Anthropic Messages API イングレス** (Claude Code / Anthropic SDK が直接接続。`+ /count_tokens`)
- `POST /v1beta/models/{model}:generateContent` — **Gemini API イングレス** (google-genai SDK が直接接続。`+ :streamGenerateContent`、`GET /v1beta/models`)
- `GET /v1/models` — 検出可能なモデル カタログ (`litellm.model_cost` からの 100 以上のモデル)
- `GET/PUT/DELETE /v1/providers/{provider}` — 暗号化されたプロバイダー キーを設定 / リスト / 取り消し
- `GET/PUT /v1/routing` — 戦略の変更 (`バランス` / `最安` / `最速` / `品質`)
- `GET /v1/analytics/{recent,spend,latency, Savingss,unreachable}` — ローカル分析、テレメトリはボックスから出ません
- `GET /v1/hosted` — ホスト型フォールバック ステータス (ダッシュボードの "Get $5 free Credit" カードを駆動します)
- `GET/POST/DELETE /v1/keys/...` — API キーのリスト化、回転、取り消し
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

[Claude Code](./integrations/claude-code.md)、[Gemini SDK](./integrations/gemini-sdk.md)、[Continue.dev](./integrations/ continue.json)、[Aider](./integrations/aider.md)、[Cursor](./integrations/cursor.md)、[LangChain](./integrations/langchain_orcarouter.py)、[LlamaIndex](./integrations/llamaindex_orcarouter.py)、[Vercel AI] のドロップイン構成SDK](./integrations/vercel_ai.ts)、および OpenAI Chat Completions プロトコルを使用するツール — さらにネイティブの Anthropic および Gemini ワイヤー フォーマットにも対応します。 [`integrations/`](./integrations/) を参照してください。

## 意図的にそうでないもの

これは **単一ワークスペース** エディションです。設計上、いいえ:
- マルチテナント、RBAC、SSO
- 請求、ウォレット、ポイント、パートナー プログラム
- 管理コンソール、監査ログ、信頼性と安全性
- マルチポッド展開 / Kubernetes
- アラート用の電子メール / Slack / Webhook

これらについては、ホストされた製品または (今後の) Teams エディションを参照してください。

## テスト

テストファーストで構築。ここに出荷されるすべての動作には、最初に失敗するテストがありました。

```bash
pip install -e ".[dev]"
PYTHONPATH=. pytest -v
# 403 passed
```

|スライス |テスト |何を |
|---|---|---|
| 1. 設定 | 5 |環境読み込み、デフォルト、`env_provider_keys()` |
| 2. シード | 3 |ブートストラップ ワークスペース + API キー + RoutingConfig、べき等 |
| 3. 認証ミドルウェア | 4 |ベアラー トークンの検証、欠落/無効の場合は 401 |
| 4. アプリファクトリー | 3 | /health、エラー エンベロープ、/v1/* ゲート |
| 5. プロバイダーキー CRUD | 5 |保存時には暗号化され、平文は往復することはありません。
| 6.ルーターキャッシュ | 13 | env+DB+hosted デプロイメントアセンブリを優先 |
| 7. チャットの完了 | 5 | OpenAI 形式、RequestLog、検証 |
| 8. 分析 | 4 |最近 / 支出 / レイテンシ p50/p99 |
| 9. /v1/{モデル、キー、ルーティング} | 8 |リスト/作成/取り消し + 戦略の更新 |
| 10. ストリーミング | 4 | SSE フォーマット、`[DONE]` センチネル、ログ ライトバック |
| 11. カタログ | 7 | 100 を超えるモデル、機能フラグ、価格設定 |
| 12. `model="auto"` | 21 |能力検出、最も安価なニーズを満たす (ユニット + 統合) |
| 13. コスト削減 | 9 |節約と常時 GPT-4 ベースライン + ホスト型自動の比較 |
| 14. プロンプトキャッシュ | 15 |クロスプロバイダー完全一致キャッシュ + チャット統合 |
| 15. ベンチマーク | 4 | summary() + render_markdown() 集約 |
| 16. ホストのステータス | 7 | `/v1/hosted` 設定ソース + サインアップ URL 表面 |
| 17. ホスト型自動節約 | 3 |合成カタログの「_hosted_auto_ Savings」エッジケース |
| 18. 到達不可能なモデル | 7 |ホストがオンになっていると「アクセスできないモデル」タイルが消去される |
| 19. マルチプロトコル認証 | 6 |x-api-key / x-goog-api-key / ?key= のスコープ、/v1beta ガード、プロトコルごとの 401 エンベロープ |
| 20. Anthropic `/v1/messages` | 53 |リクエスト/レスポンス/ストリームの変換 + イングレス統合 |
| 21. Gemini `/v1beta` | 40 |schema-enum 正規化を含む変換 + generateContent/ストリーム イングレス |
| **合計** | **403** | |

スライス行は各スライスの出荷時に追加されたテストを示します。合計は現在の完全なテスト スイートです。

＃＃ 建築

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

## ロードマップ

- [x] OpenAI 互換のチャット補完
- [x] ストリーミング (SSE)
- [x] `model="auto"` 最も安価なルーティング
- [x] アップストリームとしてホストされる
- [x] 保存時の暗号化された BYOK
- [x] ローカル分析ダッシュボード
- [x] CI (GitHub アクション)
- [x] プロバイダー間のプロンプト キャッシュ
- [x] Continue.dev / Aider / LangChain / Cursor / Vercel AI SDK の統合
- [x] 公開ベンチマーク + 貯蓄請求
- [ ] 埋め込み + 画像生成プロキシ

フェイルオーバーのデモについては、[DEMO.md](./DEMO.md) を参照してください。

## ライセンス

マサチューセッツ工科大学[ライセンス](./LICENSE) を参照してください。
