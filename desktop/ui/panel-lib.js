// View logic for the panel's roadmap features (free models, offers, agent
// sheet, model picker, local models, settings, team, sharing, orca:// links).
// Pure functions only, like lib.js: no DOM, no network. Tests:
// desktop/tests/panel.test.mjs.
import { agentRows, money, withRef } from "./lib.js";

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// ── formatting ──

// One request's cost: fractions of a cent matter here.
export function costShort(microcents) {
  const m = Math.max(0, Number(microcents) || 0);
  if (m === 0) return "$0";
  if (m >= 1_000_000) return money(m);
  const thousandths = Math.floor((m + 500) / 1000);
  if (thousandths === 0) return "<$0.001";
  return `$0.${String(thousandths).padStart(3, "0")}`;
}

export function tokens(n) {
  const v = Math.max(0, Number(n) || 0);
  if (v < 1000) return String(Math.round(v));
  if (v < 100_000) return `${(v / 1000).toFixed(1)}K`;
  if (v < 1_000_000) return `${Math.round(v / 1000)}K`;
  return `${(v / 1_000_000).toFixed(1)}M`;
}

export const tokenFlow = (input, output) => `${tokens(input)}→${tokens(output)}`;

// "claude-sonnet-4-6" → "sonnet-4-6", "deepseek/deepseek-v4-flash" → "v4-flash".
export function shortModel(id) {
  if (!id) return "—";
  const bare = String(id).includes("/") ? String(id).slice(String(id).indexOf("/") + 1) : String(id);
  return bare.replace(/^(claude|deepseek)-/, "");
}

const pad2 = (n) => String(n).padStart(2, "0");

export function localOffsetMinutes(date = new Date()) {
  return -date.getTimezoneOffset() || 0;
}

// 24-hour local time of an ISO timestamp.
export function clockTime(iso, tzOffsetMinutes = localOffsetMinutes()) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const d = new Date(t + tzOffsetMinutes * 60_000);
  return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
}

// Local calendar day, as the engine stores dismissals ("YYYY-MM-DD").
export function localDate(date = new Date(), tzOffsetMinutes = localOffsetMinutes(date)) {
  const d = new Date(date.getTime() + tzOffsetMinutes * 60_000);
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
}

// The home folder, from paths of agent configs (each sits in a dot-folder or
// dot-file right under home), or null when they don't agree.
export function guessHome(paths) {
  const homes = new Set();
  for (const p of paths || []) {
    if (!p) continue;
    const m = String(p).match(/^(.*?)[/\\]\./);
    if (!m || !m[1]) return null;
    homes.add(m[1]);
  }
  return homes.size === 1 ? [...homes][0] : null;
}

// Paths shown to people use ~ for the home folder.
export function tildePath(path, home = null) {
  if (!path) return "";
  const p = String(path);
  if (home && (p.startsWith(`${home}/`) || p.startsWith(`${home}\\`))) return `~${p.slice(home.length)}`;
  const unix = p.match(/^(?:\/Users\/[^/]+|\/home\/[^/]+|\/root)(\/.*)?$/);
  if (unix) return `~${unix[1] || ""}`;
  const win = p.match(/^[A-Za-z]:\\Users\\[^\\]+(\\.*)?$/);
  if (win) return `~${win[1] || ""}`;
  return p;
}

const FAMILIES = [
  [/^claude/, { vendor: "Anthropic", family: "Claude", provider: "anthropic" }],
  [/^(gpt|o\d|codex|chatgpt)/, { vendor: "OpenAI", family: "GPT", provider: "openai" }],
  [/^gemini/, { vendor: "Google", family: "Gemini", provider: "google" }],
  [/^deepseek/, { vendor: "DeepSeek", family: "DeepSeek", provider: "deepseek" }],
  [/^grok/, { vendor: "xAI", family: "Grok", provider: "xai" }],
  [/^(kimi|moonshot)/, { vendor: "Moonshot", family: "Kimi", provider: "moonshot" }],
  [/^qwen/, { vendor: "Qwen", family: "Qwen", provider: "qwen" }],
  [/^glm/, { vendor: "Z.ai", family: "GLM", provider: "zai" }],
  [/^minimax/, { vendor: "MiniMax", family: "MiniMax", provider: "minimax" }],
  [/^(mistral|codestral|devstral|magistral)/, { vendor: "Mistral", family: "Mistral", provider: "mistral" }],
];

