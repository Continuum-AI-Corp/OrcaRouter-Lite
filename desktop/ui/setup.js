// First-run setup: pick agents, choose where requests go, set a daily alert.
// Also reopened later from the menu, so it starts from the current settings.
import { createEngine, native, setupCalls } from "./api.js";
import {
  AGENT_COLORS,
  NO_AGENTS_TEXT,
  agentLogo,
  agentNote,
  agentRows,
  collectProviderKeys,
  keyCheckOutcome,
} from "./lib.js";
import {
  BADGE_MARKDOWN,
  byokProviders,
  createClipboardOffers,
  keySavedText,
  localChoice,
  localRuntime,
  maskOrcaKey,
  requestedStep,
  SETUP_STEP_KEY,
  savedKeyResult,
  setupLinkConfirmation,
  setupRoutes,
  setupWithRef,
  strategyChange,
} from "./setup-lib.js";

const TICK =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12l5 5L20 6"/></svg>';
const HOSTED_ROUTES = new Set(["hosted", "local_hosted"]);

const engine = createEngine();
const calls = setupCalls(engine);
const $ = (id) => document.getElementById(id);
const state = {
  agents: [],
  providers: [], // ids that already have a key
  byok: [], // the engine's provider list, as setup shows it
  names: { orcarouter: "OrcaRouter" },
  keyResults: [],
  tokenUrl: setupWithRef("https://www.orcarouter.ai/console/token"),
  strategy: null,
  initialRoute: "hosted",
  runtime: null,
  hostedSaved: false,
  loaded: false,
};
const offers = createClipboardOffers();

function agentItem(row, agent) {
  const connectable = row.state === "available" && row.setup === "auto";
  const li = document.createElement("li");
  li.className = `agent ${row.state === "connected" ? "is-connected" : connectable ? "on" : "off"}`;

  let control;
  if (row.state === "connected") {
    control = document.createElement("span");
    control.className = "tick";
    control.innerHTML = TICK; // constant markup
  } else {
    control = document.createElement("input");
    control.type = "checkbox";
    control.id = `agent-${row.id}`;
    control.value = row.id;
    control.checked = connectable;
    control.disabled = !connectable;
    control.addEventListener("change", () => {
      li.classList.toggle("on", control.checked);
      updateButton();
    });
  }

  const ic = document.createElement("span");
  ic.className = "ic";
  const logo = agentLogo(row.id);
  if (logo) {
    ic.classList.add("logo");
    if (logo.dark) ic.classList.add("dark");
    const img = document.createElement("img");
    img.src = logo.src;
    img.alt = "";
    img.draggable = false;
    ic.append(img);
  } else {
    ic.style.background = AGENT_COLORS[row.id] || AGENT_COLORS.other;
    ic.textContent = row.initials;
  }
  ic.setAttribute("aria-hidden", "true");

  const nm = document.createElement("label");
  nm.className = "nm";
  if (control.id) nm.htmlFor = control.id;
  const b = document.createElement("b");
  b.textContent = row.name;
  const small = document.createElement("small");
  if (row.state === "connected") small.textContent = "Already connected";
  else if (row.setup === "manual") small.textContent = "Connect from the menu: one paste step";
  else if (row.state === "unsupported") small.textContent = agent.note;
  else {
    const note = agentNote(agent);
    small.textContent = note.text;
    if (note.warn) small.className = "warn-note"; // e.g. Claude Code's billing change
  }
  nm.append(b, small);

  const pill = document.createElement("span");
  const pillFor = {
    connected: ["ok", "Connected"],
    unsupported: ["muted", "Coming soon"],
    available: row.setup === "manual" ? ["muted", "Manual"] : ["", "Found"],
  }[row.state] || ["muted", ""];
  pill.className = `pill ${pillFor[0]}`;
  pill.textContent = pillFor[1];
  li.append(control, ic, nm, pill);
  return li;
}

function agentBoxes() {
  return [...document.querySelectorAll(".agents input[type=checkbox]:not(:disabled)")];
}

