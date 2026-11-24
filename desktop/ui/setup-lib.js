// View logic for the setup window. Pure functions only (no DOM, no network),
// tested by desktop/tests/setup.test.mjs. Kept apart from lib.js so the
// panel and setup can change independently.
import { money } from "./lib.js";

// ── setup: links (H8, V6) ──

// The fixed source names a link may carry (same list as the engine's
// packages/desktop/links.py). Never anything about the user.
const REF_SOURCES = new Set(["lite-setup", "lite-card", "lite-badge", "lite-panel", "lite-share"]);
export const LANDING_URL = "https://continuum-ai-corp.github.io/OrcaRouter-Lite/";

// `url` with `ref=<source>`, replacing an earlier ref. Only web links are
// tagged; anything else comes back unchanged.
export function setupWithRef(url, source = "lite-setup") {
  if (!REF_SOURCES.has(source)) throw new Error(`unknown link source: ${source}`);
  if (!url) return null;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return url;
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return url;
  parsed.searchParams.delete("ref");
  parsed.searchParams.append("ref", source);
  return parsed.toString();
}

export const BADGE_MARKDOWN =
  "[![budgeted with OrcaRouter Lite](https://img.shields.io/badge/budgeted%20with-OrcaRouter%20Lite-2D7FF9)]" +
  `(${setupWithRef(LANDING_URL, "lite-badge")})`;

// ── setup: OrcaRouter key on the clipboard (H1) ──

// Same shape the app checks natively (desktop/src-tauri logic.rs).
const ORCA_KEY = /^sk-orca-[A-Za-z0-9_-]{16,200}$/;

export function isOrcaKey(text) {
  return typeof text === "string" && ORCA_KEY.test(text.trim());
}

export function maskOrcaKey(key) {
  return `sk-orca-…${String(key).trim().slice(-4)}`;
}

// What the window does each time it regains focus: offer an OrcaRouter key
// found on the clipboard, once per distinct key. Declining, using or pasting
// a key all count as having seen it. Anything that isn't a key is ignored.
export function createClipboardOffers() {
  const seen = new Set();
  return {
    onFocus(text) {
      if (!isOrcaKey(text)) return null;
      const key = text.trim();
      if (seen.has(key)) return null;
      seen.add(key);
      return key;
    },
    seen(key) {
      if (isOrcaKey(key)) seen.add(key.trim());
    },
  };
}

// ── setup: provider keys (P1) ──

// The engine's one provider list (GET /v1/providers/supported), as setup
// shows it: in the engine's order, without the hosted gateway (it has its
// own choice), the new ones marked.
export function byokProviders(supported) {
  return ((supported && supported.providers) || [])
    .filter((p) => !p.hosted)
    .map((p) => ({
      id: p.id,
      name: p.name,
      placeholder: p.key_hint ? `${p.name} key (${p.key_hint})` : `${p.name} key`,
      isNew: Boolean(p.new),
      checkable: Boolean(p.checkable),
    }));
}

// The done screen's line for a key that was saved. `result` is the engine's
// check ({status, detail}), or null when the provider has no key check.
export function savedKeyResult(name, result) {
  const line = { name: `${name} key`, ok: true, text: "Checked and saved" };
  if (!result || result.status === "unchecked") return { ...line, text: "Saved without checking" };
  if (result.status === "unreachable") return { ...line, ok: false, text: result.detail };
  return line;
}

// ── setup: where requests go (H0, H6, P2) ──

// The local runtime setup can offer: the first one running with a model.
export function localRuntime(local) {
  const r = ((local && local.runtimes) || []).find((x) => x.running && (x.models || []).length > 0);
  return r ? { id: r.id, name: r.name } : null;
}

export function localChoice(runtime) {
  return {
    title: `${runtime.name} first, OrcaRouter for the rest`,
    body: "Quick requests stay on this computer. Harder ones go to OrcaRouter's free models first, paid ones only when needed.",
  };
}

const LOCAL_ROUTES = new Set(["local_hosted", "local_only"]);

// The choices in step 2, in order, and which one starts selected.
// `providers`: ids of providers that already have a key.
export function setupRoutes({ runtime, providers = [], strategy = null }) {
  const routes = [...(runtime ? ["local_hosted", "local_only"] : []), "hosted", "byok", "company"];
  const localFirst = Boolean(runtime) && strategy === "local_first";
  let selected;
  if (!providers.length) selected = runtime ? (localFirst ? "local_only" : "local_hosted") : "hosted";
  else if (!providers.includes("orcarouter")) selected = "byok";
  else selected = localFirst ? "local_hosted" : "hosted";
  return { routes, selected };
}

// The routing strategy to save for the chosen route, or null to leave it.
// Local choices turn on "local first"; moving away from them turns it off,
// but reopening setup and keeping the same choice never changes it.
export function strategyChange(initialRoute, route, current) {
  if (LOCAL_ROUTES.has(route)) return current === "local_first" ? null : "local_first";
  if (route !== initialRoute && current === "local_first") return "balanced";
  return null;
}

// ── setup: orca://setup links (V3) ──

// What a setup link asks for, as one sentence to confirm, plus the agents to
// tick (only ones this computer can connect) and the budget to fill in.
// Null for other links, or a link that asks for nothing this computer can do.
export function setupLinkConfirmation(link, agents) {
  if (!link || link.action !== "setup") return null;
  const byId = Object.fromEntries((agents || []).map((a) => [a.id, a]));
  const tick = [];
  const names = [];
  const skipped = [];
  for (const id of link.agents || []) {
    const a = byId[id];
    if (a && a.installed && a.setup === "auto") {
      tick.push(id);
      names.push(a.name);
    } else skipped.push(a ? a.name : id);
  }
  const budgetCents = Number.isInteger(link.budget_cents) && link.budget_cents >= 0 ? link.budget_cents : null;
  const parts = [];
  if (names.length) parts.push(`connect ${names.join(", ")}`);
  if (budgetCents !== null) parts.push(`daily budget ${money(budgetCents * 10_000)}`);
  if (!parts.length) return null;
  return { text: `A link wants to set up Orca: ${parts.join("; ")}`, agents: tick, budgetCents, skipped };
}

// ── setup: a step the panel asked for ──

// The panel opens setup at a step ("Add OrcaRouter backup", "Join my
// company's gateway"). Natively it leaves {step, at} in localStorage under
// "orca-setup-step"; in a browser it adds #step= to the URL. Returns the
// route to select, or null. A stored request older than a minute is ignored
// so setup opened later from the menu starts as usual.
const STEP_ROUTES = { orcarouter: "hosted", gateway: "company" };
export const SETUP_STEP_KEY = "orca-setup-step";

export function requestedStep(stored, hash, now = Date.now()) {
  if (stored) {
    try {
      const { step, at } = JSON.parse(stored);
      if (typeof at === "number" && now - at >= 0 && now - at < 60_000 && STEP_ROUTES[step]) return STEP_ROUTES[step];
    } catch {
      /* a broken entry is ignored */
    }
  }
  const fromHash = new URLSearchParams(String(hash || "").replace(/^#/, "")).get("step");
  return STEP_ROUTES[fromHash] || null;
}

// ── setup: the line under a saved OrcaRouter key ──

// Says the clipboard was cleared only when it was: it isn't if something
// else was copied in the meantime, or outside the app (no native bridge).
export function keySavedText({ checked, warn = null, cleared = false }) {
  const first = checked ? "Checked with OrcaRouter and saved in your keychain." : warn || "Orca couldn't check it with OrcaRouter.";
  return cleared ? `${first} The clipboard was cleared.` : first;
}
