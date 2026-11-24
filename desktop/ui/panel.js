// Menu-bar panel: spend today, daily alert, coding agents, provider health,
// models on this computer, the team card, and the sheets that open from them
// (an agent's models, budget, requests and test; settings; the savings card;
// confirmations for orca:// links).
import { createEngine, native, panelEngine, toast } from "./api.js";
import {
  AGENT_COLORS,
  agentLogo,
  budgetView,
  classifyError,
  createSequencer,
  disconnectAllLabel,
  money,
  rescuedLine,
  updateLine,
  missingLine,
  weekLine,
  withRef,
} from "./lib.js";
import {
  OUT_OF_CREDIT,
  PAID_CONFIRM,
  agentBudgetView,
  backupOfferView,
  benchmarkKeyView,
  changedText,
  guessHome,
  linkSheet,
  localDate,
  localView,
  offerAddAction,
  paidModelPrompt,
  paidModelsSwitch,
  panelAgentRows,
  panelProviderRows,
  requestRows,
  routerSettingsInput,
  setupHash,
  shareCardText,
  shareIntentUrl,
  substitutionNote,
  teamGatewayView,
  testResultView,
  todayFreeLine,
  toggleLocal,
  weekSplitLine,
} from "./panel-lib.js";
import { createPicker } from "./panel-picker.js";
import { drawCard } from "./panel-card.js";

const REFRESH_MS = 15_000;
const CONFIRM_MS = 3_000;
const CONFIRM_GUARD_MS = 350; // a double-click must not confirm a disconnect
const OTHER_GLYPH =
  '<svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true"><rect x="1" y="1" width="4" height="4" rx="1"/><rect x="7" y="1" width="4" height="4" rx="1"/><rect x="1" y="7" width="4" height="4" rx="1"/><rect x="7" y="7" width="4" height="4" rx="1"/></svg>';

const engine = createEngine();
const api = panelEngine(engine);
const seq = createSequencer();
const $ = (id) => document.getElementById(id);
const busy = new Set();
const seenRows = new Set();
const lastTests = new Map(); // agent id -> the last Test result
let lastSummary = null;
let lastAgents = null;
let lastLocal = null; // GET /local: runtimes with their models
let confirming = null; // { id, armedAt }
let confirmTimer = null;
let allArmed = false; // "Disconnect all" waiting for its second click
let allTimer = null;
let lastAnnounced = "";
let canInstallUpdates = false; // set once at startup from the native shell
let view = null; // { kind, id, opener, update() }

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
  for (const c of children) if (c !== null && c !== undefined && c !== false) node.append(c);
  return node;
}

const spinner = () => el("span", { class: "spinner", "aria-hidden": "true" });

// `then: "paid"` asks setup to turn on paid models once an OrcaRouter key
// is saved (and not before).
function openSetupAt(step, then = null) {
  native.openSetupAt(engine, step, setupHash(window.location.hash, step, then), then ? { then } : {}).catch(() => {});
}

// An inline "are you sure" with the paid-models wording. Returns the box;
// focus moves to its confirm button.
function confirmBox(text, yesLabel, onYes, onNo) {
  const yes = el("button", { class: "btn btn-primary btn-sm", type: "button", "data-focus": "confirm-yes" }, yesLabel);
  const no = el("button", { class: "btn btn-ghost btn-sm", type: "button" }, "Not now");
  yes.addEventListener("click", async () => {
    yes.disabled = true;
    try {
      await onYes();
    } finally {
      yes.disabled = false;
    }
  });
  no.addEventListener("click", onNo);
  const box = el("div", { class: "confirm-box", role: "group", "aria-label": "Confirm" }, el("p", {}, text), el("div", { class: "actions" }, no, yes));
  setTimeout(() => yes.isConnected && yes.focus(), 0);
  return box;
}

// Re-render `host`'s children, keeping focus on the control with the same
// data-focus key when focus was inside.
function keepFocus(host, render) {
  const key = host.contains(document.activeElement) ? document.activeElement.dataset?.focus : null;
  render();
  if (key) host.querySelector(`[data-focus="${CSS.escape(key)}"]`)?.focus();
}

// ── paid models on OrcaRouter: one switch, in Providers and in Settings ──

let paidConfirmIn = null; // where the "turn on" confirmation is open

async function setPaidModels(on) {
  try {
    await engine.saveSettings({ hosted_models: on ? "all" : "free" });
    if (on) toast("ok", "Paid models are on", "Free models and your own keys still come first, for all agents.");
    else toast("ok", "Paid models are off", "OrcaRouter answers with its free models only.");
    paidConfirmIn = null;
    await refresh();
    return true;
  } catch (err) {
    toast("err", on ? "Couldn't turn on paid models" : "Couldn't turn off paid models", err.message);
    return false;
  }
}

function paidSwitch(where, { withText = false, rerender }) {
  const v = paidModelsSwitch(lastSummary?.hosted);
  const sw = el(
    "button",
    { class: `switch${v.on ? " on" : ""}`, type: "button", role: "switch", "aria-checked": String(v.on), "aria-label": v.label, "data-focus": `paid-${where}`, disabled: !v.enabled },
    el("span", { class: "track", "aria-hidden": "true" }, el("span", { class: "knob" })),
    el("span", { class: "sw-state" }, v.state),
  );
  sw.addEventListener("click", async () => {
    if (v.on) {
      await setPaidModels(false);
      rerender();
    } else {
      paidConfirmIn = paidConfirmIn === where ? null : where;
      rerender();
    }
  });
  const box = el("div", { class: "paid-switch" }, el("div", { class: "sw-row" }, el("span", { class: "sw-label" }, withText ? v.label : "Paid models"), sw));
  if (withText) box.append(el("p", { class: "fine" }, v.text));
  if (paidConfirmIn === where && !v.on) {
    box.append(
      confirmBox(PAID_CONFIRM, "Use paid models", async () => {
        await setPaidModels(true);
        rerender();
      }, () => {
        paidConfirmIn = null;
        rerender();
        document.querySelector(`[data-focus="paid-${where}"]`)?.focus();
      }),
    );
  }
  return box;
}