function selectedAgents() {
  return agentBoxes().filter((i) => i.checked).map((i) => i.value);
}

function route() {
  return document.querySelector('input[name="route"]:checked')?.value;
}

function updateButton() {
  const n = selectedAgents().length;
  const setUp = state.providers.length > 0;
  $("go").textContent = n === 0 ? (setUp ? "Save changes" : "Save") : n === 1 ? "Connect 1 agent" : `Connect ${n} agents`;
}

// ── step 2: where requests go ──

function showRoutes() {
  const { routes, selected } = setupRoutes({ runtime: state.runtime, providers: state.providers, strategy: state.strategy });
  for (const label of document.querySelectorAll(".choice[data-route]")) label.hidden = !routes.includes(label.dataset.route);
  if (state.runtime) {
    const text = localChoice(state.runtime);
    $("route-local-hosted").textContent = text.title;
    $("route-local-hosted-d").textContent = text.body;
  }
  document.querySelector(`input[name="route"][value="${selected}"]`).checked = true;
  state.initialRoute = selected;
  // Opened from the panel at a step (OrcaRouter's key, or a team gateway).
  // "Local first, OrcaRouter for the rest" already holds the key step.
  let stored = null;
  try {
    stored = localStorage.getItem(SETUP_STEP_KEY);
    localStorage.removeItem(SETUP_STEP_KEY);
  } catch {
    /* storage unavailable: no step */
  }
  const asked = requestedStep(stored, window.location.hash);
  if (asked && routes.includes(asked) && !(asked === "hosted" && selected === "local_hosted")) {
    document.querySelector(`input[name="route"][value="${asked}"]`).checked = true;
    document.querySelector(`.choice[data-route="${asked}"]`)?.scrollIntoView({ block: "center" });
  }
  placeKeyBlock();
}

// The OrcaRouter key step sits under whichever OrcaRouter choice is selected.
function placeKeyBlock() {
  const slot = document.querySelector(`.choice[data-route="${route() === "local_hosted" ? "local_hosted" : "hosted"}"] [data-key-slot]`);
  if (slot && $("orca-key").parentElement !== slot) slot.append($("orca-key"));
}

for (const input of document.querySelectorAll('input[name="route"]')) input.addEventListener("change", placeKeyBlock);

// ── own API keys: a chip per provider, a key row per chosen one ──

function renderProviderChips(pressed) {
  const chips = state.byok.map((p) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.dataset.provider = p.id;
    chip.textContent = p.name;
    if (p.isNew) chip.classList.add("new");
    const added = state.providers.includes(p.id);
    if (added) chip.classList.add("added");
    const extra = [p.isNew ? "new" : "", added ? "key added" : ""].filter(Boolean).join(", ");
    if (extra) {
      const sr = document.createElement("span");
      sr.className = "sr-only";
      sr.textContent = ` (${extra})`;
      chip.append(sr);
    }
    chip.setAttribute("aria-pressed", "false");
    chip.addEventListener("click", () => toggleProvider(p.id, true));
    return chip;
  });
  $("provider-chips").replaceChildren(...chips);
  for (const id of pressed) toggleProvider(id, false);
}

function toggleProvider(id, focus) {
  const chip = document.querySelector(`#provider-chips [data-provider="${id}"]`);
  const existing = document.querySelector(`#key-rows .key-row[data-provider="${id}"]`);
  if (existing) {
    existing.remove();
    chip?.setAttribute("aria-pressed", "false");
    return;
  }
  const p = state.byok.find((x) => x.id === id);
  if (!p) return;
  chip?.setAttribute("aria-pressed", "true");
  const row = document.createElement("span");
  row.className = "key-row";
  row.dataset.provider = id;
  const label = document.createElement("label");
  label.htmlFor = `key-${id}`;
  label.textContent = p.name;
  const input = document.createElement("input");
  input.className = "text";
  input.id = `key-${id}`;
  input.type = "password";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.placeholder = p.placeholder;
  row.append(label, input);
  if (!p.checkable) {
    const note = document.createElement("small");
    note.className = "fine";
    note.textContent = `${p.name} has no key check, so Orca saves it without checking.`;
    row.append(note);
  }
  // Keep rows in the list's order, whatever order they were picked in.
  const order = state.byok.map((x) => x.id);
  const after = [...$("key-rows").children].find((r) => order.indexOf(r.dataset.provider) > order.indexOf(id));
  $("key-rows").insertBefore(row, after || null);
  if (focus) input.focus();
}

