// First-run setup: pick agents, choose where requests go, set a daily alert.
// Also reopened later from the menu, so it starts from the current settings.
import { createEngine, native } from "./api.js";
import { AGENT_COLORS, agentNote, agentRows } from "./lib.js";

const PROVIDER_NAMES = { anthropic: "Anthropic", openai: "OpenAI", google: "Google", orcarouter: "OrcaRouter" };
const TICK =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12l5 5L20 6"/></svg>';

const engine = createEngine();
const $ = (id) => document.getElementById(id);
const state = { agents: [], providers: [], tokenUrl: "https://www.orcarouter.ai/console/token" };

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
  ic.style.background = AGENT_COLORS[row.id] || AGENT_COLORS.other;
  ic.textContent = row.initials;
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

function selectedAgents() {
  return [...document.querySelectorAll(".agents input[type=checkbox]:checked:not(:disabled)")].map((i) => i.value);
}

function route() {
  return document.querySelector('input[name="route"]:checked')?.value;
}

function updateButton() {
  const n = selectedAgents().length;
  const setUp = state.providers.length > 0;
  $("go").textContent = n === 0 ? (setUp ? "Save changes" : "Save") : n === 1 ? "Connect 1 agent" : `Connect ${n} agents`;
}

async function load() {
  try {
    const [agents, summary, settings, hosted] = await Promise.all([
      engine.agents(),
      engine.summary(),
      engine.settings(),
      engine.hosted().catch(() => null),
    ]);
    state.agents = agents.agents;
    state.providers = (summary.providers || []).map((p) => p.provider);
    if (hosted?.token_url) state.tokenUrl = hosted.token_url;
    // Start from what's saved: never silently reset someone's alert.
    const cents = settings.daily_budget_cents;
    $("budget").value = cents === null || cents === undefined ? "" : String(cents / 100);
    if (cents === null || cents === undefined) $("budget").placeholder = state.providers.length ? "No budget" : "20";
    $("budget-stop").checked = settings.budget_mode === "stop";
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
    li.textContent = "No coding agents found yet. Install Claude Code or Aider, then reopen setup.";
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
    $("providers-ready").textContent = `Already added: ${state.providers.map((p) => PROVIDER_NAMES[p] || p).join(", ")}. Adding a key here is optional.`;
    if (!state.providers.includes("orcarouter")) document.querySelector('input[name="route"][value="byok"]').checked = true;
  }
  updateButton();
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
  $(id).classList.add("invalid");
  $(id).setAttribute("aria-invalid", "true");
  $(id).focus();
  setStatus(message, true);
  return false;
}

async function saveProviders() {
  const haveAny = state.providers.length > 0;
  if (route() === "company") {
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
  if (route() === "hosted") {
    const key = field("hosted-key");
    if (!key) return haveAny ? true : invalid("hosted-key", "Paste your OrcaRouter key, or choose your own API keys.");
    if (!key.startsWith("sk-orca-")) return invalid("hosted-key", "OrcaRouter keys start with sk-orca-.");
    await engine.setProviderKey("orcarouter", key);
    return true;
  }
  const anthropic = field("key-anthropic");
  const openai = field("key-openai");
  if (!anthropic && !openai && !haveAny) return invalid("key-anthropic", "Add at least one provider key.");
  if (anthropic) await engine.setProviderKey("anthropic", anthropic);
  if (openai) await engine.setProviderKey("openai", openai);
  return true;
}

$("get-key").addEventListener("click", () => native.openExternal(state.tokenUrl));

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
  try {
    if (!(await saveProviders())) return;
    await engine.saveSettings({
      daily_budget_cents: raw === "" ? null : Math.round(dollars * 100),
      budget_mode: raw !== "" && $("budget-stop").checked ? "stop" : "alert",
    });
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
    showDone(results);
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
  $("done").hidden = false;
  $("close").focus();
}

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
