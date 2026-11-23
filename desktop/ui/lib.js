// View logic for the Orca app. Pure functions only: no DOM, no network,
// so they run under `node --test` (desktop/tests) and in the webview alike.

// Tile colours for agent initials, darkened from each tool's brand colour
// until white text reaches at least 4:1 (checked by the tests).
export const AGENT_COLORS = {
  "claude-code": "#C2613F",
  codex: "#0E8A6B",
  cursor: "#334155",
  aider: "#0F8A7E",
  "gemini-cli": "#2F6FE0",
  opencode: "#4338CA",
  cline: "#7C3AED",
  "command-code": "#B4233C",
  other: "#64748B",
};

// Rounds half-up to cents; the same vectors are tested in Python and Rust.
export function money(microcents) {
  const cents = Math.floor((Math.max(0, Number(microcents) || 0) + 5_000) / 10_000);
  const dollars = Math.floor(cents / 100).toLocaleString("en-US");
  return `$${dollars}.${String(cents % 100).padStart(2, "0")}`;
}

// The daily budget alerts by default; in "stop" mode it also pauses coding
// agents once it's reached. The words say which one the user chose.
export function budgetView(budget, spentMicrocents = 0) {
  if (!budget || budget.daily_cents === null || budget.daily_cents === undefined) {
    return { hasBudget: false, tone: "none", caption: "No daily budget", ariaText: "No daily budget", percent: 0, limit: null, stops: false };
  }
  const stops = budget.mode === "stop";
  const noun = stops ? "budget" : "alert";
  const limitMicro = budget.daily_cents * 10_000;
  const limit = money(limitMicro);
  const used = Math.max(0, Number(budget.used_percent) || 0);
  const pct = Math.round(used);
  let caption = `${pct}% of ${limit} ${noun}`;
  if (budget.state === "over") {
    caption = stops ? `Agents paused at ${limit}` : `${money(Math.max(0, spentMicrocents - limitMicro))} over your ${limit} alert`;
  }
  return {
    hasBudget: true,
    tone: budget.state,
    caption,
    ariaText: `${money(spentMicrocents)} of a ${limit} daily ${noun} used, ${pct}%`,
    percent: Math.min(100, used),
    limit,
    stops,
  };
}

const ORDER = { connected: 0, available: 1, unsupported: 2, missing: 3 };

function initials(name) {
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase();
  return name.slice(0, 1).toUpperCase() + name.slice(1, 2).toLowerCase();
}

const SUBTITLES = {
  connected: () => "Connected",
  available: (a) => (a.setup === "manual" ? "One paste step" : "Ready to connect"),
  unsupported: () => "Not supported yet",
  missing: () => "Not installed",
};

export function agentRows(agents, spend = [], { includeOther = false } = {}) {
  const spendById = Object.fromEntries((spend || []).map((s) => [s.id, s]));
  const rows = (agents || []).map((a, index) => {
    let state;
    if (a.connected) state = "connected";
    else if (!a.installed) state = "missing";
    else if (a.setup === "unsupported") state = "unsupported";
    else state = "available";

    const badge = {
      connected: { text: "Connected", tone: "ok" },
      available: a.setup === "manual" ? { text: "Manual setup", tone: "muted" } : { text: "Found", tone: "muted" },
      unsupported: { text: "Coming soon", tone: "muted" },
      missing: { text: "Not installed", tone: "muted" },
    }[state];
    const action = state === "connected" ? "disconnect" : state === "available" ? "connect" : null;
    const s = spendById[a.id];
    return {
      id: a.id,
      name: a.name,
      initials: initials(a.name),
      state,
      setup: a.setup,
      badge,
      action,
      subtitle: SUBTITLES[state](a),
      note: a.note || "",
      today: s ? money(s.today_microcents) : state === "connected" ? money(0) : "",
      week: s ? s.week_microcents : 0,
      index,
    };
  });

  rows.sort((x, y) => ORDER[x.state] - ORDER[y.state] || y.week - x.week || x.index - y.index);

  const other = spendById.other;
  if (includeOther && other && (other.today_microcents > 0 || other.week_microcents > 0)) {
    rows.push({
      id: "other",
      name: "Other apps",
      initials: "",
      state: "other",
      setup: null,
      badge: null,
      action: null,
      subtitle: "Your dashboard keys",
      note: "Requests made with API keys from the dashboard, not a connected agent.",
      today: money(other.today_microcents),
      week: other.week_microcents,
      index: rows.length,
    });
  }
  return rows;
}