function keyRows() {
  return [...document.querySelectorAll("#key-rows .key-row")].map((row) => {
    const p = state.byok.find((x) => x.id === row.dataset.provider);
    return { provider: p.id, name: p.name, checkable: p.checkable, key: row.querySelector("input").value, input: row.querySelector("input") };
  });
}

// ── load ──

async function load() {
  try {
    const [agents, summary, settings, hosted, supported, local, routing] = await Promise.all([
      engine.agents(),
      engine.summary(),
      engine.settings(),
      engine.hosted().catch(() => null),
      calls.supportedProviders().catch(() => null),
      calls.localRuntimes().catch(() => null),
      calls.routing().catch(() => null),
    ]);
    state.agents = agents.agents;
    if (hosted?.token_url) state.tokenUrl = setupWithRef(hosted.token_url);
    state.byok = byokProviders(supported);
    for (const p of state.byok) state.names[p.id] = p.name;
    // Providers with a key; the summary can also list "unknown" from old requests.
    state.providers = (summary.providers || []).map((p) => p.provider).filter((id) => !state.byok.length || id in state.names);
    state.runtime = localRuntime(local);
    state.strategy = routing?.strategy || null;
    // Start from what's saved: never silently reset someone's alert.
    const cents = settings.daily_budget_cents;
    $("budget").value = cents === null || cents === undefined ? "" : String(cents / 100);
    if (cents === null || cents === undefined) $("budget").placeholder = state.providers.length ? "No budget" : "20";
    $("budget-stop").checked = settings.budget_mode === "stop";
    $("start-at-login").checked = settings.start_at_login !== false;
    if (!state.providers.length && (cents === null || cents === undefined)) $("budget").value = "20";
  } catch (err) {
    setStatus(err.message, true);
    return;
  }

  const rows = agentRows(state.agents, []);
  const byId = Object.fromEntries(state.agents.map((a) => [a.id, a]));
  const shown = rows.filter((r) => r.state !== "missing");
  const missing = rows.filter((r) => r.state === "missing").map((r) => r.name);
  $("agents").replaceChildren(...shown.map((r) => agentItem(r, byId[r.id])));
  if (!shown.length) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = NO_AGENTS_TEXT;
    $("agents").append(li);
  }
  if (missing.length) {
    const li = document.createElement("li");
    li.className = "hint";
    li.textContent = `Not found on this computer: ${missing.join(", ")}.`;
    $("agents").append(li);
  }

  if (state.providers.length) {
    $("setup-title").textContent = "You're already set up";
    $("setup-lede").textContent = "Change anything below. Leave a field empty to keep what you have.";
    $("providers-ready").hidden = false;
    $("providers-ready").textContent = `Already added: ${state.providers.map((p) => state.names[p] || p).join(", ")}. Adding a key here is optional.`;
  }
  if (!state.byok.length) {
    $("byok-fine").textContent = "Couldn't load the provider list. Close setup and open it again.";
  }
  renderProviderChips(state.providers.length ? [] : ["anthropic", "openai"].filter((id) => state.byok.some((p) => p.id === id)));
  showRoutes();
  updateButton();
  state.loaded = true;
  native.onLink(showLinkSheet);
}

function setStatus(text, isError = false) {
  $("status").textContent = text;
  $("status").className = `status ${isError ? "err" : ""}`;
}