function openLink(url) {
  if (url) native.openExternal(url).catch(() => {});
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// PUT /settings merges top-level fields; maps (agent_models, agent_budgets,
// dismissed_offers) are replaced whole, so read them first.
async function patchSettings(change) {
  const current = await engine.settings();
  return engine.saveSettings(change(current));
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

  // H0: what the free models answered, and the way to paid ones.
  const free = todayFreeLine(s.today);
  $("free-line").hidden = !free;
  $("free-line").textContent = free;
  const paid = paidModelPrompt(s.hosted);
  $("paid").hidden = !paid;
  if (paid) {
    $("paid-text").textContent = paid.text;
    $("paid").classList.toggle("urgent", paid.urgent);
    $("paid-confirm-text").textContent = paid.confirm;
  } else openPaid(false);

  $("week-line").textContent = weekLine(s);
  const w = s.week;
  $("share-open").hidden = !(w.saved_microcents > 0 || w.failures_avoided > 0 || w.local_requests > 0);
  const split = weekSplitLine(w);
  $("week-split").hidden = !split;
  $("week-split").textContent = split;
  const rescued = rescuedLine(w.failures_avoided || 0);
  $("rescued").hidden = !rescued;
  $("rescued").textContent = rescued;
  $("no-provider").hidden = (s.providers || []).length > 0 || Boolean(s.hosted?.configured) || Boolean(s.gateway);
  const upd = updateLine(s.update, { canInstall: canInstallUpdates });
  $("update").hidden = !upd;
  $("update-text").textContent = upd ? upd.text : "";
  $("update-get").dataset.url = upd ? upd.url : "";
  if (upd && !$("update-get").disabled) $("update-get").textContent = upd.action;
  if (b.tone === "warn" || b.tone === "over") announce(b.caption);
}

function openPaid(open) {
  $("paid-collapse").classList.toggle("open", open);
  $("paid-open").setAttribute("aria-expanded", String(open));
  if (open) setTimeout(() => $("paid-confirm").focus(), 60);
  setTimeout(fitWindow, 240);
}

async function usePaidModels() {
  await engine.saveSettings({ hosted_models: "all" });
  toast("ok", "Paid models are on", "Free models and your own keys still come first, for all agents.");
}

$("paid-open").addEventListener("click", () => openPaid(!$("paid-collapse").classList.contains("open")));
$("paid-cancel").addEventListener("click", () => {
  openPaid(false);
  $("paid-open").focus();
});
$("paid-confirm").addEventListener("click", async () => {
  $("paid-confirm").disabled = true;
  try {
    await usePaidModels();
    openPaid(false);
  } catch (err) {
    toast("err", "Couldn't turn on paid models", err.message);
  } finally {
    $("paid-confirm").disabled = false;
    await refresh();
  }
});

// ── H2: backup offer, H4: out of credit ──

function renderOffers(s) {
  const offer = (s.offers || []).find((o) => o.id === "backup");
  const v = backupOfferView(offer);
  $("offer").hidden = !v;
  if (v) {
    $("offer-lead").textContent = v.lead;
    $("offer-rest").textContent = v.rest;
    $("offer-body").textContent = v.body;
  }
  const broke = Boolean(s.hosted?.configured && s.hosted.out_of_credit);
  $("credit").hidden = !broke;
  $("credit-text").textContent = OUT_OF_CREDIT.text;
  if (broke) announce(OUT_OF_CREDIT.lead);
}

$("offer-dismiss").addEventListener("click", async () => {
  $("offer").hidden = true;
  $("agents-h").focus();
  fitWindow();
  try {
    await patchSettings((cur) => ({ dismissed_offers: { ...(cur.dismissed_offers || {}), backup: localDate() } }));
  } catch (err) {
    toast("err", "Couldn't hide the offer", err.message);
  }
  await refresh();
});
$("offer-add").addEventListener("click", () => {
  const next = offerAddAction(lastSummary?.hosted);
  if (next.kind === "setup") {
    // Paid models come on only after a key is saved, in setup.
    openSetupAt(next.step, next.then);
  } else if (next.kind === "confirm") {
    const host = $("offer-confirm");
    host.replaceChildren(
      confirmBox(PAID_CONFIRM, "Use paid models", async () => {
        if (await setPaidModels(true)) host.replaceChildren();
      }, () => {
        host.replaceChildren();
        $("offer-add").focus();
      }),
    );
    fitWindow();
  } else toast("info", "OrcaRouter is already your backup", "Requests your keys can't take go to it.");
});
$("credit-add").addEventListener("click", () => openLink(withRef(lastSummary?.hosted?.billing_url, "lite-panel")));

// ── agents ──

function actionButton(row) {
  if (!row.action) return null;
  const pending = busy.has(row.id);
  if (row.action === "connect" || row.action === "reconnect") {
    const verb = row.action === "connect" ? "Connect" : "Reconnect";
    return el(
      "button",
      { class: "btn btn-primary btn-sm", type: "button", "data-act": row.action, disabled: pending, "aria-label": `${verb} ${row.name}` },
      pending ? spinner() : null,
      pending ? `${verb}ing` : verb,
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
  const logo = agentLogo(row.id);
  if (logo) {
    const ic = el("span", { class: logo.dark ? "ic logo dark" : "ic logo", "aria-hidden": "true" });
    ic.append(el("img", { src: logo.src, alt: "", draggable: "false" }));
    return ic;
  }
  const ic = el("span", { class: "ic", style: `background:${AGENT_COLORS[row.id] || AGENT_COLORS.other}`, "aria-hidden": "true" });
  if (row.id === "other") ic.innerHTML = OTHER_GLYPH; // constant markup: "everything else"
  else ic.textContent = row.initials;
  return ic;
}

function currentRows() {
  return panelAgentRows(lastAgents?.agents || [], lastSummary?.agents || []);
}

function renderAgents() {
  if (!lastAgents) return;
  const all = currentRows();
  const rows = all.filter((r) => r.state !== "missing");
  const missing = missingLine(all);
  $("agents-missing").textContent = missing;
  $("agents-missing").hidden = !missing;
  const allLabel = disconnectAllLabel(all.map((r) => (r.state === "changed" ? { ...r, state: "connected" } : r)));
  $("disconnect-all").hidden = !allLabel;
  if (allLabel && !allArmed) $("disconnect-all").textContent = allLabel;

  // Rows are keyed by agent id and reused, so a refresh doesn't replay their
  // entrance, and keyboard focus stays on the same row's button.
  const focused = document.activeElement?.closest?.("li[data-id]");
  const focusedId = focused?.dataset.id;
  const focusedOpen = document.activeElement?.classList?.contains("nm-btn");
  const list = $("agents");
  const existing = new Map([...list.children].map((li) => [li.dataset.id, li]));
  const next = rows.map((r) => {
    const li = existing.get(r.id) || el("li", { "data-id": r.id });
    const isNew = !seenRows.has(r.id);
    seenRows.add(r.id);
    li.className = ["row", r.state === "unsupported" ? "dim" : "", r.opens ? "opens" : "", isNew ? "enter" : ""].filter(Boolean).join(" ");
    li.title = r.note || "";
    const badge = r.badge && r.state !== "connected" && r.state !== "changed" ? el("span", { class: `pill ${r.badge.tone}` }, r.badge.text) : null;
    const subClass = r.state === "changed" ? "warn" : r.hint ? "hint" : r.paused ? "warn" : "";
    const name = el("b", {}, r.name);
    const sub = el("small", { class: subClass }, r.subtitle);
    const nm = r.opens
      ? el("button", { class: "nm nm-btn", type: "button", "aria-label": `${r.name}: ${r.subtitle}. Open details` }, name, sub)
      : el("span", { class: "nm" }, name, sub);
    li.replaceChildren(tile(r), nm, el("span", { class: "amt" }, r.today || ""), el("span", { class: "act" }, actionButton(r) || badge));
    return li;
  });
  list.replaceChildren(...next);
  if (focusedId) {
    const li = list.querySelector(`li[data-id="${CSS.escape(focusedId)}"]`);
    (focusedOpen ? li?.querySelector(".nm-btn") : li?.querySelector(".act button"))?.focus();
  }
}

$("agents").addEventListener("click", (e) => {
  if (!lastAgents) return;
  const li = e.target.closest("li[data-id]");
  if (!li) return;
  const row = currentRows().find((r) => r.id === li.dataset.id);
  if (!row) return;
  const btn = e.target.closest("button[data-act]");
  if (btn) {
    if (btn.dataset.act === "connect" || btn.dataset.act === "reconnect") connect(row);
    else disconnect(row);
    return;
  }
  if (row.opens) openAgentSheet(row.id, li.querySelector(".nm-btn"));
});

// ── providers (H4) ──

function renderProviders(s) {
  keepFocus($("providers"), () => renderProviderRows(s));
}

function renderProviderRows(s) {
  const rows = panelProviderRows(s);
  const list = $("providers");
  if (!rows.length) {
    list.replaceChildren(el("li", { class: "row" }, el("span", { class: "nm" }, el("small", {}, "No providers yet")), el("span")));
    return;
  }
  list.replaceChildren(
    ...rows.map((p) => {
      let right;
      if (p.link && !p.status) {
        right = el("button", { class: "btn btn-link btn-sm", type: "button", "data-url": p.link.url, "data-focus": "balance", "aria-label": `${p.link.text} on OrcaRouter (opens in your browser)` }, `${p.link.text} `, el("span", { "aria-hidden": "true" }, "↗"));
      } else right = el("span", { class: `pill ${p.tone}` }, p.status);
      return el(
        "li",
        { class: "row prov", "data-id": p.id },
        el("span", { class: `ic tile ${p.id === "orcarouter" ? "brand" : ""}`, "aria-hidden": "true" }, p.initials || p.name.slice(0, 2).toUpperCase()),
        el("span", { class: "nm" }, el("b", {}, p.name), p.detail ? el("small", {}, p.detail) : null),
        right,
        p.id === "orcarouter" ? el("div", { class: "prov-extra" }, paidSwitch("providers", { rerender: () => renderProviders(lastSummary) })) : null,
      );
    }),
  );
}

$("providers").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-url]");
  if (btn) openLink(btn.dataset.url);
});

