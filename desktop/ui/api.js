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
  el.querySelector("div > span").textContent = detail || "";
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
