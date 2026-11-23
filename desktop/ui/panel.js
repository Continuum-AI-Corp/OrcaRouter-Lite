// Menu-bar panel: spend today, daily alert, coding agents, provider health.
import { createEngine, native, toast } from "./api.js";
import {
  AGENT_COLORS,
  agentRows,
  budgetView,
  classifyError,
  createSequencer,
  gatewayLine,
  updateLine,
  missingLine,
  money,
  providerRows,
  rescuedLine,
  weekLine,
} from "./lib.js";

const REFRESH_MS = 15_000;
const CONFIRM_MS = 3_000;
const CONFIRM_GUARD_MS = 350; // a double-click must not confirm a disconnect
const OTHER_GLYPH =
  '<svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true"><rect x="1" y="1" width="4" height="4" rx="1"/><rect x="7" y="1" width="4" height="4" rx="1"/><rect x="1" y="7" width="4" height="4" rx="1"/><rect x="7" y="7" width="4" height="4" rx="1"/></svg>';

const engine = createEngine();
const seq = createSequencer();
const $ = (id) => document.getElementById(id);
const busy = new Set();
const seenRows = new Set();
let lastSummary = null;
let lastAgents = null;
let confirming = null; // { id, armedAt }
let confirmTimer = null;
let lastAnnounced = "";

function announce(text) {
  if (text && text !== lastAnnounced) {
    lastAnnounced = text;
    $("announce").textContent = text;
  }
}

function setEngineState(state) {
  const label = { running: "Router on", starting: "Starting", stopped: "Offline", auth: "Signed out" }[state];
  const tone = { running: "ok", starting: "muted starting", stopped: "err", auth: "warn" }[state];
  $("engine-pill").className = `pill ${tone}`;
  $("engine-state").textContent = label;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

// ── today ──

function renderToday(s) {
  const b = budgetView(s.budget, s.today.spend_microcents);
  $("today-spend").textContent = money(s.today.spend_microcents);
  $("budget-caption").textContent = b.caption;
  $("budget-edit").textContent = b.hasBudget ? "Edit budget" : "Set daily budget";
  $("today").className = `today ${b.tone === "warn" || b.tone === "over" ? b.tone : ""}`;

  const bar = $("budget-bar");
  const fill = bar.firstElementChild;
  const firstShow = bar.hidden && b.hasBudget;
  bar.hidden = !b.hasBudget;
  bar.className = `bar ${b.tone === "warn" || b.tone === "over" ? b.tone : ""}`;
  bar.setAttribute("aria-valuenow", String(Math.round(b.percent)));
  bar.setAttribute("aria-valuetext", b.ariaText);
  if (firstShow) {
    fill.style.width = "0%";
    void fill.offsetWidth; // fill from 0 the first time it appears
  }
  requestAnimationFrame(() => (fill.style.width = `${b.percent}%`));

  $("week-line").textContent = weekLine(s);
  const rescued = rescuedLine(s.week.failures_avoided || 0);
  $("rescued").hidden = !rescued;
  $("rescued").textContent = rescued;
  $("no-provider").hidden = (s.providers || []).length > 0 || Boolean(s.hosted?.configured) || Boolean(s.gateway);
  const gw = gatewayLine(s.gateway);
  $("gateway").hidden = !gw;
  $("gateway-text").textContent = gw;
  const upd = updateLine(s.update);
  $("update").hidden = !upd;
  $("update-text").textContent = upd ? upd.text : "";
  $("update-get").dataset.url = upd ? upd.url : "";
  if (b.tone === "warn" || b.tone === "over") announce(b.caption);
}

// ── agents ──

function actionButton(row) {
  if (!row.action) return null;
  const pending = busy.has(row.id);
  if (row.action === "connect") {
    return el(
      "button",
      { class: "btn btn-primary btn-sm", type: "button", "data-act": "connect", disabled: pending, "aria-label": `Connect ${row.name}` },
      pending ? el("span", { class: "spinner", "aria-hidden": "true" }) : null,
      pending ? "Connecting" : "Connect",
    );
  }
  const isConfirming = confirming?.id === row.id;
  return el(
    "button",
    {
      class: `btn btn-sm ${isConfirming ? "btn-danger confirming" : "btn-ghost"}`,
      type: "button",
      "data-act": "disconnect",
      disabled: pending,
      "aria-label": isConfirming ? `Confirm disconnecting ${row.name}` : `Disconnect ${row.name}`,
      title: "Restore this agent's original settings",
    },
    pending ? "Restoring" : isConfirming ? "Confirm?" : "Disconnect",
  );
}

function tile(row) {
  const ic = el("span", { class: "ic", style: `background:${AGENT_COLORS[row.id] || AGENT_COLORS.other}`, "aria-hidden": "true" });
  if (row.id === "other") ic.innerHTML = OTHER_GLYPH; // constant markup: "everything else"
  else ic.textContent = row.initials;
  return ic;
}

function renderAgents() {
  if (!lastAgents) return;
  const all = agentRows(lastAgents.agents, lastSummary?.agents || [], { includeOther: true });
  const rows = all.filter((r) => r.state !== "missing");
  const missing = missingLine(all);
  $("agents-missing").textContent = missing;
  $("agents-missing").hidden = !missing;

  // Rows are keyed by agent id and reused, so a refresh doesn't replay their
  // entrance, and keyboard focus stays on the same row's button.
  const focused = document.activeElement?.closest?.("li[data-id]")?.dataset.id;
  const list = $("agents");
  const existing = new Map([...list.children].map((li) => [li.dataset.id, li]));
  const next = rows.map((r) => {
    const li = existing.get(r.id) || el("li", { "data-id": r.id });
    const isNew = !seenRows.has(r.id);
    seenRows.add(r.id);
    li.className = ["row", r.state === "unsupported" ? "dim" : "", isNew ? "enter" : ""].filter(Boolean).join(" ");
    li.title = r.note || "";
    const badge = r.badge && r.state !== "connected" ? el("span", { class: `pill ${r.badge.tone}` }, r.badge.text) : null;
    li.replaceChildren(
      tile(r),
      el("span", { class: "nm" }, el("b", {}, r.name), el("small", {}, r.subtitle)),
      el("span", { class: "amt" }, r.today || ""),
      el("span", { class: "act" }, actionButton(r) || badge),
    );
    return li;
  });
  list.replaceChildren(...next);
  if (focused) list.querySelector(`li[data-id="${CSS.escape(focused)}"] button`)?.focus();
}

$("agents").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn || !lastAgents) return;
  const id = btn.closest("li").dataset.id;
  const row = agentRows(lastAgents.agents, lastSummary?.agents || []).find((r) => r.id === id);
  if (!row) return;
  if (btn.dataset.act === "connect") connect(row);
  else disconnect(row);
});