// ── on this computer (P2 · D1) ──

function renderLocal(s) {
  const runtimes = lastLocal?.runtimes || s.local?.runtimes || [];
  $("local-block").hidden = runtimes.length === 0;
  if (!runtimes.length) return;
  const v = localView(runtimes);
  $("local-none").hidden = v.anyRunning;
  if (!v.anyRunning) {
    $("local-none").textContent = `${runtimes.map((r) => r.name).join(", ").replace(/, ([^,]*)$/, " and $1")} aren't running. Start one and Orca can answer quick requests on this computer, for free.`;
    $("local-list").replaceChildren();
    return;
  }
  if ($("local-list").contains(document.activeElement) && document.activeElement.type === "checkbox") return; // mid-toggle
  $("local-list").replaceChildren(
    ...v.runtimes.map((rt) =>
      el(
        "div",
        { class: "rt" },
        el(
          "div",
          { class: "row prov" },
          el("span", { class: "ic tile", "aria-hidden": "true" }, rt.initials),
          el("span", { class: "nm" }, el("b", {}, rt.name), el("small", { class: "mono" }, rt.detail)),
          el("span", { class: `pill ${rt.running ? "ok" : "muted"}` }, rt.status),
        ),
        rt.models.length
          ? el(
              "ul",
              { class: "lm", "aria-label": `${rt.name} models` },
              ...rt.models.map((m) =>
                el(
                  "li",
                  {},
                  el(
                    "label",
                    { class: "lm-row" },
                    el("input", { type: "checkbox", "data-model": m.id, checked: m.enabled }),
                    el("span", { class: "nm" }, el("b", { class: "mono" }, m.name), el("small", {}, m.detail)),
                    el("span", { class: "amt" }, "$0"),
                  ),
                ),
              ),
            )
          : null,
      ),
    ),
  );
}

$("local-list").addEventListener("change", async (e) => {
  const box = e.target.closest("input[data-model]");
  if (!box || !lastLocal) return;
  try {
    const cur = await engine.settings();
    const next = toggleLocal(lastLocal.runtimes, cur.local_models, box.dataset.model, box.checked);
    await engine.saveSettings({ local_models: next });
    for (const rt of lastLocal.runtimes) for (const m of rt.models) if (m.id === box.dataset.model) m.enabled = box.checked;
    announce(box.checked ? "Orca may use this model" : "Orca won't use this model");
  } catch (err) {
    box.checked = !box.checked;
    toast("err", "Couldn't change local models", err.message);
  }
});

$("local-refresh").addEventListener("click", async () => {
  const btn = $("local-refresh");
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    lastLocal = await api.refreshLocal();
    if (lastSummary) renderLocal(lastSummary);
    fitWindow();
  } catch (err) {
    toast("err", "Couldn't check this computer", err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Refresh";
  }
});

async function loadLocal(s) {
  const running = (s.local?.runtimes || []).some((r) => r.running);
  if (!running) {
    lastLocal = null;
    return;
  }
  try {
    lastLocal = await api.local();
    if (lastSummary) renderLocal(lastSummary);
    fitWindow();
  } catch {
    /* the summary's counts still show */
  }
}

// ── team (H7, V3) ──

function renderTeam(s) {
  const t = teamGatewayView(s.gateway);
  $("team-title").textContent = t.title;
  $("team-detail").textContent = t.detail;
  $("team-tile").textContent = t.initials || "GW";
  $("team-joined").hidden = !t.joined;
  $("team-join").hidden = t.joined;
  $("team-leave-line").hidden = !t.joined;
}

$("team-join").addEventListener("click", () => openSetupAt("gateway"));