export function modelFamily(id) {
  if (!id) return null;
  const s = String(id).toLowerCase();
  const bare = s.includes("/") ? s.slice(s.lastIndexOf("/") + 1) : s;
  for (const [re, f] of FAMILIES) if (re.test(bare)) return { ...f };
  return null;
}

const PROVIDERS = {
  orcarouter: "OrcaRouter",
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
  gemini: "Google",
  deepseek: "DeepSeek",
  xai: "xAI",
  mistral: "Mistral",
  groq: "Groq",
  together: "Together",
  fireworks: "Fireworks",
  cohere: "Cohere",
  moonshot: "Moonshot",
  qwen: "Qwen",
  minimax: "MiniMax",
  zai: "Z.ai",
  openrouter: "OpenRouter",
  local: "This computer",
};

export const providerName = (id) => PROVIDERS[id] || String(id || "");

// ── H0: free models first ──

export function todayFreeLine(today) {
  const free = Number(today?.free_requests) || 0;
  if (!free) return "";
  const paid = Math.max(0, (Number(today.requests) || 0) - free);
  const base = `${plural(free, "request")} on OrcaRouter's free models`;
  return paid ? `${base} · ${paid} paid` : base;
}

export function paidModelPrompt(hosted) {
  if (!hosted || !hosted.configured || hosted.models !== "free") return null;
  const n = Number(hosted.needs_paid_today) || 0;
  return {
    text: n ? `${plural(n, "request")} needed a paid model today.` : "Agents use OrcaRouter's free models.",
    action: "Use a paid model",
    confirm: "Paid models cost the provider's price per request. Free models still come first.",
    confirmAction: "Use paid models",
    urgent: n > 0,
  };
}

// ── H2: the backup offer ──

export function backupOfferView(offer) {
  const n = Number(offer?.failed_today) || 0;
  if (!n) return null;
  const family = (offer.models || []).map(modelFamily).find(Boolean)?.family;
  const tail = family ? `none of your other keys has ${family}.` : `none of your other keys could take ${n === 1 ? "it" : "them"}.`;
  return {
    lead: `${plural(n, "request")} failed today.`,
    rest: `${providerName(offer.provider)} was overloaded and ${tail}`,
    body: "Add OrcaRouter's gateway as a backup and Orca sends only requests like these to it. You pay per request at the provider's price; nothing else changes.",
  };
}

// ── H3: the model an agent asked for ──

export function substitutionHint(subs) {
  const top = (subs || [])[0];
  if (!top) return "";
  const asked = modelFamily(top.requested);
  const got = modelFamily(top.served);
  if (asked && got && asked.family !== got.family) return `Getting ${got.family} instead of ${asked.family}`;
  return `Getting ${top.served} instead`;
}

// `hosted`: the summary's hosted block. action: "setup" (add an OrcaRouter
// key), "paid" (turn on paid models), or null (OrcaRouter can already serve it).
export function substitutionNote(agentName, sub, hosted = {}) {
  const f = modelFamily(sub.requested);
  const times = sub.count === 1 ? "once" : `${sub.count} times`;
  const why = f ? `You have no ${f.vendor} key` : "You have no key for it";
  let action = "setup";
  if (hosted?.configured) action = hosted.models === "free" ? "paid" : null;
  return {
    text: `${agentName} asked for ${sub.requested} ${times} today. ${why}, so ${sub.served} answered.`,
    offerTitle: `Get ${f ? f.family : sub.requested} through OrcaRouter`,
    offerDetail: f ? `Pay per token at ${f.vendor}'s price, no subscription` : "Pay per token at the provider's price, no subscription",
    keep: `Keep using ${sub.served}`,
    action,
  };
}

// ── agent rows: D5 "changed", H3 hint, D3 paused ──

