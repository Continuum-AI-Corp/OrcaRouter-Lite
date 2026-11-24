// Unit tests for the setup window's view logic (desktop/ui/setup-lib.js).
// Run: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BADGE_MARKDOWN,
  byokProviders,
  createClipboardOffers,
  isOrcaKey,
  localChoice,
  localRuntime,
  requestedStep,
  maskOrcaKey,
  savedKeyResult,
  setupLinkConfirmation,
  setupRoutes,
  setupWithRef,
  strategyChange,
} from "../ui/setup-lib.js";

// ── H8: every outgoing link carries where it came from ──

test("setupWithRef tags a link with the setup source by default", () => {
  assert.equal(setupWithRef("https://www.orcarouter.ai/console/token"), "https://www.orcarouter.ai/console/token?ref=lite-setup");
});

test("setupWithRef keeps other parameters and replaces an earlier ref", () => {
  assert.equal(
    setupWithRef("https://www.orcarouter.ai/console/token?next=%2Fkeys&ref=lite-panel", "lite-badge"),
    "https://www.orcarouter.ai/console/token?next=%2Fkeys&ref=lite-badge",
  );
  assert.equal(
    setupWithRef("https://continuum-ai-corp.github.io/OrcaRouter-Lite/", "lite-badge"),
    "https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-badge",
  );
});

test("setupWithRef only knows the fixed source names and leaves no link alone", () => {
  assert.throws(() => setupWithRef("https://example.com/", "user-42"));
  assert.equal(setupWithRef("", "lite-setup"), null);
  assert.equal(setupWithRef(null), null);
  // Only web links get a ref; anything else is returned as it was.
  assert.equal(setupWithRef("orca://setup?agents=codex"), "orca://setup?agents=codex");
});

test("the README badge links to the landing page tagged as the badge", () => {
  assert.equal(
    BADGE_MARKDOWN,
    "[![budgeted with OrcaRouter Lite](https://img.shields.io/badge/budgeted%20with-OrcaRouter%20Lite-2D7FF9)]" +
      "(https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-badge)",
  );
});

// ── H1: an OrcaRouter key on the clipboard ──

const KEY = "sk-orca-AbCdEfGh12345678_-7f3a";

test("isOrcaKey accepts only something shaped exactly like an OrcaRouter key", () => {
  assert.equal(isOrcaKey(KEY), true);
  assert.equal(isOrcaKey(` ${KEY}\n`), true);
  for (const text of [null, "", "sk-orca-short", "sk-ant-AbCdEfGh12345678", `${KEY} and more`, "hello", `x${KEY}`])
    assert.equal(isOrcaKey(text), false, String(text));
});

test("maskOrcaKey shows only the prefix and the last four characters", () => {
  assert.equal(maskOrcaKey(KEY), "sk-orca-…7f3a");
});

test("the clipboard offer offers each key once and ignores anything else", () => {
  const offers = createClipboardOffers();
  assert.equal(offers.onFocus(null), null);
  assert.equal(offers.onFocus("some text I copied"), null);
  assert.equal(offers.onFocus(KEY), KEY);
  assert.equal(offers.onFocus(KEY), null, "declined or used: never offered again");
  assert.equal(offers.onFocus(` ${KEY} `), null, "the same key with spaces is the same key");
  const other = "sk-orca-ZzYyXxWw98765432abcd";
  assert.equal(offers.onFocus(other), other, "a different key is a new offer");
});

test("a key the user pasted themselves is not offered back to them", () => {
  const offers = createClipboardOffers();
  offers.seen(KEY);
  assert.equal(offers.onFocus(KEY), null);
});

// ── P1: one provider list, from the engine ──

const SUPPORTED = {
  providers: [
    { id: "orcarouter", name: "OrcaRouter", key_hint: "sk-orca-…", env_var: "ORCAROUTER_API_KEY", docs_url: "x", checkable: true, new: false, hosted: true },
    { id: "anthropic", name: "Anthropic", key_hint: "sk-ant-…", env_var: "ANTHROPIC_API_KEY", docs_url: "x", checkable: true, new: false },
    { id: "mistral", name: "Mistral", key_hint: "", env_var: "MISTRAL_API_KEY", docs_url: "x", checkable: true, new: false },
    { id: "moonshot", name: "Moonshot (Kimi)", key_hint: "sk-…", env_var: "MOONSHOT_API_KEY", docs_url: "x", checkable: true, new: true },
    { id: "minimax", name: "MiniMax", key_hint: "", env_var: "MINIMAX_API_KEY", docs_url: "x", checkable: false, new: true },
  ],
};

