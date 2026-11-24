// Shared by the setup and dashboard browser scripts.
const path = require("path");

// The desktop app's native bridge, played by the page: what the Rust side
// would answer for each command, with what the page asked recorded on
// window.__native. Tests set window.__clip (the clipboard text) and
// window.__pendingLink (an orca:// link the app parsed) as they go.
function stubNativeBridge() {
  window.__native = { opened: [], cleared: 0, calls: [] };
  window.__clip = null;
  window.__pendingLink = null;
  window.__TAURI__ = {
    core: {
      async invoke(cmd, args) {
        window.__native.calls.push(cmd);
        switch (cmd) {
          case "clipboard_orca_key": {
            // Like the app: only a whole sk-orca- key, else nothing.
            const t = (window.__clip || "").trim();
            return /^sk-orca-[A-Za-z0-9_-]{16,200}$/.test(t) ? t : null;
          }
          case "clear_clipboard":
            window.__native.cleared += 1;
            window.__clip = null;
            return null;
          case "open_external":
            window.__native.opened.push(args.url);
            return null;
          case "take_pending_link": {
            const link = window.__pendingLink;
            window.__pendingLink = null;
            return link;
          }
          default:
            return null;
        }
      },
    },
  };
}

// The app delivers an orca:// link by keeping it and firing `orca-link`.
async function sendLink(page, link) {
  await page.evaluate((l) => {
    window.__pendingLink = l;
    window.dispatchEvent(new CustomEvent("orca-link", { detail: l }));
  }, link);
}

// Screenshots for review, in light and dark, when ORCA_E2E_SHOTS names a folder.
// `locator`: an element, "viewport" for what's on screen, or nothing for the whole page.
async function shots(page, name, locator) {
  const dir = process.env.ORCA_E2E_SHOTS;
  if (!dir) return;
  for (const scheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.waitForTimeout(150);
    const file = path.join(dir, `${name}-${scheme}.png`);
    if (locator === "viewport") await page.screenshot({ path: file });
    else if (locator) await locator.screenshot({ path: file });
    else await page.screenshot({ path: file, fullPage: true });
  }
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" });
}

// Setup's done screen; on a timeout, say what the status line said instead.
async function waitDone(page) {
  try {
    await page.locator("#done").waitFor({ state: "visible", timeout: 15000 });
  } catch (e) {
    throw new Error(`setup didn't finish: ${await page.locator("#status").textContent()}`);
  }
}

module.exports = { stubNativeBridge, sendLink, shots, waitDone };