function renderProviders(s) {
  const rows = providerRows(s.providers);
  const list = $("providers");
  if (!rows.length) {
    list.replaceChildren(el("li", { class: "row" }, el("span", { class: "nm" }, el("small", {}, "No providers yet")), el("span")));
    return;
  }
  list.replaceChildren(
    ...rows.map((p) =>
      el(
        "li",
        { class: "row" },
        el("span", { class: "nm" }, el("b", {}, p.name), p.detail ? el("small", {}, p.detail) : null),
        el("span", { class: `pill ${p.tone}` }, p.status),
      ),
    ),
  );
}

// ── refresh ──

function fitWindow() {
  // The native panel is sized to its content: no dead space under the list.
  requestAnimationFrame(() => {
    const panel = $("panel");
    const h = panel.hidden ? 360 : panel.scrollHeight;
    native.resizePanel(Math.max(360, Math.min(680, Math.ceil(h)))).catch(() => {});
  });
}

async function refresh() {
  if (!engine.hasKey) {
    showOffline("auth", "Something went wrong opening this window. Quit and reopen Orca.");
    return;
  }
  const token = seq.next();
  try {
    const [summary, agents] = await Promise.all([engine.summary(), engine.agents()]);
    if (!seq.isLatest(token)) return; // a newer refresh already rendered
    lastSummary = summary;
    lastAgents = agents;
    $("offline").hidden = true;
    $("panel").hidden = false;
    setEngineState("running");
    renderToday(summary);
    renderAgents();
    renderProviders(summary);
    fitWindow();
  } catch (err) {
    if (!seq.isLatest(token)) return;
    const kind = classifyError(err);
    if (kind === "offline") showOffline("stopped");
    else if (kind === "auth") showOffline("auth", "Orca couldn't sign in to its engine. Quit and reopen Orca.");
    else toast("err", "Couldn't refresh", err.message);
  }
}

