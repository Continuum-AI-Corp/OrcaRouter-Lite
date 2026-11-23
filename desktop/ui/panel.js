// Menu-bar panel: spend today, budget, coding agents, provider health.
import { createEngine, native, toast } from "./api.js";
import { agentRows, budgetView, missingLine, money, providerRows, weekLine } from "./lib.js";

const AGENT_COLORS = {
  "claude-code": "#D97757",
  codex: "#10A37F",
  cursor: "#334155",
  aider: "#14B8A6",
  "gemini-cli": "#4C8DF6",
  other: "#94A2B8",
};
const REFRESH_MS = 15_000;

const engine = createEngine();
const $ = (id) => document.getElementById(id);
const busy = new Set();
let lastSummary = null;
let lastAgents = null;
let confirmTimer = null;

function setEngineState(state) {
  const pill = $("engine-pill");
  const label = { running: "Running", starting: "Starting", stopped: "Offline" }[state];
  pill.className = `pill ${state === "running" ? "ok live" : state === "stopped" ? "err" : "muted"}`;
  $("engine-state").textContent = label;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function renderToday(s) {
  const b = budgetView(s.budget);
  $("today-spend").textContent = money(s.today.spend_microcents);
  $("budget-caption").textContent = b.caption;
  $("budget-edit").textContent = b.hasBudget ? "Edit budget" : "Set budget";
  $("today").className = `today ${b.tone === "warn" || b.tone === "over" ? b.tone : ""}`;
  const bar = $("budget-bar");
  bar.hidden = !b.hasBudget;
  bar.className = `bar ${b.tone === "warn" || b.tone === "over" ? b.tone : ""}`;
  bar.setAttribute("role", "progressbar");
  bar.setAttribute("aria-valuenow", String(Math.round(b.percent)));
  bar.setAttribute("aria-valuemin", "0");
  bar.setAttribute("aria-valuemax", "100");
  bar.setAttribute("aria-label", "Daily budget used");
  requestAnimationFrame(() => (bar.firstElementChild.style.width = `${b.percent}%`));
  $("week-line").textContent = weekLine(s);
  const rescued = s.week.failures_avoided || 0;
  $("rescued").hidden = rescued === 0;
  $("rescued").textContent = `${rescued} ${rescued === 1 ? "request" : "requests"} rescued by fallback this week`;
  $("no-provider").hidden = (s.providers || []).length > 0 || s.hosted?.configured;
}

function actionButton(row) {
  if (!row.action) return null;
  const pending = busy.has(row.id);
  if (row.action === "connect") {
    return el(
      "button",
      { class: "btn btn-primary btn-sm", type: "button", disabled: pending, onclick: () => connect(row) },
      pending ? el("span", { class: "spinner", "aria-hidden": "true" }) : null,
      pending ? "Connecting" : "Connect",
    );
  }
  const confirming = row.confirming;
  return el(
    "button",
    {
      class: `btn btn-sm ${confirming ? "btn-danger" : "btn-ghost"}`,
      type: "button",
      disabled: pending,
      title: "Restore this agent's original settings",
      onclick: () => disconnect(row),
    },
    pending ? "Restoring" : confirming ? "Confirm" : "Disconnect",
  );
}

let confirming = null;

function renderAgents() {
  if (!lastAgents) return;
  const all = agentRows(lastAgents.agents, lastSummary?.agents || [], { includeOther: true });
  const rows = all.filter((r) => r.state !== "missing");
  $("agents-missing").textContent = missingLine(all);
  $("agents-missing").hidden = !missingLine(all);
  const list = $("agents");
  list.replaceChildren(
    ...rows.map((r, i) => {
      r.confirming = confirming === r.id;
      const sub = {
        connected: "Connected",
        available: r.setup === "manual" ? "One paste step" : "Ready to connect",
        unsupported: "Not supported yet",
        missing: "Not installed",
        other: "Your own Lite keys",
      }[r.state];
      return el(
        "li",
        {
          class: `row ${r.state === "missing" || r.state === "unsupported" ? "dim" : ""}`,
          style: `animation-delay:${i * 24}ms`,
          title: r.note || null,
        },
        el("span", { class: "ic", style: `background:${AGENT_COLORS[r.id] || "#94A2B8"}`, "aria-hidden": "true" }, r.initials),
        el("span", { class: "nm" }, el("b", {}, r.name), el("small", {}, sub)),
        el("span", { class: "amt" }, r.today || ""),
        el(
          "span",
          { class: "act" },
          actionButton(r) ||
            (r.state === "connected" || r.state === "other"
              ? null
              : el("span", { class: `pill ${r.badge.tone}` }, r.badge.text)),
        ),
      );
    }),
  );
}

function renderProviders(s) {
  const rows = providerRows(s.providers);
  const list = $("providers");
  if (!rows.length) {
    list.replaceChildren(el("li", { class: "row" }, el("span", { class: "nm" }, el("small", {}, "No providers yet")), el("span")));
    return;
  }
  list.replaceChildren(
    ...rows.map((p) =>
      el("li", { class: "row" }, el("span", { class: "nm" }, el("b", {}, p.name)), el("span", { class: `pill ${p.tone}` }, p.status)),
    ),
  );
}

async function refresh() {
  if (!engine.hasKey) {
    showOffline("The app didn't pass an engine key to this window.");
    return;
  }
  try {
    const [summary, agents] = await Promise.all([engine.summary(), engine.agents()]);
    lastSummary = summary;
    lastAgents = agents;
    $("offline").hidden = true;
    $("panel").hidden = false;
    setEngineState("running");
    renderToday(summary);
    renderAgents();
    renderProviders(summary);
  } catch (err) {
    if (err.status === 0) showOffline();
    else toast("err", "Couldn't refresh", err.message);
  }
}

function showOffline(detail) {
  setEngineState("stopped");
  $("panel").hidden = true;
  $("offline").hidden = false;
  if (detail) $("offline-detail").textContent = detail;
}

async function connect(row) {
  busy.add(row.id);
  renderAgents();
  try {
    const res = await engine.connect(row.id);
    if (res.manual) {
      $("manual-title").textContent = `Finish in ${res.name}`;
      $("manual-note").textContent = res.note;
      $("manual-url").textContent = res.base_url;
      $("manual-key").textContent = res.api_key;
      $("manual").hidden = false;
    } else {
      toast("ok", `${res.name} connected`, "New sessions route through Orca. Your old settings are backed up.");
    }
  } catch (err) {
    toast("err", `Couldn't connect ${row.name}`, err.message, 6000);
  } finally {
    busy.delete(row.id);
    await refresh();
  }
}

async function disconnect(row) {
  if (confirming !== row.id) {
    confirming = row.id;
    renderAgents();
    clearTimeout(confirmTimer);
    confirmTimer = setTimeout(() => {
      confirming = null;
      renderAgents();
    }, 3000);
    return;
  }
  confirming = null;
  clearTimeout(confirmTimer);
  busy.add(row.id);
  renderAgents();
  try {
    const res = await engine.disconnect(row.id);
    toast("ok", `${res.name} disconnected`, "Its original settings are restored.");
  } catch (err) {
    toast("err", `Couldn't disconnect ${row.name}`, err.message, 6000);
  } finally {
    busy.delete(row.id);
    await refresh();
  }
}

// ── budget editing ──
$("budget-edit").addEventListener("click", () => {
  const form = $("budget-form");
  form.hidden = !form.hidden;
  if (!form.hidden) {
    const cents = lastSummary?.budget?.daily_cents;
    $("budget-input").value = cents ? String(cents / 100) : "";
    $("budget-input").focus();
  }
});
$("budget-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const dollars = Number($("budget-input").value);
  if (!Number.isFinite(dollars) || dollars < 0) {
    toast("err", "Enter a budget in dollars", "For example 20 for $20 a day.");
    return;
  }
  await saveBudget(Math.round(dollars * 100));
});
$("budget-clear").addEventListener("click", () => saveBudget(null));