$("gateway-leave").addEventListener("click", async () => {
  try {
    await engine.leaveGateway();
    toast("ok", "Left your team's gateway", "Your agents' original settings are restored.");
  } catch (err) {
    toast("err", "Couldn't leave the gateway", err.message, 6000);
  }
  await refresh();
});

async function busyButton(btn, label, work) {
  const text = btn.textContent;
  btn.disabled = true;
  btn.textContent = label;
  try {
    return await work();
  } finally {
    btn.disabled = false;
    btn.textContent = text;
  }
}

$("report-copy").addEventListener("click", () =>
  busyButton($("report-copy"), "Copying…", async () => {
    try {
      const r = await api.report("markdown", "this");
      if (await copyText(r.content)) toast("ok", "Report copied", "This week's spend by agent and model, as Markdown.");
      else toast("err", "Couldn't copy the report", "Your system blocked copying. Use CSV to save it instead.");
    } catch (err) {
      toast("err", "Couldn't build the report", err.message);
    }
  }),
);

$("report-csv").addEventListener("click", () =>
  busyButton($("report-csv"), "Saving…", async () => {
    try {
      const r = await api.saveReport("this");
      toast("ok", "Report saved", `Saved to ${r.path}.`, 6000);
      announce(`Report saved to ${r.path}`);
    } catch (err) {
      toast("err", "Couldn't save the report", err.message);
    }
  }),
);

$("share-setup").addEventListener("click", () =>
  busyButton($("share-setup"), "Copying…", async () => {
    try {
      const r = await api.shareSetup();
      if (await copyText(r.link)) toast("ok", "Link copied", "Teammates who open it get the same agents and budget. It never carries keys.");
      else toast("info", "Your setup link", r.link, 8000);
    } catch (err) {
      toast("err", "Couldn't make the link", err.message);
    }
  }),
);

// ── views: agent sheet, settings, savings card ──

function showView(kind, title, opener) {
  closeView({ restoreFocus: false });
  view = { kind, opener, update: null };
  $("view-title").textContent = title;
  $("view-body").replaceChildren();
  $("home").hidden = true;
  $("view").hidden = false;
  $("scroll").scrollTop = 0;
  $("view-title").focus();
  return view;
}

function closeView({ restoreFocus = true } = {}) {
  if (!view) return;
  const opener = view.opener;
  view = null;
  $("view").hidden = true;
  $("home").hidden = false;
  $("view-body").replaceChildren();
  fitWindow();
  if (restoreFocus && opener?.isConnected) opener.focus();
  else if (restoreFocus) $("agents-h").focus();
}

$("view-back").addEventListener("click", () => closeView());
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !$("link-modal").hidden) return;
  if (view && !e.defaultPrevented) {
    e.preventDefault();
    closeView();
  }
});

function section(label, ...children) {
  return el("section", { class: "vs" }, label ? el("h3", { class: "label" }, label) : null, ...children);
}

// ── the agent sheet (D2, D3, D4, D5, H3) ──