export function panelAgentRows(agents, spend = [], opts = { includeOther: true }) {
  const byId = Object.fromEntries((spend || []).map((s) => [s.id, s]));
  const raw = Object.fromEntries((agents || []).map((a) => [a.id, a]));
  return agentRows(agents, spend, opts).map((row) => {
    const a = raw[row.id] || {};
    const s = byId[row.id] || {};
    const out = { ...row, hint: false, opens: false, configPath: a.config_path || null };
    if (row.state !== "connected") return out;
    out.opens = true;
    if (a.changed || s.state === "changed") {
      return { ...out, state: "changed", subtitle: "Its settings changed", action: "reconnect", badge: { text: "Changed", tone: "warn" } };
    }
    if (s.paused && s.budget_cents !== null && s.budget_cents !== undefined) {
      return { ...out, subtitle: `Paused at its ${money(s.budget_cents * 10_000)} daily budget`, paused: true };
    }
    const hint = substitutionHint(s.substitutions);
    if (hint) return { ...out, subtitle: hint, hint: true };
    return out;
  });
}

export function changedText(agentName, configPath, home = null) {
  const where = configPath ? ` in ${tildePath(configPath, home)}` : "";
  return `Something replaced Orca's settings${where}, probably ${agentName}'s last update. Its requests aren't going through Orca.`;
}

// ── H4: OrcaRouter spend ──

export function hostedProviderDetail(h) {
  const spend = Number(h?.month_spend_microcents) || 0;
  const reqs = Number(h?.month_requests) || 0;
  const rescued = Number(h?.month_rescued) || 0;
  if (!spend && !reqs) return "No requests this month";
  const tail = rescued ? `${plural(rescued, "request")} rescued` : plural(reqs, "request");
  return `${money(spend)} this month · ${tail}`;
}

const HEALTH = {
  healthy: { status: "Healthy", tone: "ok", detail: "Your key" },
  degraded: { status: "Degraded", tone: "warn", detail: "Most requests failed in the last hour" },
  idle: { status: "Idle", tone: "muted", detail: "Your key · no requests in the last hour" },
};

export const OUT_OF_CREDIT = {
  lead: "OrcaRouter is out of credit.",
  text: "Orca is using your own keys only. Requests only OrcaRouter can serve will fail until you add credit.",
  action: "Add credit",
};

export function panelProviderRows(summary) {
  const hosted = summary?.hosted || {};
  const list = [...(summary?.providers || [])];
  if (hosted.configured && !list.some((p) => p.provider === "orcarouter")) list.push({ provider: "orcarouter", state: "idle" });
  const rows = list.map((p) => {
    if (p.provider === "orcarouter") {
      return {
        id: "orcarouter",
        name: "OrcaRouter",
        initials: "OR",
        detail: hostedProviderDetail(hosted),
        status: hosted.out_of_credit ? "Out of credit" : null,
        tone: hosted.out_of_credit ? "err" : "ok",
        link: hosted.console_url ? { text: "Balance", url: withRef(hosted.console_url, "lite-panel") } : null,
      };
    }
    const h = HEALTH[p.state] || HEALTH.idle;
    return { id: p.provider, name: providerName(p.provider), initials: null, detail: p.provider === "local" ? "Models on this computer" : h.detail, status: h.status, tone: h.tone, link: null };
  });
  rows.sort((a, b) => (a.id === "orcarouter" ? -1 : b.id === "orcarouter" ? 1 : 0));
  return rows;
}

// ── H5: the model picker ──

function perM(v) {
  if (v === 0) return "$0";
  if (v > 0 && v < 0.1 && Math.round(v * 100) !== v * 100) return `$${Number(v.toFixed(3))}`;
  return `$${v.toFixed(2)}`;
}

export function modelPrice(m) {
  if (m.free) return m.provider === "local" ? "$0 · on this computer" : "$0 · free model";
  const i = m.input_per_m;
  const o = m.output_per_m;
  if ((i === null || i === undefined) && (o === null || o === undefined)) return "Price not listed";
  return `${perM(i || 0)} / ${perM(o || 0)} per M tokens`;
}