// Agents that aren't installed take one line instead of a row each.
export function missingLine(rows) {
  const names = rows.filter((r) => r.state === "missing").map((r) => r.name);
  return names.length ? `Not installed: ${names.join(", ")}` : "";
}

const PROVIDER_NAMES = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
  groq: "Groq",
  together: "Together",
  fireworks: "Fireworks",
  xai: "xAI",
  deepseek: "DeepSeek",
  orcarouter: "OrcaRouter hosted",
};

const HEALTH = {
  healthy: { status: "Healthy", tone: "ok", detail: "" },
  degraded: { status: "Degraded", tone: "warn", detail: "Most requests failed in the last hour" },
  idle: { status: "Idle", tone: "muted", detail: "No requests in the last hour" },
};

export function providerRows(providers) {
  return (providers || []).map((p) => ({
    id: p.provider,
    name: PROVIDER_NAMES[p.provider] || p.provider,
    ...(HEALTH[p.state] || HEALTH.idle),
  }));
}

const MODEL_NAMES = { "gpt-4o": "GPT-4o" };

export function weekLine(summary) {
  const w = summary.week;
  const base = `Last 7 days ${money(w.spend_microcents)}`;
  if (!(w.saved_microcents > 0)) return base;
  const vs = MODEL_NAMES[w.baseline_model] || w.baseline_model;
  return `${base} · saved ${money(w.saved_microcents)} vs ${vs}`;
}

export function rescuedLine(count) {
  if (!count) return "";
  return count === 1
    ? "1 failed request was retried on another provider in the last 7 days"
    : `${count} failed requests were retried on another provider in the last 7 days`;
}

// How a failed engine call should be shown: can't reach it, can't sign in, or other.
export function classifyError(err) {
  if (!err || err.status === 0) return "offline";
  if (err.status === 401 || err.status === 403) return "auth";
  return "error";
}

// Overlapping refreshes: only the most recently started one may render.
export function createSequencer() {
  let latest = 0;
  return {
    next: () => ++latest,
    isLatest: (token) => token === latest,
  };
}

export function tzOffsetMinutes(date = new Date()) {
  return -date.getTimezoneOffset() || 0;
}

// Where the engine is and which key to use. The native app injects
// `window.__ORCA__ = { key }` before the page loads; in a plain browser
// (development, screenshots) the key can ride in the URL fragment, which
// is never sent to any server.
export function engineConfig(location, injected) {
  const baseUrl = location.origin;
  if (injected && injected.key) return { baseUrl, key: injected.key };
  const params = new URLSearchParams((location.hash || "").replace(/^#/, ""));
  return { baseUrl, key: params.get("key") || "" };
}

// Joined a team's gateway: agents' spend is tracked there, not here.
export function gatewayLine(gateway) {
  if (!gateway || !gateway.url) return "";
  let host = gateway.url;
  try {
    host = new URL(gateway.url).host;
  } catch {
    /* keep the raw value */
  }
  return `Your agents use your team's gateway at ${host}`;
}

// A newer release, as reported by the engine's daily check. Only this
// repository's release pages are offered as a link.
const RELEASE_PAGES = "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/";

// `canInstall`: this build carries the updater's public key, so the app can
// download, verify and install the update itself.
export function updateLine(update, { canInstall = false } = {}) {
  if (!update || typeof update.url !== "string" || !update.url.startsWith(RELEASE_PAGES)) return null;
  return {
    text: `OrcaRouter Lite ${update.version} is available`,
    url: update.url,
    action: canInstall ? "Install and restart" : "Download",
  };
}

// The line under an agent in setup. Only notes the engine marks as warnings
// (Claude Code: billing moves off the subscription) are styled as warnings.
export function agentNote(agent) {
  if (!agent || !agent.note) return { text: "Orca will update its settings", warn: false };
  return { text: agent.note, warn: Boolean(agent.warn) };
}