async function openAgentSheet(id, opener) {
  const row = currentRows().find((r) => r.id === id);
  if (!row) return;
  const v = showView("agent", "Coding agent", opener);
  v.id = id;
  const body = $("view-body");
  const head = el("div", { class: "as-head" });
  const state = el("div", { class: "as-state" });
  const testLine = el("div", { class: "as-test-result", "aria-live": "polite" });
  const testBtn = el("button", { class: "btn btn-ghost btn-sm", type: "button" }, "Test");
  const models = el("div", { class: "as-models" }, el("p", { class: "fine" }, "Loading…"));
  const budget = el("div", { class: "as-budget" });
  const requests = el("div", { class: "as-requests" }, el("p", { class: "fine" }, "Loading…"));
  const disconnectBtn = el("button", { class: "btn btn-ghost btn-sm", type: "button", "data-act": "sheet-disconnect" }, "Disconnect");
  body.append(
    head,
    state,
    section(null, el("div", { class: "as-test" }, el("span", { class: "nm" }, el("b", {}, "Test"), el("small", {}, "Send one tiny request the way the agent does")), testBtn), testLine),
    section("Models", models),
    section("Budget", budget),
    section("Recent requests", requests),
    el("div", { class: "as-foot" }, disconnectBtn, el("span", { class: "fine" }, "Restores its original settings.")),
  );

  const spendOf = () => (lastSummary?.agents || []).find((a) => a.id === id) || { today_microcents: 0, substitutions: [] };
  const rowOf = () => currentRows().find((r) => r.id === id) || row;

  function renderHead() {
    const r = rowOf();
    const s = spendOf();
    const pill =
      r.state === "changed"
        ? el("span", { class: "pill warn" }, "Settings changed")
        : r.paused
          ? el("span", { class: "pill warn" }, "Paused")
          : el("span", { class: "pill ok" }, "Connected");
    head.replaceChildren(tile(r), el("span", { class: "nm" }, el("b", {}, r.name), pill), el("span", { class: "as-today" }, `${money(s.today_microcents)} today`));
  }

  let stateKey = null;
  let subConfirm = false;
  function renderState() {
    const r = rowOf();
    const sub0 = (spendOf().substitutions || [])[0] || null;
    const key = JSON.stringify([r.state, r.name, r.configPath, sub0, lastSummary?.hosted?.configured, lastSummary?.hosted?.models, subConfirm]);
    if (key === stateKey) return; // unchanged: leave focus and inputs alone
    stateKey = key;
    const hadFocus = state.contains(document.activeElement);
    const items = [];
    if (r.state === "changed") {
      items.push(
        el(
          "div",
          { class: "note warn" },
          el("p", {}, changedText(r.name, r.configPath, guessHome((lastAgents?.agents || []).map((a) => a.config_path)))),
          el("div", { class: "actions" }, el("button", { class: "btn btn-primary btn-sm", type: "button", "data-act": "sheet-reconnect" }, `Reconnect ${r.name}`)),
        ),
      );
    }
    const sub = (spendOf().substitutions || [])[0];
    if (sub) {
      const n = substitutionNote(r.name, sub, lastSummary?.hosted);
      const offer = n.action
        ? el(
            "div",
            { class: "offer-row" },
            el("span", { class: "nm" }, el("b", {}, n.offerTitle), el("small", {}, n.offerDetail)),
            el("button", { class: "btn btn-primary btn-sm", type: "button", "data-act": `sub-${n.action}`, "aria-label": n.offerTitle }, "Add"),
          )
        : null;
      const confirm =
        n.action === "paid" && subConfirm
          ? confirmBox(PAID_CONFIRM, "Use paid models", async () => {
              subConfirm = false;
              await setPaidModels(true);
              if (view === v) renderState();
            }, () => {
              subConfirm = false;
              renderState();
              state.querySelector('[data-act="sub-paid"]')?.focus();
            })
          : null;
      items.push(
        el(
          "div",
          { class: "note info" },
          el("p", {}, n.text),
          offer,
          confirm,
          el("button", { class: "btn btn-link btn-sm", type: "button", "data-act": "sub-keep", "data-model": sub.requested }, n.keep),
        ),
      );
    }
    state.replaceChildren(...items);
    // What had focus is gone (the note was kept or resolved): land on the sheet's title.
    if (hadFocus && !state.contains(document.activeElement) && !subConfirm) $("view-title").focus();
    fitWindow();
  }

  function renderTest() {
    const t = testResultView(lastTests.get(id));
    testLine.replaceChildren();
    testLine.hidden = !t;
    if (!t) return;
    testLine.className = `as-test-result note ${t.tone}`;
    if (t.lead) testLine.append(el("b", {}, `${t.lead} `));
    testLine.append(t.text);
  }

  // D3: per-agent daily budget.
  const budgetBar = el("div", { class: "bar", role: "progressbar", "aria-label": `${row.name}'s budget used`, "aria-valuemin": "0", "aria-valuemax": "100" }, el("i"));
  const budgetCaption = el("span", { class: "caption" });
  const budgetBox = el("input", { type: "checkbox", id: "as-budget-on" });
  const budgetInput = el("input", { id: "as-budget-amount", type: "number", min: "0", step: "0.01", inputmode: "decimal", placeholder: "5.00", "aria-label": `Daily budget for ${row.name} in dollars` });
  const budgetStatus = el("p", { class: "fine", "aria-live": "polite" }, "Orca pauses only this agent; the others keep working.");
  budget.append(
    el("div", { class: "as-budget-top" }, budgetCaption),
    budgetBar,
    el(
      "div",
      { class: "check-line budget-line" },
      budgetBox,
      el("label", { for: "as-budget-on" }, `Pause ${row.name} at`),
      el("span", { class: "money-input" }, el("span", { "aria-hidden": "true" }, "$"), budgetInput),
      el("span", { class: "per" }, "a day"),
    ),
    budgetStatus,
  );

  function renderBudget(initial = false) {
    const s = spendOf();
    const cents = s.budget_cents ?? null;
    const b = agentBudgetView(s.today_microcents, cents);
    budgetCaption.textContent = b.hasBudget ? b.caption : `${money(s.today_microcents)} today, no budget`;
    budgetBar.hidden = !b.hasBudget;
    budgetBar.className = `bar ${b.tone === "warn" || b.tone === "over" ? b.tone : ""}`;
    budgetBar.setAttribute("aria-valuenow", String(b.percent));
    budgetBar.firstElementChild.style.width = `${b.percent}%`;
    if (initial || (document.activeElement !== budgetInput && document.activeElement !== budgetBox)) {
      budgetBox.checked = b.hasBudget;
      if (b.hasBudget) budgetInput.value = (cents / 100).toFixed(2);
    }
  }

  async function saveBudget() {
    const on = budgetBox.checked;
    const raw = budgetInput.value.trim();
    const dollars = Number(raw);
    if (on && (raw === "" || !Number.isFinite(dollars) || dollars < 0)) {
      budgetStatus.textContent = "Enter an amount in dollars, like 5 for $5.00 a day.";
      budgetInput.focus();
      return;
    }
    try {
      await patchSettings((cur) => {
        const all = { ...(cur.agent_budgets || {}) };
        if (on) all[id] = Math.round(dollars * 100);
        else delete all[id];
        return { agent_budgets: all };
      });
      budgetStatus.textContent = on ? `Saved. Orca pauses ${row.name} at ${money(Math.round(dollars * 100) * 10_000)} a day.` : "Saved. No budget for this agent.";
      await refresh();
    } catch (err) {
      budgetStatus.textContent = `Couldn't save: ${err.message}`;
    }
  }
  budgetBox.addEventListener("change", () => {
    if (budgetBox.checked && !budgetInput.value) budgetInput.value = "5.00";
    saveBudget();
  });
  budgetInput.addEventListener("change", () => {
    if (budgetInput.value.trim() && !budgetBox.checked) budgetBox.checked = true;
    saveBudget();
  });
  budgetInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      budgetInput.blur();
    }
  });

  // D3: recent requests.
  async function loadRequests() {
    if (requests.contains(document.activeElement)) return;
    try {
      const r = await api.agentRequests(id, 20);
      const rows = requestRows(r.requests).slice(0, 10);
      if (!rows.length) {
        requests.replaceChildren(el("p", { class: "fine" }, `No requests yet. Use ${row.name} and they show here.`));
      } else {
        requests.replaceChildren(
          el(
            "ul",
            { class: "reqs" },
            ...rows.map((q) =>
              el(
                "li",
                { class: q.tag ? `req ${q.tag}` : "req" },
                el("span", { class: "t" }, q.time),
                el("span", { class: "m", title: q.fullModel }, el("span", { class: "mono" }, q.model), q.tag ? el("span", { class: `tag ${q.tag === "rescued" ? "warn" : "err"}` }, q.tag) : null),
                el("span", { class: "k" }, q.tokens),
                el("span", { class: "c" }, q.cost),
                q.note ? el("small", { class: "why" }, q.note) : null,
              ),
            ),
          ),
        );
      }
    } catch (err) {
      requests.replaceChildren(el("p", { class: "fine" }, `Couldn't load requests: ${err.message}`));
    }
    fitWindow();
  }

  // D2: models.
  let settings = null;
  const fallbackBox = el("input", { type: "checkbox", id: "as-fallback" });
  const modelStatus = el("p", { class: "fine", "aria-live": "polite" }, "Applies to this agent only. Other agents keep their own choice.");
  const pickerCtx = () => ({ hostedConfigured: Boolean(lastSummary?.hosted?.configured), hostedModels: lastSummary?.hosted?.models || "free" });
  const saveMap = async (change) => {
    await patchSettings((cur) => {
      const all = { ...(cur.agent_models || {}) };
      const mine = { main: null, background: null, fallback_to_auto: true, ...(all[id] || {}), ...change };
      if (!mine.main && !mine.background && mine.fallback_to_auto) delete all[id];
      else all[id] = mine;
      settings = { ...cur, agent_models: all };
      return { agent_models: all };
    });
    modelStatus.textContent = "Saved. Applies to this agent only.";
  };
  const pickerFor = (label, role, detail) =>
    createPicker({
      label,
      value: settings?.agent_models?.[id]?.[role] ?? null,
      defaultLabel: "What the agent asks for",
      defaultDetail: detail,
      load: () => api.models("", 1000),
      context: pickerCtx,
      onChoose: async (value) => {
        try {
          await saveMap({ [role]: value });
        } catch (err) {
          modelStatus.textContent = `Couldn't save: ${err.message}`;
          throw err;
        }
      },
      onNeedsKey: () => openSetupAt("orcarouter"),
      onNeedsPaid: async () => {
        try {
          await usePaidModels();
          await refresh();
          return true;
        } catch (err) {
          toast("err", "Couldn't turn on paid models", err.message);
          return false;
        }
      },
      onResize: fitWindow,
    });

  async function loadModels() {
    try {
      settings = await engine.settings();
    } catch (err) {
      models.replaceChildren(el("p", { class: "fine" }, `Couldn't load settings: ${err.message}`));
      return;
    }
    const map = settings.agent_models?.[id] || {};
    fallbackBox.checked = map.fallback_to_auto ?? true;
    const main = pickerFor("Main model", "main", `${row.name}'s own model, or auto`);
    const bg = pickerFor("Background tasks (titles, summaries)", "background", "Its small model for quick tasks");
    models.replaceChildren(
      main.root,
      bg.root,
      el("label", { class: "check-line", for: "as-fallback" }, fallbackBox, el("span", {}, "If a model isn't available, use ", el("code", {}, "auto"))),
      modelStatus,
    );
    fitWindow();
  }
  fallbackBox.addEventListener("change", async () => {
    try {
      await saveMap({ fallback_to_auto: fallbackBox.checked });
    } catch (err) {
      fallbackBox.checked = !fallbackBox.checked;
      modelStatus.textContent = `Couldn't save: ${err.message}`;
    }
  });

  // D4: test.
  async function runTest() {
    testBtn.disabled = true;
    testBtn.replaceChildren(spinner(), "Testing");
    await testAgent(id);
    testBtn.disabled = false;
    testBtn.replaceChildren("Test");
    if (view === v) renderTest();
    fitWindow();
  }
  testBtn.addEventListener("click", runTest);

  // Actions inside the sheet.
  let sheetArmed = 0;
  body.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    const r = rowOf();
    if (act === "sheet-reconnect") {
      btn.disabled = true;
      await connect(r);
      if (view === v) {
        renderHead();
        renderState();
        renderTest();
      }
    } else if (act === "sub-setup") {
      openSetupAt("orcarouter");
    } else if (act === "sub-paid") {
      subConfirm = true;
      renderState();
    } else if (act === "sub-keep") {
      const model = btn.dataset.model;
      try {
        await patchSettings((cur) => ({ kept_substitutions: [...new Set([...(cur.kept_substitutions || []), model])] }));
        toast("ok", "Got it", `Orca won't mention ${model} for ${r.name} again.`);
      } catch (err) {
        toast("err", "Couldn't save", err.message);
      }
      await refresh();
      if (view === v) renderState();
    } else if (act === "sheet-disconnect") {
      const now = performance.now();
      if (!sheetArmed) {
        sheetArmed = now;
        btn.className = "btn btn-sm btn-danger confirming";
        btn.textContent = "Confirm?";
        btn.setAttribute("aria-label", `Confirm disconnecting ${r.name}`);
        announce(`Press again to disconnect ${r.name}`);
        setTimeout(() => {
          sheetArmed = 0;
          if (btn.isConnected) {
            btn.className = "btn btn-ghost btn-sm";
            btn.textContent = "Disconnect";
            btn.removeAttribute("aria-label");
          }
        }, CONFIRM_MS);
        return;
      }
      if (now - sheetArmed < CONFIRM_GUARD_MS) return;
      sheetArmed = 0;
      btn.disabled = true;
      btn.textContent = "Restoring";
      try {
        const res = await engine.disconnect(id);
        toast("ok", `${res.name} disconnected`, "Its original settings are restored.");
        closeView({ restoreFocus: false });
        $("agents-h").focus();
      } catch (err) {
        toast("err", `Couldn't disconnect ${r.name}`, err.message, 6000);
        btn.disabled = false;
      }
      await refresh();
    }
  });

  v.update = () => {
    if (!rowOf().opens) {
      closeView({ restoreFocus: false });
      return;
    }
    renderHead();
    renderState();
    renderBudget();
    loadRequests();
  };
  renderHead();
  renderState();
  renderTest();
  renderBudget(true);
  fitWindow();
  await Promise.all([loadModels(), loadRequests()]);
}

