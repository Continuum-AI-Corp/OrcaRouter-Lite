// Unit tests for the Orca app's view logic. Run: npm test (node --test)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  AGENT_COLORS,
  agentRows,
  budgetView,
  classifyError,
  createSequencer,
  engineConfig,
  missingLine,
  money,
  providerRows,
  rescuedLine,
  tzOffsetMinutes,
  weekLine,
} from "../ui/lib.js";

const MONEY_VECTORS = JSON.parse(readFileSync(new URL("./money_vectors.json", import.meta.url), "utf8"));

test("money matches the vectors shared with Python and Rust", () => {
  for (const [micro, text] of MONEY_VECTORS) assert.equal(money(micro), text, `money(${micro})`);
});

// ── budget ──

test("budgetView without a budget", () => {
  const v = budgetView({ daily_cents: null, used_percent: null, state: "none" }, 0);
  assert.equal(v.hasBudget, false);
  assert.equal(v.tone, "none");
  assert.equal(v.caption, "No daily budget");
  assert.equal(v.percent, 0);
});

test("budgetView says how much is used, in words as well as colour", () => {
  const ok = budgetView({ daily_cents: 2000, used_percent: 16, state: "ok" }, 3_200_000);
  assert.equal(ok.caption, "16% of $20.00 alert");
  assert.equal(ok.ariaText, "$3.20 of a $20.00 daily alert used, 16%");
  assert.equal(ok.percent, 16);
  const warn = budgetView({ daily_cents: 2000, used_percent: 85, state: "warn" }, 17_000_000);
  assert.equal(warn.caption, "85% of $20.00 alert");
  assert.equal(warn.tone, "warn");
});

test("budgetView over the limit says by how much and clamps the bar", () => {
  const over = budgetView({ daily_cents: 2000, used_percent: 120.5, state: "over" }, 24_100_000);
  assert.equal(over.caption, "$4.10 over your $20.00 alert");
  assert.equal(over.percent, 100);
  assert.equal(over.tone, "over");
});

// ── agents ──

const AGENTS = [
  { id: "claude-code", name: "Claude Code", installed: true, setup: "auto", connected: true, note: "" },
  { id: "codex", name: "Codex", installed: true, setup: "unsupported", connected: false, note: "Codex needs the Responses API." },
  { id: "cursor", name: "Cursor", installed: true, setup: "manual", connected: false, note: "Paste it." },
  { id: "aider", name: "Aider", installed: false, setup: "auto", connected: false, note: "" },
  { id: "gemini-cli", name: "Gemini CLI", installed: false, setup: "unsupported", connected: false, note: "" },
];
const SPEND = [
  { id: "claude-code", name: "Claude Code", today_microcents: 2_600_000, week_microcents: 11_400_000 },
  { id: "other", name: "Other apps", today_microcents: 400_000, week_microcents: 500_000 },
];

test("agentRows orders connected, then connectable, then coming soon, then missing", () => {
  const rows = agentRows(AGENTS, SPEND);
  assert.deepEqual(rows.map((r) => r.id), ["claude-code", "cursor", "codex", "aider", "gemini-cli"]);
});

test("agentRows gives each state its badge, subtitle and action", () => {
  const by = Object.fromEntries(agentRows(AGENTS, SPEND).map((r) => [r.id, r]));
  assert.deepEqual([by["claude-code"].badge.text, by["claude-code"].action], ["Connected", "disconnect"]);
  assert.equal(by["claude-code"].today, "$2.60");
  assert.deepEqual([by.cursor.badge.text, by.cursor.action, by.cursor.subtitle], ["Manual setup", "connect", "One paste step"]);
  assert.deepEqual([by.codex.badge.text, by.codex.action], ["Coming soon", null]);
  assert.equal(by.codex.note, "Codex needs the Responses API.");
  assert.deepEqual([by.aider.badge.text, by.aider.action], ["Not installed", null]);
});

test("agentRows adds an Other apps row only when it has spend", () => {
  const rows = agentRows(AGENTS, SPEND, { includeOther: true });
  const other = rows.find((r) => r.id === "other");
  assert.equal(other.today, "$0.40");
  assert.equal(other.subtitle, "Your dashboard keys");
  const none = agentRows(AGENTS, [SPEND[0]], { includeOther: true });
  assert.equal(none.find((r) => r.id === "other"), undefined);
});

