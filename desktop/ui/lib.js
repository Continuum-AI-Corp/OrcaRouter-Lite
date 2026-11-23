// View logic for the Orca app. Pure functions only: no DOM, no network,
// so they run under `node --test` (desktop/tests) and in the webview alike.

export function money(microcents) {
  const cents = Math.floor((Math.max(0, Number(microcents) || 0) + 5_000) / 10_000);
  const dollars = Math.floor(cents / 100).toLocaleString("en-US");
  return `$${dollars}.${String(cents % 100).padStart(2, "0")}`;
}

export function budgetView(budget) {
  if (!budget || budget.daily_cents === null || budget.daily_cents === undefined) {
    return { hasBudget: false, tone: "none", caption: "No daily budget", percent: 0, limit: null };
  }
  const limit = money(budget.daily_cents * 10_000);
  const percent = Math.max(0, Math.min(100, Number(budget.used_percent) || 0));
  return { hasBudget: true, tone: budget.state, caption: `of ${limit} budget`, percent, limit };
}

const ORDER = { connected: 0, available: 1, unsupported: 2, missing: 3 };

function initials(name) {
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase();
  return (name.slice(0, 1).toUpperCase() + name.slice(1, 2).toLowerCase()).padEnd(2, " ");
}

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
      initials: "··",
      state: "other",
      setup: null,
      badge: { text: "Direct", tone: "muted" },
      action: null,
      note: "Requests made with your own Lite keys.",
      today: money(other.today_microcents),
      week: other.week_microcents,
      index: rows.length,
    });
  }
  return rows;
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
  healthy: { status: "Healthy", tone: "ok" },
  degraded: { status: "Degraded", tone: "warn" },
  idle: { status: "Idle", tone: "muted" },
};

export function providerRows(providers) {
  return (providers || []).map((p) => ({
    id: p.provider,
    name: PROVIDER_NAMES[p.provider] || p.provider,
    ...(HEALTH[p.state] || HEALTH.idle),
  }));
}

export function weekLine(summary) {
  const w = summary.week;
  const base = `This week ${money(w.spend_microcents)}`;
  return w.saved_microcents > 0 ? `${base} · saved ${money(w.saved_microcents)}` : base;
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

// Agents that aren't installed take one line instead of a row each.
export function missingLine(rows) {
  const names = rows.filter((r) => r.state === "missing").map((r) => r.name);
  return names.length ? `Not installed: ${names.join(", ")}` : "";
}