async function testAgent(id) {
  try {
    const res = await api.testAgent(id);
    lastTests.set(id, res);
    return res;
  } catch (err) {
    const res = { ok: false, error: `The test couldn't run: ${err.message}` };
    lastTests.set(id, res);
    return res;
  }
}

// ── settings (D7) ──

async function openSettings(opener) {
  const v = showView("settings", "Settings", opener);
  const body = $("view-body");
  const keyBox = el("div", { class: "aa" }, el("p", { class: "fine" }, "Loading…"));
  const retries = el("input", { id: "set-retries", type: "number", min: "0", max: "5", step: "1", inputmode: "numeric", placeholder: "Default" });
  const cooldown = el("input", { id: "set-cooldown", type: "number", min: "0", max: "3600", step: "1", inputmode: "numeric", placeholder: "Default" });
  const routerStatus = el("p", { class: "fine", "aria-live": "polite" }, "Auto moves on to the next model right away; retries apply to models you pin. Takes effect immediately. No restart.");
  const routerSave = el("button", { class: "btn btn-primary btn-sm", type: "submit", disabled: true }, "Save");
  const routerForm = el(
    "form",
    { class: "router-form", novalidate: true },
    el(
      "div",
      { class: "two-fields" },
      el("div", { class: "field" }, el("label", { class: "field-label", for: "set-retries" }, "Retries (pinned models)"), el("span", { class: "unit-input" }, retries)),
      el(
        "div",
        { class: "field" },
        el("label", { class: "field-label", for: "set-cooldown" }, "Rest a failing provider"),
        el("span", { class: "unit-input" }, cooldown, el("span", { "aria-hidden": "true" }, "s")),
      ),
    ),
    el("div", { class: "actions" }, routerSave),
    routerStatus,
  );
  const paidHost = el("div", {});
  const renderPaid = () => keepFocus(paidHost, () => paidHost.replaceChildren(paidSwitch("settings", { withText: true, rerender: renderPaid })));
  renderPaid();
  body.append(
    section("OrcaRouter", paidHost),
    section("Benchmark scores", el("p", { class: "field-label" }, "Artificial Analysis key"), keyBox,
      el("p", { class: "fine" }, "Used by the Quality and Balanced strategies. Free tier is plenty; scores refresh hourly.")),
    section("When a provider fails", routerForm),
  );

  function renderKey(status) {
    const k = benchmarkKeyView(status);
    if (k.mode === "empty") {
      const input = el("input", { id: "aa-key", type: "password", autocomplete: "off", spellcheck: "false", placeholder: "Paste your key", "aria-label": "Artificial Analysis key" });
      const form = el("form", { class: "aa-form", novalidate: true }, input, el("button", { class: "btn btn-primary btn-sm", type: "submit" }, "Save"));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const value = input.value.trim();
        if (!value) {
          input.focus();
          return;
        }
        try {
          renderKey(await api.saveBenchmarkKey(value));
          announce("Key saved");
          (keyBox.querySelector("#aa-clear") || keyBox.querySelector("code"))?.focus();
        } catch (err) {
          toast("err", "Couldn't save the key", err.message);
        }
      });
      keyBox.replaceChildren(form);
      return;
    }
    const pill = el("span", { class: `pill ${k.mode === "env" ? "muted" : "ok"}` }, k.mode === "env" ? "Environment" : "Saved");
    const shown = el("div", { class: "aa-shown" }, el("code", { class: "mono", tabindex: "-1" }, k.hint), pill);
    const actions = k.mode === "saved" ? el("button", { class: "btn btn-link btn-sm", type: "button", id: "aa-clear" }, "Remove") : null;
    keyBox.replaceChildren(shown, el("p", { class: "fine aa-note" }, k.text, " ", actions));
    actions?.addEventListener("click", async () => {
      try {
        renderKey(await api.saveBenchmarkKey(null));
        announce("Key removed");
        keyBox.querySelector("#aa-key")?.focus();
      } catch (err) {
        toast("err", "Couldn't remove the key", err.message);
      }
    });
  }

  routerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (routerSave.disabled) return; // never save blanks over values that didn't load
    const parsed = routerSettingsInput(retries.value, cooldown.value);
    if (parsed.error) {
      routerStatus.textContent = parsed.error.message;
      (parsed.error.field === "retries" ? retries : cooldown).focus();
      return;
    }
    try {
      await engine.saveSettings(parsed.values);
      routerStatus.textContent = "Saved. Takes effect immediately. No restart.";
    } catch (err) {
      routerStatus.textContent = `Couldn't save: ${err.message}`;
    }
  });

  // Loaded separately: one failing must not blank (and then save over) the other.
  const keyLoad = api.benchmarkKey().then(
    (key) => view === v && renderKey(key),
    (err) => view === v && keyBox.replaceChildren(el("p", { class: "fine" }, `Couldn't load the key: ${err.message}`)),
  );
  const settingsLoad = engine.settings().then(
    (s) => {
      if (view !== v) return;
      retries.value = s.router_num_retries ?? "";
      cooldown.value = s.router_cooldown_seconds ?? "";
      routerSave.disabled = false;
    },
    (err) => {
      if (view === v) routerStatus.textContent = `Couldn't load these settings, so they can't be saved now: ${err.message}`;
    },
  );
  await Promise.all([keyLoad, settingsLoad]);
  fitWindow();
}