function field(id) {
  const input = $(id);
  input.classList.remove("invalid");
  input.removeAttribute("aria-invalid");
  return input.value.trim();
}

function invalid(id, message) {
  return invalidEl($(id), message);
}

function invalidEl(input, message) {
  input.classList.add("invalid");
  input.setAttribute("aria-invalid", "true");
  input.focus();
  setStatus(message, true);
  return false;
}

// Check a key with its provider (when it has a check), then save it.
// False stops setup.
async function checkAndSave(provider, key, input, checkable = true) {
  const name = state.names[provider] || provider;
  let result = null;
  if (checkable) {
    setStatus(`Checking your ${name} key…`);
    try {
      result = await engine.checkProviderKey(provider, key);
    } catch {
      result = null; // an engine that can't check still saves the key
    }
  } else setStatus(`Saving your ${name} key…`);
  const outcome = keyCheckOutcome(result);
  if (!outcome.save) return invalidEl(input, outcome.warn);
  await engine.setProviderKey(provider, key);
  offers.seen(key);
  state.keyResults.push(savedKeyResult(name, checkable ? result || { status: "unreachable", detail: `Couldn't check the ${name} key; it's saved anyway.` } : null));
  return true;
}

async function saveProviders() {
  const haveAny = state.providers.length > 0;
  const r = route();
  if (r === "company") {
    const url = field("gateway-url");
    const key = field("gateway-key");
    if (!url) return invalid("gateway-url", "Enter the gateway address your platform team gave you.");
    if (!key) return invalid("gateway-key", "Paste the key your platform team gave you.");
    setStatus("Checking the gateway…");
    try {
      await engine.joinGateway(url, key);
    } catch (err) {
      return invalid("gateway-url", err.message);
    }
    state.joinedGateway = true;
    return true;
  }
  if (r === "local_only") return true;
  if (HOSTED_ROUTES.has(r)) {
    if (state.hostedSaved) return true;
    const key = field("hosted-key");
    const hasHosted = state.providers.includes("orcarouter");
    if (!key) {
      if (r === "local_hosted") return hasHosted ? true : invalid("hosted-key", "Get your OrcaRouter key, or choose Only this computer.");
      return haveAny ? true : invalid("hosted-key", "Get your OrcaRouter key, or choose your own API keys.");
    }
    if (!key.startsWith("sk-orca-")) return invalid("hosted-key", "OrcaRouter keys start with sk-orca-.");
    return checkAndSave("orcarouter", key, $("hosted-key"));
  }
  const rows = keyRows();
  for (const row of rows) {
    row.input.classList.remove("invalid");
    row.input.removeAttribute("aria-invalid");
  }
  const { keys, error } = collectProviderKeys(rows);
  if (error) return invalidEl(rows[error.index].input, error.message);
  if (!keys.length && !haveAny) {
    if (rows.length) return invalidEl(rows[0].input, "Add at least one provider key.");
    $("provider-chips").querySelector("button")?.focus();
    setStatus("Choose a provider and add its key.", true);
    return false;
  }
  for (const k of keys) {
    if (!(await checkAndSave(k.provider, k.key, rows[k.index].input, rows[k.index].checkable))) return false;
  }
  return true;
}

// Local choices turn on the "local first" strategy; leaving them turns it off.
async function saveStrategy(results) {
  const r = route();
  const next = strategyChange(state.initialRoute, r, state.strategy);
  if (next) {
    await calls.setStrategy(next);
    state.strategy = next;
  }
  if (r === "local_hosted") results.push({ name: "Local models", ok: true, text: `${state.runtime.name} first, then OrcaRouter` });
  if (r === "local_only") results.push({ name: "Local models", ok: true, text: `Only ${state.runtime.name} on this computer` });
}

$("get-key").addEventListener("click", () => native.openExternal(state.tokenUrl));

// ── H1: an OrcaRouter key on the clipboard, offered when the window regains focus ──

let offered = null;