const TAGS = {
  yours: { tag: "Your key", tone: "ok" },
  local: { tag: "Local", tone: "muted" },
  free: { tag: "Free", tone: "ok" },
  paid: { tag: "OrcaRouter", tone: "brand" },
};

function unavailableReason(groupId, { hostedConfigured, hostedModels }) {
  if (groupId === "free" || groupId === "paid") {
    if (!hostedConfigured) return "Needs an OrcaRouter key";
    if (groupId === "paid" && hostedModels === "free") return "Paid models are off";
  }
  if (groupId === "local") return "Not running, or turned off below";
  return "Not available right now";
}

export function pickerView(groups, { query = "", hostedConfigured = false, hostedModels = "free" } = {}) {
  const words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (m) => words.every((w) => `${m.id} ${m.name}`.toLowerCase().includes(w));
  let total = 0;
  let count = 0;
  const out = [];
  for (const g of groups || []) {
    total += Number(g.total) || (g.models || []).length;
    const items = (g.models || []).filter(matches).map((m) => ({
      id: m.id,
      name: m.name || m.id,
      groupId: g.id,
      price: modelPrice(m),
      tag: TAGS[g.id]?.tag || "",
      tagTone: TAGS[g.id]?.tone || "muted",
      available: Boolean(m.available),
      reason: m.available ? "" : unavailableReason(g.id, { hostedConfigured, hostedModels }),
      model: m,
    }));
    count += items.length;
    if (items.length) out.push({ id: g.id, label: g.label, items });
  }
  return { total, matches: count, groups: out };
}

export function pickerChoice(model, groupId, { hostedConfigured = false, hostedModels = "free" } = {}) {
  if (model.available) return { kind: "select" };
  if (groupId === "free" || groupId === "paid") {
    if (!hostedConfigured) return { kind: "needs_key" };
    if (groupId === "paid" && hostedModels === "free") return { kind: "needs_paid" };
  }
  return { kind: "unavailable" };
}

// ── D3: per-agent budget and the request log ──

export function agentBudgetView(todayMicrocents, cents) {
  if (cents === null || cents === undefined) return { hasBudget: false, caption: "", percent: 0, tone: "none" };
  const limit = cents * 10_000;
  const spent = Math.max(0, Number(todayMicrocents) || 0);
  const pct = limit === 0 ? (spent > 0 ? 100 : 0) : (100 * spent) / limit;
  const tone = pct >= 100 ? "over" : pct >= 80 ? "warn" : "ok";
  return { hasBudget: true, caption: `${money(spent)} of ${money(limit)}`, percent: Math.min(100, Math.round(pct)), tone };
}

function requestNote(r, time) {
  const asked = modelFamily(r.model_requested);
  const firstName = asked && asked.provider !== r.provider ? asked.vendor : "The first provider";
  if (r.status < 400) {
    if (r.rescued) return `${firstName} didn't answer at ${time}; Orca sent the request to ${providerName(r.provider)}.`;
    if (r.note === "substituted") {
      return `Asked for ${r.model_requested} at ${time}; no key of yours serves it, so ${r.model} answered.`;
    }
    return "";
  }
  if (r.note === "no_fallback") return `${providerName(r.provider) || "The provider"} failed at ${time} and none of your other keys could take it.`;
  if (r.note === "needs_paid") return `Needed a paid model at ${time}; OrcaRouter is on free models only.`;
  if (r.note === "out_of_credit") return `OrcaRouter was out of credit at ${time}.`;
  return `Failed at ${time} (${r.status}).`;
}

export function requestRows(requests, { tzOffsetMinutes = localOffsetMinutes() } = {}) {
  let previous = null; // a run of the same failure is explained once
  return (requests || []).map((r) => {
    const time = clockTime(r.at, tzOffsetMinutes);
    const failed = Number(r.status) >= 400;
    const kind = failed ? `${r.status}|${r.note}|${r.provider}|${r.model_requested}` : null;
    const repeat = kind !== null && kind === previous;
    previous = kind;
    return {
      time,
      model: shortModel(r.model || r.model_requested),
      fullModel: r.model || r.model_requested || "",
      tokens: tokenFlow(r.input_tokens, r.output_tokens),
      cost: costShort(r.cost_microcents),
      tag: failed ? "failed" : r.rescued ? "rescued" : null,
      note: repeat ? "" : requestNote(r, time),
    };
  });
}