function showOffline(state, detail) {
  setEngineState(state);
  $("panel").hidden = true;
  $("offline").hidden = false;
  $("today-spend").textContent = "—"; // never leave stale numbers behind
  $("offline-title").textContent = state === "auth" ? "Orca can't sign in" : "Orca isn't running";
  $("offline-detail").textContent = detail || "It may still be starting. Orca checks again every 15 seconds.";
  announce($("offline-title").textContent);
  fitWindow();
}

// ── actions ──

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
      toast("ok", `${res.name} connected`, "Restart open sessions to use Orca. Your old settings are backed up.");
    }
  } catch (err) {
    toast("err", `Couldn't connect ${row.name}`, err.message, 6000);
  } finally {
    busy.delete(row.id);
    await refresh();
  }
}

async function disconnect(row) {
  const now = performance.now();
  if (confirming?.id !== row.id) {
    confirming = { id: row.id, armedAt: now };
    renderAgents();
    announce(`Press again to disconnect ${row.name}`);
    clearTimeout(confirmTimer);
    confirmTimer = setTimeout(() => {
      confirming = null;
      renderAgents();
    }, CONFIRM_MS);
    return;
  }
  if (now - confirming.armedAt < CONFIRM_GUARD_MS) return; // second click of a double-click
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

// ── daily alert editing ──

function openBudget(open) {
  $("budget-collapse").classList.toggle("open", open);
  $("budget-edit").setAttribute("aria-expanded", String(open));
  if (open) {
    const cents = lastSummary?.budget?.daily_cents;
    $("budget-input").value = cents === null || cents === undefined ? "" : String(cents / 100);
    $("budget-stop").checked = lastSummary?.budget?.mode === "stop";
    setTimeout(() => $("budget-input").focus(), 60);
  }
  setTimeout(fitWindow, 240);
}

$("budget-edit").addEventListener("click", () => openBudget(!$("budget-collapse").classList.contains("open")));
$("budget-form").addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    openBudget(false);
    $("budget-edit").focus();
  }
});
$("budget-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const raw = $("budget-input").value.trim();
  const dollars = Number(raw);
  if (raw === "" || !Number.isFinite(dollars) || dollars < 0) {
    toast("err", "Enter an amount in dollars", "For example 20 for a $20.00 daily budget.");
    return;
  }
  await saveBudget(Math.round(dollars * 100));
});
$("budget-clear").addEventListener("click", () => saveBudget(null));

async function saveBudget(cents) {
  const mode = cents !== null && $("budget-stop").checked ? "stop" : "alert";
  try {
    await engine.saveSettings({ daily_budget_cents: cents, budget_mode: mode });
    openBudget(false);
    const detail =
      cents === null
        ? ""
        : mode === "stop"
          ? "Orca notifies you at 80% and pauses your coding agents at 100%."
          : "Orca notifies you at 80% and 100%. It won't stop your agents.";
    toast("ok", cents === null ? "Daily budget removed" : `Daily budget set to ${money(cents * 10_000)}`, detail);
    await refresh();
  } catch (err) {
    toast("err", "Couldn't save the budget", err.message);
  }
}

$("update-get").addEventListener("click", () => {
  const url = $("update-get").dataset.url;
  if (url) native.openExternal(url);
});

$("gateway-leave").addEventListener("click", async () => {
  try {
    await engine.leaveGateway();
    toast("ok", "Left your team's gateway", "Your agents' original settings are restored.");
  } catch (err) {
    toast("err", "Couldn't leave the gateway", err.message, 6000);
  }
  await refresh();
});

// ── manual setup sheet ──

$("manual-close").addEventListener("click", () => {
  $("manual").hidden = true;
  fitWindow();
});
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
      toast("info", "Copy the selected text", "Your system blocked automatic copying.");
    }
  }),
);

// ── footer and offline ──

$("open-dashboard").addEventListener("click", () => native.openDashboard(engine));
$("open-setup").addEventListener("click", () => native.openSetup(engine));
$("open-setup-cta").addEventListener("click", () => native.openSetup(engine));
$("retry").addEventListener("click", async () => {
  $("retry").textContent = "Checking…";
  $("retry").disabled = true;
  await refresh();
  $("retry").textContent = "Try again";
  $("retry").disabled = false;
});
if (native.available()) {
  for (const id of ["quit", "offline-quit"]) {
    $(id).hidden = false;
    $(id).addEventListener("click", () => native.quit());
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
setInterval(() => {
  if (!document.hidden) refresh();
}, REFRESH_MS);
refresh();