async function onFocus() {
  if (!state.loaded || offered || state.hostedSaved || !$("done").hidden || !HOSTED_ROUTES.has(route())) return;
  let text = null;
  try {
    text = await native.clipboardOrcaKey();
  } catch {
    return;
  }
  const key = offers.onFocus(text);
  if (!key || state.hostedSaved || !HOSTED_ROUTES.has(route())) return;
  offered = key;
  $("clip-offer-key").textContent = maskOrcaKey(key);
  $("clip-offer").classList.remove("err");
  $("clip-offer-err").hidden = true;
  $("clip-offer-text").hidden = false;
  $("clip-offer").querySelector(".offer-actions").hidden = false;
  $("clip-no").disabled = false;
  $("clip-use").disabled = false;
  $("clip-offer").hidden = false;
  $("key-live").textContent = `OrcaRouter key found on your clipboard (${maskOrcaKey(key)}). Use it?`;
}

window.addEventListener("focus", onFocus);

$("clip-no").addEventListener("click", () => {
  // Declined: the clipboard stays as it is and this key isn't offered again.
  offered = null;
  $("clip-offer").hidden = true;
  $("key-live").textContent = "";
  $("get-key").focus();
});

$("clip-use").addEventListener("click", async () => {
  const key = offered;
  if (!key) return;
  $("clip-no").disabled = true;
  $("clip-use").disabled = true;
  setStatus("Checking your OrcaRouter key…");
  let result = null;
  try {
    result = await engine.checkProviderKey("orcarouter", key);
  } catch {
    result = null;
  }
  const outcome = keyCheckOutcome(result);
  if (!outcome.save) {
    offered = null;
    $("clip-offer").classList.add("err");
    $("clip-offer-text").hidden = true;
    $("clip-offer-err").textContent = outcome.warn;
    $("clip-offer-err").hidden = false;
    $("clip-offer").querySelector(".offer-actions").hidden = true;
    setStatus(outcome.warn, true);
    $("key-live").textContent = outcome.warn;
    $("hosted-key").focus();
    return;
  }
  try {
    await engine.setProviderKey("orcarouter", key);
  } catch (err) {
    offered = null;
    $("clip-offer").hidden = true;
    setStatus(err.message, true);
    return;
  }
  const cleared = (await native.clearClipboard(key).catch(() => false)) === true;
  offered = null;
  state.hostedSaved = true;
  if (!state.providers.includes("orcarouter")) state.providers.push("orcarouter");
  state.keyResults.push(savedKeyResult("OrcaRouter", result));
  $("clip-offer").hidden = true;
  $("get-key").parentElement.hidden = true;
  $("hosted-key").hidden = true;
  const checked = result?.status === "valid";
  $("key-saved").querySelector("b").textContent = checked ? "Key works." : "Key saved.";
  $("key-saved-text").textContent = keySavedText({ checked, warn: outcome.warn, cleared });
  $("key-saved").hidden = false;
  $("key-live").textContent = $("key-saved").textContent;
  setStatus("");
  updateButton();
  $("go").focus();
});

// ── V3: orca://setup links fill in the form; only the user's click acts ──

let lastFocus = null;

function showLinkSheet(link) {
  const c = setupLinkConfirmation(link, state.agents);
  if (!c) return;
  state.link = c;
  $("link-text").textContent = c.text;
  $("link-skipped").hidden = c.skipped.length === 0;
  $("link-skipped").textContent = c.skipped.length ? `Orca can't connect these here: ${c.skipped.join(", ")}.` : "";
  lastFocus = document.activeElement;
  $("setup-form").inert = true;
  $("setup-header").inert = true;
  $("link-sheet").hidden = false;
  $("link-continue").focus();
}

function closeLinkSheet() {
  $("link-sheet").hidden = true;
  $("setup-form").inert = false;
  $("setup-header").inert = false;
  state.link = null;
}

$("link-cancel").addEventListener("click", () => {
  closeLinkSheet();
  lastFocus?.focus?.();
});

