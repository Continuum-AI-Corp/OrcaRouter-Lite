# 30-second failover demo

Three scripts, two terminals, one screen recording.

## Setup (~2 minutes)

```bash
cd OrcaRouter-Lite
cp .env.example .env

# Configure BOTH providers so failover has somewhere to go.
echo 'OPENAI_API_KEY=sk-...'        >> .env
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
# Optional: GOOGLE_API_KEY, GROQ_API_KEY for more failover variety

docker compose up -d
docker compose logs api 2>&1 | grep 'sk-orca-'
# → copy the printed sk-orca-* key
```

## Recording (~30 seconds)

Open three tiles side-by-side for the camera:
1. **Terminal A** (top) — runs `scripts/demo.sh` in a tight loop
2. **Browser** (right) — `http://localhost:8000/`, Analytics tab visible
3. **Terminal B** (bottom) — fires `scripts/demo_kill_openai.sh` mid-recording

```bash
# Terminal A — start the loop
export ORCA_API_KEY="sk-orca-..."
./scripts/demo.sh
```

You'll see output like:
```
[  1] MISS         gpt-4o-mini                              ok
[  2] HIT          gpt-4o-mini                              ok
[  3] HIT          gpt-4o-mini                              ok
...
```

After ~10 seconds, in Terminal B:
```bash
./scripts/demo_kill_openai.sh
```

The next request in Terminal A retries via Anthropic; subsequent requests
show the resolved model flipping (`claude-3-5-haiku-latest` etc) without
any code change in Terminal A:

```
[ 11] MISS         claude-3-5-haiku-latest                  ok
[ 12] HIT          claude-3-5-haiku-latest                  ok
```

The dashboard's recent-requests table fills with `provider=anthropic` rows;
the savings tile updates live.

## Capture

- **macOS**: Cmd-Shift-5, then `ffmpeg -i input.mov -vf "fps=12,scale=1200:-1" demo.gif`
- **Linux**: `peek` or `byzanz-record`
- **Cross-platform**: [OBS](https://obsproject.com) (overkill for 30s but bulletproof)

Trim to ≤30s. Export under 8 MB so GitHub renders inline in the README.

## Storyboard

| Time | What viewers see |
|---|---|
| 0-3s | Title card: "OrcaRouter Lite — failover in real time" |
| 3-12s | Tight loop succeeding via `gpt-4o-mini`. Dashboard fills. |
| 12-15s | Terminal B runs `demo_kill_openai.sh` — visible failover trigger |
| 15-25s | Same loop continues; resolved model flips to `claude-*` mid-stream |
| 25-30s | Closing card: "No code change. `model="auto"` did the routing." |

## Restore

```bash
./scripts/demo_restore_openai.sh
```

## Where to publish

- README hero (replace the placeholder image link)
- Show HN cover image
- Twitter/Threads launch post
- ProductHunt gallery

## Why this lands

Most LLM router pitches show a config table. This shows **a failure happening
in real time and being absorbed transparently**. The viewer's brain resolves
"so this is what would have prevented my 3am pager last month" and that's the
share-worthy moment.

## Bonus: native-protocol smoke (Anthropic + Gemini ingress)

With the same running server, verify the native endpoints end-to-end — the
Anthropic Messages API (`/v1/messages`, what Claude Code speaks) and the
Gemini API (`/v1beta`):

```bash
ORCA_API_KEY="sk-orca-..." PYTHONPATH=. python scripts/smoke_native.py
# 9/9 checks passed
```

The script exercises blocking, streaming, tool use, and count_tokens over
raw HTTP, and — when `pip install anthropic google-genai` is present — the
official SDKs pointed straight at Lite. See
[integrations/claude-code.md](./integrations/claude-code.md) and
[integrations/gemini-sdk.md](./integrations/gemini-sdk.md).