test("byokProviders keeps the engine's order, leaves out the hosted gateway and marks new ones", () => {
  const rows = byokProviders(SUPPORTED);
  assert.deepEqual(rows.map((r) => r.id), ["anthropic", "mistral", "moonshot", "minimax"]);
  assert.deepEqual(rows[0], { id: "anthropic", name: "Anthropic", placeholder: "Anthropic key (sk-ant-…)", isNew: false, checkable: true });
  assert.equal(rows[1].placeholder, "Mistral key", "no hint: just the name");
  assert.equal(rows[2].isNew, true);
  assert.equal(rows[3].checkable, false);
  assert.deepEqual(byokProviders(null), []);
});

test("savedKeyResult says whether the provider checked the key", () => {
  assert.deepEqual(savedKeyResult("Anthropic", { status: "valid", detail: "Anthropic accepted the key." }), {
    name: "Anthropic key", ok: true, text: "Checked and saved",
  });
  assert.deepEqual(savedKeyResult("MiniMax", null), { name: "MiniMax key", ok: true, text: "Saved without checking" });
  assert.deepEqual(savedKeyResult("MiniMax", { status: "unchecked", detail: "…" }), {
    name: "MiniMax key", ok: true, text: "Saved without checking",
  });
  assert.deepEqual(savedKeyResult("Groq", { status: "unreachable", detail: "Couldn't reach Groq to check the key; it's saved anyway." }), {
    name: "Groq key", ok: false, text: "Couldn't reach Groq to check the key; it's saved anyway.",
  });
});

// ── H6 + P2: local models ──

const OLLAMA = { id: "ollama", name: "Ollama", url: "127.0.0.1:11434", running: true, models: [{ id: "ollama/qwen3-coder:30b" }] };
const LMSTUDIO = { id: "lmstudio", name: "LM Studio", url: "127.0.0.1:1234", running: true, models: [{ id: "lmstudio/x" }] };
const OFF = { id: "lmstudio", name: "LM Studio", url: "127.0.0.1:1234", running: false, models: [] };

test("localRuntime is the first runtime that is running with a model", () => {
  assert.equal(localRuntime(null), null);
  assert.equal(localRuntime({ runtimes: [] }), null);
  assert.equal(localRuntime({ runtimes: [OFF] }), null);
  assert.equal(localRuntime({ runtimes: [{ ...OLLAMA, models: [] }] }), null, "running but empty can't answer anything");
  assert.deepEqual(localRuntime({ runtimes: [OFF, OLLAMA, LMSTUDIO] }), { id: "ollama", name: "Ollama" });
  assert.deepEqual(localRuntime({ runtimes: [LMSTUDIO] }), { id: "lmstudio", name: "LM Studio" });
});

test("localChoice names the runtime that was found", () => {
  assert.deepEqual(localChoice({ id: "lmstudio", name: "LM Studio" }), {
    title: "LM Studio first, OrcaRouter for the rest",
    body: "Quick requests stay on this computer. Harder ones go to OrcaRouter's free models first, paid ones only when needed.",
  });
});

test("setupRoutes offers the local choices only when a runtime was found", () => {
  assert.deepEqual(setupRoutes({ runtime: null, providers: [] }), {
    routes: ["hosted", "byok", "company"], selected: "hosted",
  });
  assert.deepEqual(setupRoutes({ runtime: { id: "ollama", name: "Ollama" }, providers: [] }), {
    routes: ["local_hosted", "local_only", "hosted", "byok", "company"], selected: "local_hosted",
  });
});