async function saveBudget(cents) {
  try {
    await engine.saveSettings({ daily_budget_cents: cents });
    $("budget-form").hidden = true;
    toast("ok", cents === null ? "Daily budget removed" : `Daily budget set to ${money(cents * 10_000)}`,
      cents === null ? "" : "You'll get a notification at 80% and 100%.");
    await refresh();
  } catch (err) {
    toast("err", "Couldn't save the budget", err.message);
  }
}

// ── manual setup sheet ──
$("manual-close").addEventListener("click", () => ($("manual").hidden = true));
document.querySelectorAll("[data-copy]").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const text = $(btn.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied";
      setTimeout(() => (btn.textContent = "Copy"), 1400);
    } catch {
      const range = document.createRange();
      range.selectNodeContents($(btn.dataset.copy));
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      toast("info", "Press ⌘C to copy", "The text is selected.");
    }
  }),
);

// ── footer ──
$("open-dashboard").addEventListener("click", () => native.openDashboard(engine));
$("open-setup").addEventListener("click", () => native.openSetup(engine));
$("open-setup-cta").addEventListener("click", () => native.openSetup(engine));
$("retry").addEventListener("click", refresh);
if (native.available()) {
  $("quit").hidden = false;
  $("quit").addEventListener("click", () => native.quit());
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
setInterval(() => {
  if (!document.hidden) refresh();
}, REFRESH_MS);
refresh();
