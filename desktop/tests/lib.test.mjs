// Unit tests for the Orca app's view logic. Run: node --test desktop/tests
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  agentRows,
  missingLine,
  budgetView,
  engineConfig,
  money,
  providerRows,
  tzOffsetMinutes,
  weekLine,
} from "../ui/lib.js";

test("money rounds half-up to cents like the engine does", () => {
  assert.equal(money(0), "$0.00");
  assert.equal(money(4_999), "$0.00");
  assert.equal(money(5_000), "$0.01");
  assert.equal(money(1_234_567), "$1.23");
  assert.equal(money(3_200_000), "$3.20");
  assert.equal(money(123_456_789_000), "$123,456.79");
});

test("budgetView without a budget", () => {
  const v = budgetView({ daily_cents: null, used_percent: null, state: "none" });
  assert.equal(v.hasBudget, false);
  assert.equal(v.tone, "none");
  assert.equal(v.caption, "No daily budget");
  assert.equal(v.percent, 0);
});

test("budgetView with a budget clamps the bar and keeps the tone", () => {
  const ok = budgetView({ daily_cents: 2000, used_percent: 16, state: "ok" });
  assert.equal(ok.caption, "of $20.00 budget");
  assert.equal(ok.percent, 16);
  assert.equal(ok.tone, "ok");
  const over = budgetView({ daily_cents: 2000, used_percent: 140, state: "over" });
  assert.equal(over.percent, 100);
  assert.equal(over.tone, "over");
});

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

test("agentRows gives each state its badge and action", () => {
  const by = Object.fromEntries(agentRows(AGENTS, SPEND).map((r) => [r.id, r]));
  assert.deepEqual([by["claude-code"].badge.text, by["claude-code"].action], ["Connected", "disconnect"]);
  assert.equal(by["claude-code"].today, "$2.60");
  assert.deepEqual([by.cursor.badge.text, by.cursor.action], ["Manual setup", "connect"]);
  assert.deepEqual([by.codex.badge.text, by.codex.action], ["Coming soon", null]);
  assert.equal(by.codex.note, "Codex needs the Responses API.");
  assert.deepEqual([by.aider.badge.text, by.aider.action], ["Not installed", null]);
});

test("agentRows adds an Other apps row only when it has spend", () => {
  const rows = agentRows(AGENTS, SPEND, { includeOther: true });
  const other = rows.find((r) => r.id === "other");
  assert.equal(other.today, "$0.40");
  const none = agentRows(AGENTS, [SPEND[0]], { includeOther: true });
  assert.equal(none.find((r) => r.id === "other"), undefined);
});

test("agentRows gives every agent short initials", () => {
  for (const r of agentRows(AGENTS, SPEND)) assert.ok(r.initials.length === 2, r.id);
});

test("providerRows names providers and maps health to a tone", () => {
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
});

test("weekLine summarises spend and savings", () => {
  assert.equal(
    weekLine({ week: { spend_microcents: 14_800_000, saved_microcents: 9_100_000 } }),
    "This week $14.80 · saved $9.10",
  );
  assert.equal(weekLine({ week: { spend_microcents: 0, saved_microcents: 0 } }), "This week $0.00");
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

test("missingLine folds agents that aren't installed into one sentence", () => {
  const rows = agentRows(AGENTS, SPEND);
  assert.equal(missingLine(rows), "Not installed: Aider, Gemini CLI");
  assert.equal(missingLine(rows.filter((r) => r.state !== "missing")), "");
});
