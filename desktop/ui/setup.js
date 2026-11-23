// First-run setup: pick agents, choose where requests go, set a budget.
import { createEngine, native } from "./api.js";

const AGENT_COLORS = { "claude-code": "#D97757", codex: "#10A37F", cursor: "#334155", aider: "#14B8A6", "gemini-cli": "#4C8DF6" };
const PROVIDER_NAMES = { anthropic: "Anthropic", openai: "OpenAI", google: "Google", orcarouter: "OrcaRouter" };

const engine = createEngine();
const $ = (id) => document.getElementById(id);
let state = { agents: [], providers: [], tokenUrl: "https://www.orcarouter.ai/console/token" };

function initials(name) {
  const w = name.split(/\s+/);
  return w.length > 1 ? (w[0][0] + w[1][0]).toUpperCase() : name.slice(0, 2);
}

function agentItem(a) {
  const auto = a.setup === "auto" && a.installed;
  const li = document.createElement("li");
  li.className = `agent ${auto ? (a.connected ? "on" : "on") : "off"}`;
  const box = document.createElement("input");
  box.type = "checkbox";
  box.id = `agent-${a.id}`;
  box.value = a.id;
  box.checked = auto;
  box.disabled = !auto || a.connected;
  box.addEventListener("change", () => {
    li.classList.toggle("on", box.checked);
    updateButton();
  });
  const ic = document.createElement("span");
  ic.className = "ic";
  ic.style.background = AGENT_COLORS[a.id] || "#94A2B8";
  ic.textContent = initials(a.name);
  ic.setAttribute("aria-hidden", "true");
  const nm = document.createElement("label");
  nm.className = "nm";
  nm.htmlFor = box.id;
  const b = document.createElement("b");
  b.textContent = a.name;
  const small = document.createElement("small");
  small.textContent = a.connected
    ? "Already connected"
    : a.setup === "manual"
      ? "Connect from the menu bar: one paste step"
      : a.setup === "unsupported"
        ? a.note
        : "Orca will update its settings";
  nm.append(b, small);
  const pill = document.createElement("span");
  pill.className = `pill ${a.connected ? "ok" : a.setup === "unsupported" ? "muted" : a.setup === "manual" ? "muted" : ""}`;
  pill.textContent = a.connected ? "Connected" : a.setup === "unsupported" ? "Coming soon" : a.setup === "manual" ? "Manual" : "Found";
  li.append(box, ic, nm, pill);
  return li;
}

function selectedAgents() {
  return [...document.querySelectorAll(".agents input:checked:not(:disabled)")].map((i) => i.value);
}

function route() {
  return document.querySelector('input[name="route"]:checked')?.value;
}

function updateButton() {
  const n = selectedAgents().length;
  $("go").textContent = n === 0 ? "Save" : n === 1 ? "Connect 1 agent" : `Connect ${n} agents`;
}

async function load() {
  try {
    const [agents, summary, hosted] = await Promise.all([engine.agents(), engine.summary(), engine.hosted().catch(() => null)]);
    state.agents = agents.agents;
    state.providers = (summary.providers || []).map((p) => p.provider);
    if (hosted?.token_url) state.tokenUrl = hosted.token_url;
  } catch (err) {
    setStatus(err.message, true);
    return;
  }
  const shown = state.agents.filter((a) => a.installed);
  const missing = state.agents.filter((a) => !a.installed).map((a) => a.name);
  $("agents").replaceChildren(...shown.map(agentItem));
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
    $("providers-ready").hidden = false;
    $("providers-ready").textContent = `Already set up: ${state.providers.map((p) => PROVIDER_NAMES[p] || p).join(", ")}. Adding a key here is optional.`;
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
  return input.value.trim();
}

function invalid(id, message) {
  $(id).classList.add("invalid");
  $(id).focus();
  setStatus(message, true);
  return false;
}

async function saveProviders() {
  const haveAny = state.providers.length > 0;
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
  const dollars = Number($("budget").value);
  if ($("budget").value !== "" && (!Number.isFinite(dollars) || dollars < 0)) {
    invalid("budget", "Enter the daily budget in dollars, for example 20.");
    return;
  }
  $("go").disabled = true;
  $("skip").disabled = true;
  setStatus("Saving…");
  const results = [];
  try {
    if (!(await saveProviders())) return;
    await engine.saveSettings({ daily_budget_cents: $("budget").value === "" ? null : Math.round(dollars * 100) });
    for (const id of selectedAgents()) {
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
  document.querySelector(".sh").hidden = true;
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
  $("done").hidden = false;
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
