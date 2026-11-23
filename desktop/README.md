# OrcaRouter Lite desktop app

A menu-bar app that runs the Lite router on your computer, connects your coding
agents to it, and shows what they spend.

<img src="../docs/screenshots/desktop-panel.png" alt="Menu-bar panel" width="320">

## How it fits together

```
┌──────────────── menu-bar app (Tauri, src-tauri/) ───────────────┐
│ tray title "$3.20"  ·  notifications  ·  panel / setup windows  │
└──────────────┬──────────────────────────────────────────────────┘
               │ starts `orca-engine up` (or reuses one already on the port)
               ▼
┌──────────────── engine on 127.0.0.1:8765 (Python, ../app) ──────┐
│ /v1/chat/completions, /v1/messages, ...   ← your coding agents  │
│ /v1/app/*   agents, spend summary, budget ← the app (app.key)   │
│ /desktop/   panel.html, setup.html        ← the app's windows   │
└─────────────────────────────────────────────────────────────────┘
```

- **`ui/`**: the panel and first-run pages. Plain HTML, CSS and ES modules built on
  the dashboard's design tokens; no build step. The engine serves them at
  `/desktop/`, so the windows call the API same-origin. View logic lives in
  `ui/lib.js` and is tested by `tests/lib.test.mjs`.
- **`src-tauri/`**: the native shell. It starts the engine, injects the app key
  into its own windows only, refuses navigation to any other origin, shows
  today's spend as the tray title, and sends budget and failover notifications.
  The rules for the title and notifications are pure functions in
  `src/logic.rs` with unit tests.
- **`engine/`**: `build_engine.py` freezes the engine with PyInstaller into the
  `orca-engine` sidecar that the installer bundles, so users need no Python.

Everything the app does is also a command: `orca up`, `orca connect <agent>`,
`orca disconnect <agent>`, `orca status`.

## Develop

```bash
pip install -e ".[dev]"     # from the repo root: engine + orca CLI
```

```bash
cd desktop && npm install
```

```bash
# Development stand-in for the bundled engine: runs `orca` from PATH.
triple=$(rustc -vV | sed -n 's/host: //p')
mkdir -p src-tauri/binaries
printf '#!/bin/sh\nexec orca "$@"\n' > src-tauri/binaries/orca-engine-$triple
chmod +x src-tauri/binaries/orca-engine-$triple
```

```bash
npm run dev
```

On Linux, Tauri needs `libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev`.

To work on the pages in a browser instead, run `orca up` and open
`http://127.0.0.1:8765/desktop/panel.html#key=<contents of ~/.orcarouter-lite/app.key>`.
For screenshots, `scripts/seed_demo.py` fills a throwaway engine with demo data.

## Test

```bash
npm test                                   # view logic
cd src-tauri && cargo test --lib           # tray title + notification rules
```

The engine side (`/v1/app`, agent connectors, `orca` CLI) is covered by the
Python suite at the repo root.

## Build installers

```bash
pip install -e ".[desktop-build]"
python desktop/engine/build_engine.py     # → src-tauri/binaries/orca-engine-<triple>
cd desktop && npx tauri build             # → src-tauri/target/release/bundle/
```

The [`desktop` workflow](../.github/workflows/desktop.yml) does this on macOS
(Apple silicon and Intel), Linux and Windows for every `v*` tag, smoke-tests the
frozen engine, and attaches the installers to the GitHub release. macOS builds
are signed and notarised when the `APPLE_*` repository secrets are set.

Login items should start the app with `--background` so it doesn't open the
panel on boot; launching it by hand opens the panel.

## Security model

See [SECURITY.md](../SECURITY.md#what-the-desktop-app-and-orca-cli-can-touch)
for what the app may read and change on your computer.