test("every agent gets two letters of initials, never padding", () => {
  for (const r of agentRows(AGENTS, SPEND)) assert.match(r.initials, /^[A-Z][A-Za-z]$/, r.id);
});

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

test("agent tile colours keep white initials readable (≥ 4:1)", () => {
  for (const [id, hex] of Object.entries(AGENT_COLORS)) {
    const ratio = 1.05 / (luminance(hex) + 0.05);
    assert.ok(ratio >= 4, `${id} ${hex} is ${ratio.toFixed(2)}:1`);
  }
});

test("missingLine folds agents that aren't installed into one sentence", () => {
  const rows = agentRows(AGENTS, SPEND);
  assert.equal(missingLine(rows), "Not installed: Aider, Gemini CLI");
  assert.equal(missingLine(rows.filter((r) => r.state !== "missing")), "");
});

// ── routing ──

test("providerRows names providers and explains their health", () => {
  const rows = providerRows([
    { provider: "anthropic", source: "db", state: "healthy" },
    { provider: "openai", source: "env", state: "degraded" },
    { provider: "orcarouter", source: "db", state: "idle" },
  ]);
  assert.deepEqual(rows.map((r) => [r.name, r.status, r.tone]), [
    ["Anthropic", "Healthy", "ok"],
    ["OpenAI", "Degraded", "warn"],
    ["OrcaRouter hosted", "Idle", "muted"],
  ]);
  // Healthy providers stay one line; only problems and idleness are explained.
  assert.equal(rows[0].detail, "");
  assert.equal(rows[1].detail, "Most requests failed in the last hour");
  assert.equal(rows[2].detail, "No requests in the last hour");
});

// ── copy ──

test("weekLine names the window and the comparison", () => {
  assert.equal(
    weekLine({ week: { spend_microcents: 14_800_000, saved_microcents: 9_100_000, baseline_model: "gpt-4o" } }),
    "Last 7 days $14.80 · saved $9.10 vs GPT-4o",
  );
  assert.equal(weekLine({ week: { spend_microcents: 0, saved_microcents: 0, baseline_model: "gpt-4o" } }), "Last 7 days $0.00");
});

test("rescuedLine explains fallback in plain words", () => {
  assert.equal(rescuedLine(0), "");
  assert.equal(rescuedLine(1), "1 failed request was retried on another provider in the last 7 days");
  assert.equal(rescuedLine(3), "3 failed requests were retried on another provider in the last 7 days");
});

// ── plumbing ──

test("classifyError separates offline, signed-out and other failures", () => {
  assert.equal(classifyError({ status: 0 }), "offline");
  assert.equal(classifyError({ status: 401 }), "auth");
  assert.equal(classifyError({ status: 403 }), "auth");
  assert.equal(classifyError({ status: 500 }), "error");
});

test("a sequencer drops results that arrive after a newer request started", () => {
  const seq = createSequencer();
  const first = seq.next();
  const second = seq.next();
  assert.equal(seq.isLatest(first), false);
  assert.equal(seq.isLatest(second), true);
});

test("tzOffsetMinutes is minutes east of UTC", () => {
  assert.equal(tzOffsetMinutes({ getTimezoneOffset: () => -120 }), 120);
  assert.equal(tzOffsetMinutes({ getTimezoneOffset: () => 300 }), -300);
});

test("engineConfig prefers what the native app injected", () => {
  const cfg = engineConfig({ origin: "http://127.0.0.1:8765", hash: "#key=sk-orca-x" }, { key: "sk-orca-app" });
  assert.deepEqual(cfg, { baseUrl: "http://127.0.0.1:8765", key: "sk-orca-app" });
});

test("engineConfig falls back to the URL fragment in a browser", () => {
  const cfg = engineConfig({ origin: "http://127.0.0.1:8765", hash: "#key=sk-orca-abc" }, undefined);
  assert.deepEqual(cfg, { baseUrl: "http://127.0.0.1:8765", key: "sk-orca-abc" });
  assert.equal(engineConfig({ origin: "http://127.0.0.1:8765", hash: "" }, undefined).key, "");
});
