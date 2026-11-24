// Engine client for the Orca app. Same-origin: the engine serves these
// pages at /desktop/, so requests go to location.origin with the app key.
import { engineConfig, tzOffsetMinutes } from "./lib.js";

const TIMEOUT_MS = 8_000;

export class EngineError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export function createEngine(win = window) {
  const { baseUrl, key } = engineConfig(win.location, win.__ORCA__);

  async function call(method, path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let resp;
    try {
      resp = await fetch(`${baseUrl}${path}`, {
        method,
        signal: controller.signal,
        headers: {
          Authorization: `Bearer ${key}`,
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch {
      throw new EngineError("Can't reach the Orca engine.", 0);
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try {
      data = await resp.json();
    } catch {
      data = null;
    }
    if (!resp.ok) {
      const msg = data?.error?.message || data?.detail || `Request failed (${resp.status})`;
      throw new EngineError(typeof msg === "string" ? msg : JSON.stringify(msg), resp.status);
    }
    return data;
  }

  return {
    baseUrl,
    key,
    hasKey: Boolean(key),
    request: call, // page-specific calls (see setupCalls below)
    summary: () => call("GET", `/v1/app/summary?tz_offset_minutes=${tzOffsetMinutes()}`),
    agents: () => call("GET", "/v1/app/agents"),
    connect: (id) => call("POST", `/v1/app/agents/${encodeURIComponent(id)}/connect`),
    disconnect: (id) => call("POST", `/v1/app/agents/${encodeURIComponent(id)}/disconnect`),
    disconnectAll: () => call("POST", "/v1/app/agents/disconnect-all"),
    settings: () => call("GET", "/v1/app/settings"),
    saveSettings: (s) => call("PUT", "/v1/app/settings", s),
    hosted: () => call("GET", "/v1/hosted"),
    joinGateway: (url, key) => call("POST", "/v1/app/gateway", { url, key }),
    leaveGateway: () => call("DELETE", "/v1/app/gateway"),
    setProviderKey: (provider, apiKey) => call("PUT", `/v1/providers/${encodeURIComponent(provider)}`, { api_key: apiKey }),
    checkProviderKey: (provider, apiKey) =>
      call("POST", `/v1/app/providers/${encodeURIComponent(provider)}/check`, { api_key: apiKey }),
  };
}

// Native bridge. Inside the desktop app these call into Rust; in a plain
// browser they fall back to ordinary navigation.
export const native = {
  available: () => Boolean(window.__TAURI__?.core?.invoke),
  invoke(cmd, args) {
    return window.__TAURI__.core.invoke(cmd, args);
  },
  async openDashboard(engine) {
    if (this.available()) return this.invoke("open_dashboard");
    // The dashboard shares this origin, so hand it the key it would ask for.
    try {
      localStorage.setItem("orca-lite-api-key", engine.key);
    } catch {
      /* storage can be unavailable; the dashboard will ask for the key */
    }
    window.open(`${engine.baseUrl}/`, "_blank", "noopener");
  },
  async openSetup(engine) {
    if (this.available()) return this.invoke("open_setup");
    window.location.href = `${engine.baseUrl}/desktop/setup.html${window.location.hash}`;
  },
  async openExternal(url) {
    if (this.available()) return this.invoke("open_external", { url });
    window.open(url, "_blank", "noopener");
  },
  async finishSetup() {
    if (this.available()) return this.invoke("finish_setup");
  },
  async resizePanel(height) {
    if (this.available()) return this.invoke("resize_panel", { height });
  },
  async canInstallUpdates() {
    if (this.available()) return this.invoke("can_install_updates");
    return false;
  },
  async installUpdate() {
    if (this.available()) return this.invoke("install_update");
  },
  async quit() {
    if (this.available()) return this.invoke("quit_app");
  },
  // H1 (setup window only): the clipboard text if it's an OrcaRouter key
  // and the window has focus, else null. Offer it; never use it silently.
  async clipboardOrcaKey() {
    if (this.available()) return this.invoke("clipboard_orca_key");
    return null;
  },
  // H1 (setup window only): clears the clipboard if it still holds exactly
  // the key that was saved (never another key or anything copied since).
  async clearClipboard(key) {
    if (this.available()) return this.invoke("clear_clipboard", { key: String(key || "") });
  },
  // V2 (panel only): put a PNG (base64, or a canvas data: URL) on the clipboard.
  async copyPng(base64) {
    if (this.available()) return this.invoke("copy_png", { base64 });
    const b64 = base64.replace(/^data:image\/png;base64,/, "");
    const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    await navigator.clipboard.write([new ClipboardItem({ "image/png": new Blob([bytes], { type: "image/png" }) })]);
  },
  // V3: the orca:// link waiting for this page ({action: "connect", agent} |
  // {action: "join", gateway} | {action: "setup", agents, budget_cents}), or null.
  async takePendingLink() {
    if (this.available()) return this.invoke("take_pending_link");
    return null;
  },
  // V3: call `callback(link)` for each orca:// link meant for this page,
  // including one that arrived before it loaded. Show a confirmation; never
  // act on a link without the user's click. Returns an unsubscribe function.
  onLink(callback) {
    const deliver = async () => {
      const link = await this.takePendingLink();
      if (link) callback(link);
    };
    const handler = (event) => {
      // Natively the event only says "a link is waiting" (taking it clears
      // it, so it's delivered once). In a plain browser (development, the
      // e2e suite) there is no native side: the event carries the link.
      if (!this.available() && event?.detail) callback(event.detail);
      else deliver();
    };
    window.addEventListener("orca-link", handler);
    deliver();
    return () => window.removeEventListener("orca-link", handler);
  },
};

let toastTimer = null;

export function toast(kind, title, detail, ms = 3600) {
  document.querySelectorAll(".toast:not(.leaving)").forEach((t) => {
    t.classList.add("leaving");
    setTimeout(() => t.remove(), 240);
  });
  clearTimeout(toastTimer);
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.setAttribute("role", kind === "err" ? "alert" : "status");
  const icon = {
    ok: '<path d="M4 12l5 5L20 6"/>',
    err: '<path d="M12 7v6M12 17h.01"/>',
    info: '<path d="M12 11v6M12 7h.01"/>',
  }[kind];
  el.innerHTML = `<span class="ico" aria-hidden="true"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">${icon}</svg></span><div><b></b><span></span></div>`;
  el.querySelector("b").textContent = title;
  el.querySelector(":scope > div > span").textContent = detail || ""; // not the icon, also a span
  document.body.appendChild(el);
  const dismiss = () => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 240);
  };
  const arm = () => (toastTimer = setTimeout(dismiss, ms));
  // Hovering keeps a toast (errors especially) on screen while it's read.
  el.addEventListener("mouseenter", () => clearTimeout(toastTimer));
  el.addEventListener("mouseleave", arm);
  arm();
}

// ── setup: engine calls (P1, H6, P2) ──

// The calls only the setup window makes, on top of createEngine's.
export function setupCalls(engine) {
  return {
    // The one provider list, in display order (P1).
    supportedProviders: () => engine.request("GET", "/v1/providers/supported"),
    // Ollama, LM Studio and llama.cpp found on this computer (P2).
    localRuntimes: () => engine.request("GET", "/v1/app/local"),
    routing: () => engine.request("GET", "/v1/routing"),
    setStrategy: (strategy) => engine.request("PUT", "/v1/routing", { strategy }),
  };
}

// ── panel: roadmap calls ──
// The panel's engine calls for the roadmap features (offers, agent sheet,
// model picker, local models, settings, team report, sharing). Same rules as
// createEngine's: same origin, the app key, errors as EngineError.

async function panelCall(engine, method, path, body, timeoutMs = TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let resp;
  try {
    resp = await fetch(`${engine.baseUrl}${path}`, {
      method,
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${engine.key}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new EngineError("Can't reach the Orca engine.", 0);
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try {
    data = await resp.json();
  } catch {
    data = null;
  }
  if (!resp.ok) {
    const msg = data?.error?.message || data?.detail || `Request failed (${resp.status})`;
    throw new EngineError(typeof msg === "string" ? msg : JSON.stringify(msg), resp.status);
  }
  return data;
}

export function panelEngine(engine) {
  const tz = () => tzOffsetMinutes();
  const q = encodeURIComponent;
  return {
    models: (query = "", limit = 1000) =>
      panelCall(engine, "GET", `/v1/app/models?limit=${limit}${query ? `&q=${q(query)}` : ""}`),
    local: () => panelCall(engine, "GET", "/v1/app/local"),
    refreshLocal: () => panelCall(engine, "POST", "/v1/app/local/refresh", undefined, 15_000),
    agentRequests: (id, limit = 20) => panelCall(engine, "GET", `/v1/app/agents/${q(id)}/requests?limit=${limit}`),
    // One tiny request through the agent's own config: up to 20 s upstream.
    testAgent: (id) => panelCall(engine, "POST", `/v1/app/agents/${q(id)}/test`, undefined, 30_000),
    benchmarkKey: () => panelCall(engine, "GET", "/v1/app/benchmark-key"),
    saveBenchmarkKey: (apiKey) => panelCall(engine, "PUT", "/v1/app/benchmark-key", { api_key: apiKey }),
    report: (format = "markdown", week = "this") =>
      panelCall(engine, "GET", `/v1/app/report?format=${q(format)}&week=${q(week)}&tz_offset_minutes=${tz()}`),
    saveReport: (week = "this") =>
      panelCall(engine, "POST", "/v1/app/report/save", { format: "csv", week, tz_offset_minutes: tz() }),
    shareCard: () => panelCall(engine, "GET", `/v1/app/share/card?tz_offset_minutes=${tz()}`),
    shareSetup: () => panelCall(engine, "GET", "/v1/app/share/setup"),
  };
}

// Open setup at one step ("orcarouter" or "gateway"). The native command
// takes no arguments, so the step also waits in localStorage (same origin as
// setup) under "orca-setup-step" as {step, at}; setup reads it once. In a
// plain browser the step rides in setup's URL fragment.
native.openSetupAt = async function openSetupAt(engine, step, hash) {
  try {
    localStorage.setItem("orca-setup-step", JSON.stringify({ step, at: Date.now() }));
  } catch {
    /* storage can be unavailable; setup then opens at its first step */
  }
  if (this.available()) return this.invoke("open_setup");
  window.location.href = `${engine.baseUrl}/desktop/setup.html${hash}`;
};
