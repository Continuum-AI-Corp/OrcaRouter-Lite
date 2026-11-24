#!/usr/bin/env bash
# Records docs/launch/demo.gif: the 30-second storyboard in
# docs/launch/demo-script.md (install, connect, spend, alert), from the real
# setup and panel pages of an engine filled with demo data.
#
#   scripts/record_demo.sh            # writes docs/launch/demo.gif
#   OUT=/tmp/demo.gif scripts/record_demo.sh
#
# Needs python with the repo installed (pip install -e .), node with the
# `playwright` package and its Chromium, and ffmpeg. Everything runs in a
# throwaway HOME, so your real ~/.orcarouter-lite and agent settings are never
# touched; the folder is deleted afterwards.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/docs/launch/demo.gif}"
PORT="${PORT:-8799}"
PY="${PYTHON:-python3}"

for tool in node ffmpeg "$PY"; do
  command -v "$tool" >/dev/null || { echo "record_demo: $tool is required" >&2; exit 1; }
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/orca-demo.XXXXXX")"
ENGINE_PID=""
cleanup() {
  [ -n "$ENGINE_PID" ] && kill "$ENGINE_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

# A pretend computer with four coding agents installed (their config folders
# are what setup detects).
export HOME="$WORK/home"
export ORCA_HOME="$HOME/.orcarouter-lite"
mkdir -p "$HOME/.claude" "$HOME/.codex" "$HOME/.gemini" "$HOME/.config/opencode"

cd "$ROOT"
"$PY" -c 'from app.orca_cli import entrypoint; entrypoint()' up --port "$PORT" >"$WORK/engine.log" 2>&1 &
ENGINE_PID=$!
for _ in $(seq 1 60); do
  [ -s "$ORCA_HOME/engine.json" ] && curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT/health" >/dev/null || { cat "$WORK/engine.log" >&2; exit 1; }
BASE="http://127.0.0.1:$PORT"
KEY="$(cat "$ORCA_HOME/app.key")"

FRAMES="$WORK/frames"
mkdir -p "$FRAMES"
# 1. Before any agent is connected: setup as a new user sees it.
NODE_PATH="${NODE_PATH:-$(npm root -g 2>/dev/null)}" node scripts/record_demo.cjs setup "$BASE" "$KEY" "$FRAMES"
# 2. A day of demo spend ($4.05 today), two agents connected, a $20 budget.
"$PY" desktop/scripts/seed_demo.py
NODE_PATH="${NODE_PATH:-$(npm root -g 2>/dev/null)}" node scripts/record_demo.cjs spend "$BASE" "$KEY" "$FRAMES"
# 3. Same spend against a $5 budget: past 80%, the alert state.
curl -sf -X PUT -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"daily_budget_cents": 500}' "$BASE/v1/app/settings" >/dev/null
NODE_PATH="${NODE_PATH:-$(npm root -g 2>/dev/null)}" node scripts/record_demo.cjs alert "$BASE" "$KEY" "$FRAMES"
# 4. Compose the storyboard frames and encode.
NODE_PATH="${NODE_PATH:-$(npm root -g 2>/dev/null)}" node scripts/record_demo.cjs compose "$BASE" "$KEY" "$FRAMES"

mkdir -p "$(dirname "$OUT")"
ffmpeg -loglevel error -y -framerate 2 -i "$FRAMES/frame-%03d.png" \
  -vf "fps=2,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle" \
  -loop 0 "$OUT"
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1))"