// ── D4: test results ──

export function testResultView(res) {
  if (!res) return null;
  if (res.ok === true) {
    const s = Number(res.seconds) || 0;
    const secs = s < 10 ? s.toFixed(1) : String(Math.round(s));
    const using = res.config_path ? `, using ${tildePath(res.config_path)}` : "";
    return { tone: "ok", lead: "Works.", text: `Answered in ${secs} s by ${res.model}${using}.` };
  }
  const text = res.error || "The test didn't finish. Try again.";
  return { tone: res.ok === null ? "info" : "err", lead: "", text };
}

// ── P2 · D1 + H6: this computer ──

function ctxLabel(n) {
  if (!n) return "";
  if (n >= 1_048_576) return `${Math.round(n / 1_048_576)}M context`;
  return `${Math.max(1, Math.round(n / 1024))}K context`;
}

export function localModelDetail(m) {
  const caps = [m.tools ? "Tools" : null, m.vision ? (m.tools ? "images" : "Images") : null].filter(Boolean).join(", ");
  const parts = [caps, ctxLabel(m.context)].filter(Boolean).join(", ");
  return m.tools ? parts : `${parts} · no tool use`;
}

const RUNTIME_INITIALS = { ollama: "OL", lmstudio: "LM", llamacpp: "LC" };

export function localView(runtimes) {
  const list = (runtimes || []).map((rt) => {
    const models = Array.isArray(rt.models) ? rt.models : [];
    const count = Array.isArray(rt.models) ? rt.models.length : Number(rt.models) || 0;
    return {
      id: rt.id,
      name: rt.name,
      initials: RUNTIME_INITIALS[rt.id] || String(rt.name || "?").slice(0, 2).toUpperCase(),
      running: Boolean(rt.running),
      detail: rt.running ? `${rt.url} · found ${plural(count, "model")}` : `Not running · checks ${rt.url}`,
      status: rt.running ? "Running" : "Off",
      models: models.map((m) => ({ id: m.id, name: m.name, detail: localModelDetail(m), enabled: Boolean(m.enabled) })),
    };
  });
  return { anyRunning: list.some((r) => r.running), runtimes: list };
}

// The new local_models list after one model is switched on or off.
export function toggleLocal(runtimes, selection, id, on) {
  const all = (runtimes || []).flatMap((rt) => (Array.isArray(rt.models) ? rt.models : []));
  const current = selection ? [...selection] : all.filter((m) => m.enabled).map((m) => m.id);
  const without = current.filter((x) => x !== id);
  return on ? [...without, id] : without;
}

export function weekSplitLine(week) {
  const local = Number(week?.local_requests) || 0;
  const hosted = Number(week?.hosted_requests) || 0;
  const parts = [];
  if (local) {
    const saved = Number(week.local_saved_microcents) || 0;
    parts.push(saved ? `${local} answered locally, about ${money(saved)} you didn't spend` : `${local} answered locally`);
  }
  if (hosted) parts.push(`${hosted} through OrcaRouter`);
  return parts.join(" · ");
}

// ── D7: settings ──

function wholeNumber(raw) {
  const s = String(raw ?? "").trim();
  if (s === "") return { value: null };
  if (!/^\d+$/.test(s)) return { bad: true };
  return { value: Number(s) };
}

export function routerSettingsInput(retries, cooldown) {
  const r = wholeNumber(retries);
  if (r.bad || (r.value !== null && r.value > 5)) {
    return { values: null, error: { field: "retries", message: "Retries is a whole number from 0 to 5." } };
  }
  const c = wholeNumber(cooldown);
  if (c.bad || (c.value !== null && c.value > 3600)) {
    return { values: null, error: { field: "cooldown", message: "Rest a failing provider for 0 to 3600 seconds." } };
  }
  return { values: { router_num_retries: r.value, router_cooldown_seconds: c.value }, error: null };
}