test("setupRoutes starts a returning user from what they have", () => {
  const ollama = { id: "ollama", name: "Ollama" };
  assert.equal(setupRoutes({ runtime: null, providers: ["openai"] }).selected, "byok");
  assert.equal(setupRoutes({ runtime: null, providers: ["orcarouter", "openai"] }).selected, "hosted");
  assert.equal(setupRoutes({ runtime: ollama, providers: ["orcarouter"], strategy: "local_first" }).selected, "local_hosted");
  assert.equal(setupRoutes({ runtime: ollama, providers: [], strategy: "local_first" }).selected, "local_only");
  assert.equal(setupRoutes({ runtime: ollama, providers: ["orcarouter"], strategy: "balanced" }).selected, "hosted");
  assert.equal(setupRoutes({ runtime: ollama, providers: ["openai"], strategy: "local_first" }).selected, "byok");
});

test("strategyChange turns local first on for the local choices and off only when the user moves away", () => {
  assert.equal(strategyChange("hosted", "local_hosted", "balanced"), "local_first");
  assert.equal(strategyChange("hosted", "local_only", "cheapest"), "local_first");
  assert.equal(strategyChange("local_hosted", "local_hosted", "local_first"), null, "already on");
  assert.equal(strategyChange("local_hosted", "hosted", "local_first"), "balanced");
  assert.equal(strategyChange("byok", "byok", "local_first"), null, "reopening setup keeps what was chosen");
  assert.equal(strategyChange("local_hosted", "byok", "quality"), null, "only undoes local first");
});

// ── V3: orca://setup links ──

const AGENTS = [
  { id: "claude-code", name: "Claude Code", installed: true, connected: false, setup: "auto" },
  { id: "codex", name: "Codex", installed: true, connected: false, setup: "auto" },
  { id: "goose", name: "Goose", installed: false, connected: false, setup: "auto" },
  { id: "cursor", name: "Cursor", installed: true, connected: false, setup: "manual" },
];

test("a setup link becomes one sentence to confirm, with the agents to tick and the budget", () => {
  const c = setupLinkConfirmation({ action: "setup", agents: ["claude-code", "codex"], budget_cents: 500 }, AGENTS);
  assert.equal(c.text, "A link wants to set up Orca: connect Claude Code, Codex; daily budget $5.00");
  assert.deepEqual(c.agents, ["claude-code", "codex"]);
  assert.equal(c.budgetCents, 500);
  assert.deepEqual(c.skipped, []);
});

test("a setup link without a budget, or with agents this computer can't connect", () => {
  const c = setupLinkConfirmation({ action: "setup", agents: ["codex", "goose", "cursor", "nope"], budget_cents: null }, AGENTS);
  assert.equal(c.text, "A link wants to set up Orca: connect Codex");
  assert.deepEqual(c.agents, ["codex"]);
  assert.equal(c.budgetCents, null);
  assert.deepEqual(c.skipped, ["Goose", "Cursor", "nope"]);
  const b = setupLinkConfirmation({ action: "setup", agents: [], budget_cents: 2000 }, AGENTS);
  assert.equal(b.text, "A link wants to set up Orca: daily budget $20.00");
});

test("only setup links reach setup's confirmation", () => {
  assert.equal(setupLinkConfirmation({ action: "connect", agent: "codex" }, AGENTS), null);
  assert.equal(setupLinkConfirmation(null, AGENTS), null);
  assert.equal(setupLinkConfirmation({ action: "setup", agents: ["nope"], budget_cents: null }, AGENTS), null, "nothing to do");
});


// The panel opens setup at a step ("Add OrcaRouter backup", "Join"): it
// leaves {step, at} in localStorage (natively) or #step= in the URL.
test("requestedStep reads a fresh stored step or the URL fragment", () => {
  const now = 1_000_000;
  assert.equal(requestedStep(JSON.stringify({ step: "orcarouter", at: now - 5_000 }), "", now), "hosted");
  assert.equal(requestedStep(null, "#step=gateway", now), "company");
  assert.equal(requestedStep(null, "#x=1&step=orcarouter", now), "hosted");
});

test("requestedStep ignores stale, unknown or broken requests", () => {
  const now = 1_000_000;
  assert.equal(requestedStep(JSON.stringify({ step: "orcarouter", at: now - 120_000 }), "", now), null);
  assert.equal(requestedStep(JSON.stringify({ step: "evil", at: now }), "", now), null);
  assert.equal(requestedStep("{not json", "#step=nope", now), null);
  assert.equal(requestedStep(null, "", now), null);
});