$("link-continue").addEventListener("click", () => {
  const c = state.link;
  closeLinkSheet();
  if (!c) return;
  for (const box of agentBoxes()) {
    box.checked = c.agents.includes(box.value);
    box.closest(".agent")?.classList.toggle("on", box.checked);
  }
  if (c.budgetCents !== null) $("budget").value = String(c.budgetCents / 100);
  updateButton();
  setStatus("Filled in from the link. Check it, then click below.");
  $("go").focus();
});

$("link-sheet").addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    e.preventDefault();
    $("link-cancel").click();
  } else if (e.key === "Tab") {
    // Keep focus on the two buttons while the sheet is open.
    const first = $("link-cancel");
    const last = $("link-continue");
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
});

// ── save ──

$("setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const raw = $("budget").value.trim();
  const dollars = Number(raw);
  if (raw !== "" && (!Number.isFinite(dollars) || dollars < 0)) {
    invalid("budget", "Enter the daily budget in dollars, for example 20, or leave it empty.");
    return;
  }
  $("go").disabled = true;
  $("skip").disabled = true;
  setStatus("Saving…");
  const results = [];
  state.keyResults = state.keyResults.filter((r) => r.name === "OrcaRouter key" && state.hostedSaved);
  try {
    if (!(await saveProviders())) return;
    await saveStrategy(results);
    await engine.saveSettings({
      daily_budget_cents: raw === "" ? null : Math.round(dollars * 100),
      budget_mode: raw !== "" && $("budget-stop").checked ? "stop" : "alert",
      start_at_login: $("start-at-login").checked,
    });
    // The app makes the OS login item match the saved setting.
    if (native.available()) await native.invoke("apply_start_at_login").catch(() => {});
    // Joining a gateway already connected every agent it could.
    for (const id of state.joinedGateway ? [] : selectedAgents()) {
      const name = state.agents.find((a) => a.id === id)?.name || id;
      setStatus(`Connecting ${name}…`);
      try {
        await engine.connect(id);
        results.push({ name, ok: true, text: "Connected" });
      } catch (err) {
        results.push({ name, ok: false, text: err.message });
      }
    }
    await native.finishSetup().catch(() => {});
    if (state.joinedGateway) results.push({ name: "Team gateway", ok: true, text: "Agents connected" });
    showDone([...results, ...state.keyResults]);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    $("go").disabled = false;
    $("skip").disabled = false;
  }
});

function showDone(results) {
  $("setup-form").hidden = true;
  $("setup-header").hidden = true;
  $("results").replaceChildren(
    ...results.map((r) => {
      const li = document.createElement("li");
      li.className = r.ok ? "" : "bad";
      const b = document.createElement("b");
      b.textContent = r.name;
      const s = document.createElement("span");
      s.textContent = r.text;
      li.append(b, s);
      return li;
    }),
  );
  $("results").hidden = results.length === 0;
  $("badge-md").textContent = BADGE_MARKDOWN;
  $("done").hidden = false;
  $("close").focus();
}

// ── V6: the README badge ──

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Older webviews: copy the selected text instead.
    const range = document.createRange();
    range.selectNodeContents($("badge-md"));
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    const ok = document.execCommand("copy");
    sel.removeAllRanges();
    return ok;
  }
}

let copiedTimer = null;
$("badge-copy").addEventListener("click", async () => {
  const ok = await copyText(BADGE_MARKDOWN);
  $("badge-copy").textContent = ok ? "Copied" : "Select and copy";
  $("badge-live").textContent = ok ? "Badge Markdown copied." : "Couldn't copy. Select the text and copy it.";
  clearTimeout(copiedTimer);
  copiedTimer = setTimeout(() => {
    $("badge-copy").textContent = "Copy";
  }, 2000);
});

function close() {
  if (native.available()) native.invoke("close_setup");
  else window.location.href = `panel.html${window.location.hash}`;
}

$("skip").addEventListener("click", async () => {
  await native.finishSetup().catch(() => {});
  close();
});
$("close").addEventListener("click", close);

load();