export function benchmarkKeyView(status) {
  if (!status?.configured) return { mode: "empty", hint: "", text: "" };
  if (status.source === "env") {
    return { mode: "env", hint: status.hint || "", text: "Set in this computer's environment (ARTIFICIAL_ANALYSIS_API_KEY). Change it there." };
  }
  return { mode: "saved", hint: status.hint || "", text: "Saved on this computer, encrypted." };
}

// ── H7: team ──

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return String(url || "");
  }
}

export function teamGatewayView(gateway) {
  if (!gateway?.url) return { joined: false, title: "Join your team's gateway", detail: "Use the address and key your platform team gave you.", initials: "" };
  const host = hostOf(gateway.url);
  return { joined: true, title: "Team gateway", detail: `${host} · spend tracked by your team`, initials: host.replace(/[^a-z0-9]/gi, "").slice(0, 2).toUpperCase() };
}

// ── V2: the savings card ──

export function listNames(names) {
  const n = (names || []).filter(Boolean);
  if (n.length <= 1) return n[0] || "";
  if (n.length === 2) return `${n[0]} and ${n[1]}`;
  if (n.length === 3) return `${n[0]}, ${n[1]} and ${n[2]}`;
  return `${n[0]}, ${n[1]} and ${n.length - 2} more`;
}

export const LANDING_URL = "https://continuum-ai-corp.github.io/OrcaRouter-Lite/";

export function shareCardText(card) {
  const saved = Number(card?.week_saved_microcents) || 0;
  const rescued = Number(card?.rescued) || 0;
  const local = Number(card?.local_requests) || 0;
  const agents = listNames(card?.agents || []);
  let headline = "Orca kept my coding agents on budget";
  if (saved > 0) headline = `Orca saved me ${money(saved)}`;
  else if (local > 0) headline = `Orca answered ${plural(local, "request")} on my computer`;
  let sub = "";
  if (rescued > 0) sub = `and rescued ${plural(rescued, "request")}`;
  else if (saved > 0 && local > 0) sub = `and answered ${local} locally`;
  const across = agents ? ` across ${agents}` : "";
  const post = `This week ${headline}${sub ? ` ${sub}` : ""}${across}.`;
  return {
    kicker: agents ? `This week, across ${agents}` : "This week, with my coding agents",
    headline,
    sub,
    brand: "Orca Router",
    footer: "github.io/OrcaRouter-Lite",
    post,
    shareable: saved > 0 || rescued > 0 || local > 0,
    alt: [agents ? `This week, across ${agents}` : "This week", headline, sub].filter(Boolean).join(". "),
  };
}

// Only our landing page is shared, always with ref=lite-card.
export function shareIntentUrl(kind, { text, link }) {
  const tagged = withRef(link, "lite-card");
  if (!tagged || !tagged.startsWith(LANDING_URL)) return null;
  if (kind === "x") {
    const u = new URL("https://x.com/intent/post");
    if (text) u.searchParams.set("text", text);
    u.searchParams.set("url", tagged);
    return u.toString();
  }
  if (kind === "linkedin") {
    const u = new URL("https://www.linkedin.com/sharing/share-offsite/");
    u.searchParams.set("url", tagged);
    return u.toString();
  }
  return null;
}

// Largest font size from max down to min at which `measure(text, size)` fits.
export function fitFontSize(measure, text, maxWidth, { max, min }) {
  for (let size = max; size > min; size -= 1) if (measure(text, size) <= maxWidth) return size;
  return min;
}

function fitLine(measure, text, maxWidth, sizes) {
  const size = fitFontSize(measure, text, maxWidth, sizes);
  let t = text;
  while (t.length > 1 && measure(t, size) > maxWidth) t = `${t.slice(0, -2).trimEnd()}…`;
  return { text: t, size };
}

