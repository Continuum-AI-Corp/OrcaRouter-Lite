# Install OrcaRouter Lite on your computer

The desktop app is all you need. It carries its own engine and keeps its data
in a local SQLite file, so there is **no server, no Docker and no database to
set up**. Everything lives in `~/.orcarouter-lite` (on Windows,
`%USERPROFILE%\.orcarouter-lite`).

## 1. Download

- **Releases** (from the first tagged version): the
  [latest release](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest)
  has `.dmg` (Apple silicon and Intel), `.msi`/`.exe` (Windows) and
  `.deb`/`.AppImage` (Linux).
- **Before the first release:** open the latest green run of the
  [desktop workflow](https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/actions/workflows/desktop.yml)
  (you need to be signed in to GitHub) and download the
  `orcarouter-lite-<runner>` artifact for your system: `macos-15` (Apple
  silicon), `macos-15-intel`, `windows-2022` or `ubuntu-22.04`. Ignore the
  `-updater-` artifacts; those are update bundles.
- **Package managers** (from the first tagged version):

  ```bash
  brew install --cask continuum-ai-corp/tap/orcarouter-lite   # macOS app
  ```

  ```powershell
  winget install OrcaRouter.Lite                              # Windows app
  ```

  The landing page, <https://continuum-ai-corp.github.io/OrcaRouter-Lite/>,
  picks the right download for your system.

## 2. Install and open it

### macOS

Open the `.dmg` and drag **OrcaRouter Lite** to Applications.

Until the project's Apple certificate is set up, builds are signed ad hoc, so
the first time you open it macOS says it's from an unidentified developer:

1. Right-click (or Control-click) **OrcaRouter Lite** in Applications and
   choose **Open**, then **Open** again. Or, after the warning, go to
   **System Settings → Privacy & Security** and click **Open Anyway**.
2. If macOS says the app "is damaged" (a download that lost its signature),
   run this once and open it again:

   ```bash
   xattr -dr com.apple.quarantine "/Applications/OrcaRouter Lite.app"
   ```

Orca lives in the menu bar; it has no Dock icon.

### Windows

Run the `.msi` or the setup `.exe`. Until the project's code-signing
certificate is set up, SmartScreen may say "Windows protected your PC": click
**More info → Run anyway**. Orca lives in the notification area (click the `^`
next to the clock if you don't see it).

### Linux

```bash
sudo apt install ./OrcaRouter*.deb
```

Or make the AppImage executable and run it:

```bash
chmod +x OrcaRouter*.AppImage && ./OrcaRouter*.AppImage
```

The tray icon needs a desktop with a system tray (GNOME needs the
AppIndicator extension).

## 3. First run

Setup opens by itself:

1. **Coding agents on this computer.** The agents Orca found are ticked. It
   backs up each agent's settings before changing them.
2. **Where should requests go?** The OrcaRouter gateway comes first: one key
   for every model, failover between providers, and free models to start.
   Paid models are billed per request, and only when you choose them. Or add
   your own keys instead (Anthropic, OpenAI, Gemini, DeepSeek, xAI, Mistral,
   Groq, Together, Fireworks); they work with or without OrcaRouter. Each key
   is checked with its provider before it's saved. More
   providers, and how `model="auto"` picks a model, are in the dashboard
   (menu → Open dashboard).
3. **Daily budget.** Notifications at 80% and 100%; optionally pause agents
   when it's reached. **Start Orca when I log in** is on, so your agents keep
   working after a restart.

Restart any agent sessions that were already open. An agent that asks for a
model you have no key for (Claude Code with only an OpenAI key, say) is served
by the best model your keys do cover; the response headers
`x-orca-requested-model` and `x-orca-resolved-model` say which.

## Uninstall

Restore your agents first: in the menu-bar panel click **Disconnect all**
(twice, it asks to confirm). If you also installed the `orca` CLI, this does
the same, with or without the app running:

```bash
orca disconnect --all
```

Then remove the app:

- **macOS:** quit Orca from its menu and drag the app to the Trash.
- **Windows:** Settings → Apps → OrcaRouter Lite → Uninstall. The uninstaller
  restores your agents itself.
- **Linux:** remove the package with `sudo apt remove <name>`, using the name
  `dpkg -l | grep -i orca` shows (or delete the AppImage).

To remove your data too, delete `~/.orcarouter-lite`. On macOS and Windows the
encryption key is also in the Keychain / Credential Manager under
"OrcaRouter Lite".

## Just the command-line tool

For a server, a headless machine, or if you'd rather not run a menu-bar app,
install the `orca` CLI and engine on their own (from the first tagged
version):

```bash
brew install continuum-ai-corp/tap/orcarouter-lite   # macOS and Linux (Homebrew formula)
```

```bash
pipx install orcarouter-lite                         # any OS with Python 3.11+
```

Then `orca up` starts the router, `orca connect claude-code` connects an
agent and `orca status` shows today's spend. The formula installs the
dependencies from the release's hash-locked `requirements.lock`. It doesn't
include the app, and the cask doesn't put `orca` on your PATH by itself;
install both if you want both.

## Run from source instead

```bash
pip install -e .
```

```bash
orca up
```

```bash
orca connect claude-code
```

`orca status` shows today's spend; `orca disconnect --all` restores every agent.