$("open-settings").addEventListener("click", (e) => openSettings(e.currentTarget));

// ── savings card (V2, H8) ──

async function openShare(opener) {
  const v = showView("share", "Share this week", opener);
  const body = $("view-body");
  const canvas = el("canvas", { class: "card-canvas", role: "img", "aria-label": "Your savings card" });
  const copyBtn = el("button", { class: "btn btn-primary btn-sm", type: "button", id: "card-copy" }, "Copy image");
  const xBtn = el("button", { class: "btn btn-ghost btn-sm", type: "button", id: "card-x" }, "Post on X");
  const liBtn = el("button", { class: "btn btn-ghost btn-sm", type: "button", id: "card-linkedin" }, "LinkedIn");
  body.append(
    el("div", { class: "card-wrap" }, canvas),
    el("div", { class: "actions center" }, copyBtn, xBtn, liBtn),
    el("p", { class: "fine center" }, "Shows totals only: no prompts, models or company names. Made on this computer; nothing is sent until you post it."),
  );
  let card;
  let text;
  try {
    card = await api.shareCard();
    text = shareCardText(card);
    if (view !== v) return;
    canvas.setAttribute("aria-label", text.alt);
    await drawCard(canvas, text);
  } catch (err) {
    body.replaceChildren(el("p", { class: "fine" }, `Couldn't make the card: ${err.message}`));
    return;
  }
  fitWindow();
  copyBtn.addEventListener("click", async () => {
    try {
      await native.copyPng(canvas.toDataURL("image/png"));
      toast("ok", "Image copied", "Paste it into a post. The link to Orca is in the picture.");
    } catch (err) {
      toast("err", "Couldn't copy the image", String(err?.message || err));
    }
  });
  xBtn.addEventListener("click", () => openLink(shareIntentUrl("x", { text: text.post, link: card.link })));
  liBtn.addEventListener("click", () => openLink(shareIntentUrl("linkedin", { text: text.post, link: card.link })));
}

$("share-open").addEventListener("click", (e) => openShare(e.currentTarget));

// ── orca:// links (V3): always a confirmation ──

let pendingSheet = null;
let modalOpener = null;
const waitingSheets = []; // links that arrived while a sheet was open

function showLinkSheet(sheet) {
  if (pendingSheet) {
    if (waitingSheets.length < 3) waitingSheets.push(sheet);
    return;
  }
  pendingSheet = sheet;
  if (!modalOpener) modalOpener = document.activeElement;
  const isJoin = sheet.kind === "join";
  const row = isJoin ? null : currentRows().find((r) => r.id === sheet.agentId);
  const t = $("link-tile");
  t.replaceWith(isJoin ? el("span", { class: "ic tile brand", id: "link-tile", "aria-hidden": "true" }, "GW") : Object.assign(tile(row || { id: sheet.agentId, initials: sheet.name.slice(0, 2) }), { id: "link-tile" }));
  $("link-title").textContent = sheet.title;
  $("link-host").hidden = !isJoin;
  $("link-host").textContent = isJoin ? sheet.host : "";
  $("link-insecure").hidden = !(isJoin && sheet.insecure);
  $("link-insecure-text").hidden = !(isJoin && sheet.insecure);
  $("link-detail").textContent = sheet.detail;
  $("link-join").hidden = !isJoin;
  $("link-key").value = "";
  const ok = $("link-confirm");
  ok.hidden = !isJoin && !sheet.ready;
  ok.disabled = false;
  ok.textContent = sheet.confirm;
  $("link-cancel").textContent = !isJoin && !sheet.ready ? "Close" : "Cancel";
  $("panel").inert = true;
  $("link-modal").hidden = false;
  (isJoin ? $("link-key") : $("link-cancel")).focus();
  fitWindow();
}