// Where each line of the card goes, in canvas pixels. `measure(text, size)`
// returns the rendered width (canvas measureText in the page, a stub in tests).
export function cardLayout(measure, t, { width = 1200, height = 630 } = {}) {
  const pad = Math.round(width * 0.06);
  const inner = width - 2 * pad;
  const kicker = fitLine(measure, t.kicker, inner, { max: Math.round(height * 0.058), min: Math.round(height * 0.035) });
  const headline = fitLine(measure, t.headline, inner, { max: Math.round(height * 0.12), min: Math.round(height * 0.06) });
  const sub = fitLine(measure, t.sub || "", inner, { max: headline.size, min: Math.round(height * 0.05) });
  const footerSize = Math.round(height * 0.048);
  const brandWidth = measure(t.brand || "", footerSize);
  const footer = fitLine(measure, t.footer, inner - brandWidth - footerSize * 3, { max: footerSize, min: Math.round(height * 0.03) });
  const top = pad + kicker.size;
  const headY = Math.round(height * 0.5);
  const footY = height - pad;
  return {
    pad,
    kicker: { ...kicker, x: pad, y: top },
    headline: { ...headline, x: pad, y: headY },
    sub: { ...sub, x: pad, y: headY + Math.round(headline.size * 1.15) },
    // Logo at the left of the footer, brand next to it, link at the right edge.
    logo: { x: pad, y: footY - footerSize * 1.4, size: footerSize * 1.6 },
    brand: { text: t.brand || "", size: footerSize, x: pad + footerSize * 2.1, y: footY },
    footer: { ...footer, x: width - pad - measure(footer.text, footer.size), y: footY },
  };
}

// ── V3: orca:// links ──

function privateHost(hostname) {
  const h = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (h === "localhost" || h === "::1" || h.endsWith(".local")) return true;
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (!m) return false;
  const [a, b] = [Number(m[1]), Number(m[2])];
  return a === 127 || a === 10 || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31);
}

// The confirmation sheet for a link, or null to ignore it. A link never acts
// on its own and never carries a key.
export function linkSheet(link, agents) {
  if (!link || typeof link !== "object") return null;
  if (link.action === "connect") {
    if (typeof link.agent !== "string" || !/^[a-z0-9-]{1,64}$/.test(link.agent)) return null;
    const a = (agents || []).find((x) => x.id === link.agent);
    if (!a) return null;
    let detail = `Orca changes ${a.name}'s settings so its requests go through Orca. Its old settings are backed up.`;
    let ready = true;
    if (a.connected) [detail, ready] = [`${a.name} is already connected to Orca.`, false];
    else if (!a.installed) [detail, ready] = [`${a.name} isn't installed on this computer.`, false];
    else if (a.setup === "unsupported") [detail, ready] = [`Orca can't connect ${a.name} yet.`, false];
    else if (a.setup === "manual") detail = `Orca shows a base URL and key to paste into ${a.name}.`;
    return { kind: "connect", agentId: a.id, name: a.name, title: `Connect ${a.name}`, detail, ready, confirm: "Connect" };
  }
  if (link.action === "join") {
    let u;
    try {
      u = new URL(link.gateway);
    } catch {
      return null;
    }
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    if (u.username || u.password || u.search || u.hash) return null; // links never carry keys
    const insecure = u.protocol === "http:";
    if (insecure && !privateHost(u.hostname)) return null;
    const url = `${u.protocol}//${u.host}${u.pathname === "/" ? "" : u.pathname.replace(/\/$/, "")}`;
    return {
      kind: "join",
      url,
      host: u.host,
      insecure,
      title: "Join a team gateway",
      detail: "Your agents send their requests to this gateway, and your team sees their spend.",
      confirm: "Join",
    };
  }
  return null;
}

// Setup reads `step` from its URL fragment to open at that step.
export const SETUP_STEPS = ["orcarouter", "gateway"];

export function setupHash(hash, step) {
  if (!SETUP_STEPS.includes(step)) throw new Error(`unknown setup step: ${step}`);
  const params = new URLSearchParams(String(hash || "").replace(/^#/, ""));
  params.set("step", step);
  return `#${params.toString()}`;
}