function closeLinkSheet() {
  pendingSheet = null;
  if (waitingSheets.length) {
    showLinkSheet(waitingSheets.shift());
    return;
  }
  $("link-modal").hidden = true;
  $("panel").inert = false;
  // Back where the user was; a link that arrived with nothing focused
  // leaves focus at the top of what's showing.
  if (modalOpener?.isConnected && modalOpener !== document.body) modalOpener.focus();
  else $(view ? "view-title" : "today-h").focus();
  modalOpener = null;
  fitWindow();
}

async function handleLink(link) {
  if (!lastAgents) await refresh();
  const sheet = linkSheet(link, lastAgents?.agents || []);
  if (sheet) showLinkSheet(sheet);
}

$("link-cancel").addEventListener("click", closeLinkSheet);
$("link-join").addEventListener("submit", (e) => {
  e.preventDefault();
  $("link-confirm").click();
});
$("link-confirm").addEventListener("click", async () => {
  const sheet = pendingSheet;
  if (!sheet) return;
  if (sheet.kind === "connect") {
    closeLinkSheet();
    const row = currentRows().find((r) => r.id === sheet.agentId);
    if (row) await connect(row);
    return;
  }
  const key = $("link-key").value.trim();
  if (!key) {
    $("link-key").focus();
    $("link-key-help").textContent = "Paste the key your platform team gave you first. Links never carry keys.";
    return;
  }
  $("link-confirm").disabled = true;
  $("link-confirm").textContent = "Joining…";
  try {
    await engine.joinGateway(sheet.url, key);
    closeLinkSheet();
    toast("ok", "Joined your team's gateway", `Your agents now use ${sheet.host}.`);
  } catch (err) {
    $("link-confirm").disabled = false;
    $("link-confirm").textContent = sheet.confirm;
    toast("err", "Couldn't join the gateway", err.message, 6000);
  }
  await refresh();
});
$("link-modal").addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    closeLinkSheet();
    return;
  }
  if (e.key !== "Tab") return;
  const items = [...$("link-modal").querySelectorAll("button, input")].filter((x) => !x.hidden && !x.closest("[hidden]") && !x.disabled);
  const i = items.indexOf(document.activeElement);
  const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i === items.length - 1 ? 0 : i + 1;
  e.preventDefault();
  items[next]?.focus();
});
native.onLink(handleLink);

// ── refresh ──

function fitWindow() {
  // The native panel is sized to its content: no dead space under the list.
  requestAnimationFrame(() => {
    let h = 360;
    if (!$("panel").hidden) {
      h = $("panel").querySelector(".ph").offsetHeight + $("scroll").scrollHeight + $("panel").querySelector(".pf").offsetHeight;
    }
    if (!$("link-modal").hidden) h = Math.max(h, $("link-modal").firstElementChild.offsetHeight + 48);
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
    renderOffers(summary);
    renderAgents();
    renderProviders(summary);
    renderLocal(summary);
    renderTeam(summary);
    view?.update?.();
    fitWindow();
    loadLocal(summary);
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
  const verb = row.state === "changed" ? "reconnected" : "connected";
  try {
    const res = await engine.connect(row.id);
    if (res.manual) {
      $("manual-title").textContent = `Finish in ${res.name}`;
      $("manual-note").textContent = res.note;
      $("manual-url").textContent = res.base_url;
      $("manual-key").textContent = res.api_key;
      $("manual").hidden = false;
      if (view) closeView({ restoreFocus: false });
      // Above the agent list and scrolled into view: with many agents it
      // would otherwise open off screen.
      $("manual").scrollIntoView({ block: "nearest" });
      $("manual").focus({ preventScroll: true });
    } else {
      // D4: test it right away, the way the agent will send requests.
      toast("info", `${res.name} ${verb}`, "Testing it now…", 20_000);
      busy.delete(row.id);
      await refresh();
      const t = testResultView(await testAgent(row.id));
      if (t.tone === "ok") toast("ok", `${res.name} ${verb}`, `${t.lead} ${t.text} Restart open sessions to use Orca.`, 6000);
      else toast("err", `${res.name} ${verb}, but the test failed`, t.text, 8000);
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
    e.stopPropagation();
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

$("update-get").addEventListener("click", async () => {
  const url = $("update-get").dataset.url;
  if (!url) return;
  if (!canInstallUpdates) {
    native.openExternal(url);
    return;
  }
  const btn = $("update-get");
  btn.disabled = true;
  btn.textContent = "Installing…";
  try {
    await native.installUpdate(); // restarts the app when it's done
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Install and restart";
    toast("err", "Couldn't install the update", String(err?.message || err), 8000);
  }
});

// ── disconnect all ──
// Two clicks, like a single agent's Disconnect: restores every agent's own
// settings and revokes their keys (do this before uninstalling Orca).

$("disconnect-all").addEventListener("click", async () => {
  const btn = $("disconnect-all");
  if (!allArmed) {
    allArmed = true;
    btn.classList.add("confirming");
    btn.textContent = "Restore every agent? Click again";
    announce("Press again to disconnect every agent");
    clearTimeout(allTimer);
    allTimer = setTimeout(() => {
      allArmed = false;
      btn.classList.remove("confirming");
      renderAgents();
    }, CONFIRM_MS);
    return;
  }
  clearTimeout(allTimer);
  allArmed = false;
  btn.classList.remove("confirming");
  btn.disabled = true;
  try {
    const res = await engine.disconnectAll();
    const names = res.disconnected.join(", ") || "Nothing was connected";
    if (res.failed.length) toast("err", "Some agents couldn't be restored", res.failed.map((f) => `${f.name}: ${f.error}`).join("; "), 8000);
    else toast("ok", "Every agent disconnected", `Restored: ${names}.`);
  } catch (err) {
    toast("err", "Couldn't disconnect all agents", err.message, 6000);
  } finally {
    btn.disabled = false;
    await refresh();
  }
});

// ── manual setup sheet ──

$("manual-close").addEventListener("click", () => {
  $("manual").hidden = true;
  fitWindow();
});
document.querySelectorAll("[data-copy]").forEach((btn) =>
  btn.addEventListener("click", async () => {
    const text = $(btn.dataset.copy).textContent;
    if (await copyText(text)) {
      btn.textContent = "Copied";
      setTimeout(() => (btn.textContent = "Copy"), 1400);
    } else {
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
  if (!$("panel").hidden) $("today-h").focus();
});
if (native.available()) {
  native
    .canInstallUpdates()
    .then((yes) => {
      canInstallUpdates = Boolean(yes);
      if (lastSummary) renderToday(lastSummary);
    })
    .catch(() => {});
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
