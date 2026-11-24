// Unit tests for the panel's roadmap views (desktop/ui/panel-lib.js) and the
// shared link helper (withRef in desktop/ui/lib.js). Run: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { withRef } from "../ui/lib.js";
import {
  agentBudgetView,
  backupOfferView,
  benchmarkKeyView,
  cardLayout,
  changedText,
  clockTime,
  costShort,
  fitFontSize,
  guessHome,
  hostedProviderDetail,
  linkSheet,
  listNames,
  localDate,
  localModelDetail,
  localView,
  modelFamily,
  modelPrice,
  paidModelPrompt,
  panelAgentRows,
  panelProviderRows,
  pickerChoice,
  pickerView,
  providerName,
  requestRows,
  routerSettingsInput,
  setupHash,
  shareCardText,
  shareIntentUrl,
  shortModel,
  substitutionHint,
  substitutionNote,
  teamGatewayView,
  testResultView,
  tildePath,
  todayFreeLine,
  toggleLocal,
  tokenFlow,
  tokens,
  weekSplitLine,
} from "../ui/panel-lib.js";

// ── H8: every outgoing link says where it came from ──

test("withRef adds the source and replaces an earlier ref", () => {
  assert.equal(withRef("https://www.orcarouter.ai/console", "lite-panel"), "https://www.orcarouter.ai/console?ref=lite-panel");
  assert.equal(
    withRef("https://continuum-ai-corp.github.io/OrcaRouter-Lite/?a=1&ref=lite-card", "lite-share"),
    "https://continuum-ai-corp.github.io/OrcaRouter-Lite/?a=1&ref=lite-share",
  );
  // Idempotent: the engine's links already carry it.
  const once = withRef("https://www.orcarouter.ai/console/topup?ref=lite-panel", "lite-panel");
  assert.equal(withRef(once, "lite-panel"), once);
});

test("withRef only knows fixed sources and only web links", () => {
  assert.throws(() => withRef("https://example.com/", "me@example.com"));
  assert.equal(withRef(null, "lite-panel"), null);
  assert.equal(withRef("", "lite-panel"), null);
  assert.equal(withRef("javascript:alert(1)", "lite-panel"), null);
  assert.equal(withRef("not a url", "lite-panel"), null);
});

// ── formatting ──

test("costShort shows fractions of a cent for single requests", () => {
  assert.equal(costShort(71_000), "$0.071");
  assert.equal(costShort(1_000), "$0.001");
  assert.equal(costShort(334_400), "$0.334");
  assert.equal(costShort(0), "$0");
  assert.equal(costShort(200), "<$0.001");
  assert.equal(costShort(2_500_000), "$2.50");
});

test("tokens and tokenFlow read like the mockup", () => {
  assert.equal(tokens(90), "90");
  assert.equal(tokens(2_100), "2.1K");
  assert.equal(tokens(18_200), "18.2K");
  assert.equal(tokens(41_000), "41.0K");
  assert.equal(tokens(128_000), "128K");
  assert.equal(tokens(1_250_000), "1.3M");
  assert.equal(tokens(null), "0");
  assert.equal(tokenFlow(96_400, 3_000), "96.4K→3.0K");
});

test("shortModel drops vendor prefixes", () => {
  assert.equal(shortModel("claude-sonnet-4-6"), "sonnet-4-6");
  assert.equal(shortModel("deepseek/deepseek-v4-flash"), "v4-flash");
  assert.equal(shortModel("gpt-4.1"), "gpt-4.1");
  assert.equal(shortModel("ollama/qwen3-coder:30b"), "qwen3-coder:30b");
  assert.equal(shortModel(""), "—");
  assert.equal(shortModel(null), "—");
});

test("clockTime is the local 24-hour time", () => {
  assert.equal(clockTime("2026-11-24T14:32:10+00:00", 0), "14:32");
  assert.equal(clockTime("2026-11-24T14:32:10+00:00", -300), "09:32");
  assert.equal(clockTime("2026-11-24T23:05:00Z", 60), "00:05");
  assert.equal(clockTime("nonsense", 0), "");
});

test("localDate is YYYY-MM-DD in the given offset", () => {
  assert.equal(localDate(new Date("2026-11-24T23:30:00Z"), 60), "2026-11-25");
  assert.equal(localDate(new Date("2026-11-24T02:00:00Z"), -300), "2026-11-23");
});

test("tildePath hides the home folder", () => {
  assert.equal(tildePath("/Users/ana/.claude/settings.json"), "~/.claude/settings.json");
  assert.equal(tildePath("/home/ana/.codex/config.toml"), "~/.codex/config.toml");
  assert.equal(tildePath("C:\\Users\\ana\\.claude\\settings.json"), "~\\.claude\\settings.json");
  assert.equal(tildePath("/root/.claude/settings.json"), "~/.claude/settings.json");
  assert.equal(tildePath("~/.claude/settings.json"), "~/.claude/settings.json");
  assert.equal(tildePath(null), "");
});

test("modelFamily knows the vendor behind a model name", () => {
  assert.deepEqual(modelFamily("claude-sonnet-4-6"), { vendor: "Anthropic", family: "Claude", provider: "anthropic" });
  assert.equal(modelFamily("anthropic/claude-haiku-4-5").family, "Claude");
  assert.equal(modelFamily("gpt-4.1").vendor, "OpenAI");
  assert.equal(modelFamily("gemini-2.5-pro").family, "Gemini");
  assert.equal(modelFamily("kimi-k2.6").vendor, "Moonshot");
  assert.equal(modelFamily("glm-5.2").family, "GLM");
  assert.equal(modelFamily("something-else"), null);
});

test("providerName covers every provider id the engine reports", () => {
  for (const [id, name] of [["orcarouter", "OrcaRouter"], ["anthropic", "Anthropic"], ["zai", "Z.ai"], ["openrouter", "OpenRouter"],
    ["moonshot", "Moonshot"], ["local", "This computer"], ["mystery", "mystery"]]) {
    assert.equal(providerName(id), name);
  }
});

// ── H0: free first ──

test("todayFreeLine splits free from paid requests", () => {
  assert.equal(todayFreeLine({ requests: 64, free_requests: 64 }), "64 requests on OrcaRouter's free models");
  assert.equal(todayFreeLine({ requests: 1, free_requests: 1 }), "1 request on OrcaRouter's free models");
  assert.equal(todayFreeLine({ requests: 70, free_requests: 64 }), "64 requests on OrcaRouter's free models · 6 paid");
  assert.equal(todayFreeLine({ requests: 5, free_requests: 0 }), "");
  assert.equal(todayFreeLine(undefined), "");
});

test("paidModelPrompt appears only while OrcaRouter is on free models", () => {
  assert.equal(paidModelPrompt({ configured: false, models: "free" }), null);
  assert.equal(paidModelPrompt({ configured: true, models: "all", needs_paid_today: 4 }), null);
  const plain = paidModelPrompt({ configured: true, models: "free", needs_paid_today: 0 });
  assert.equal(plain.text, "Agents use OrcaRouter's free models.");
  assert.equal(plain.action, "Use a paid model");
  assert.match(plain.confirm, /provider's price/);
  assert.doesNotMatch(plain.confirm, /\$5/);
  assert.equal(paidModelPrompt({ configured: true, models: "free", needs_paid_today: 3 }).text, "3 requests needed a paid model today.");
  assert.equal(paidModelPrompt({ configured: true, models: "free", needs_paid_today: 1 }).text, "1 request needed a paid model today.");
});

// ── H2: backup offer ──

test("backupOfferView says what failed and what OrcaRouter would take", () => {
  const v = backupOfferView({ id: "backup", failed_today: 3, provider: "anthropic", agent: "claude-code", models: ["claude-sonnet-4-6"] });
  assert.equal(v.lead, "3 requests failed today.");
  assert.equal(v.rest, "Anthropic was overloaded and none of your other keys has Claude.");
  assert.equal(
    v.body,
    "Add OrcaRouter's gateway as a backup and Orca sends only requests like these to it. You pay per request at the provider's price; nothing else changes.",
  );
  const one = backupOfferView({ failed_today: 1, provider: "openai", models: [] });
  assert.equal(one.lead, "1 request failed today.");
  assert.equal(one.rest, "OpenAI was overloaded and none of your other keys could take it.");
  assert.equal(backupOfferView(null), null);
  assert.equal(backupOfferView({ failed_today: 0, provider: "openai" }), null);
});

// ── H3: substitutions ──

test("substitution hint and note", () => {
  const subs = [{ requested: "claude-sonnet-4-6", served: "gpt-4.1", count: 41 }];
  assert.equal(substitutionHint(subs), "Getting GPT instead of Claude");
  assert.equal(substitutionHint([{ requested: "claude-opus-4-6", served: "claude-haiku-4-5", count: 1 }]), "Getting claude-haiku-4-5 instead");
  assert.equal(substitutionHint([{ requested: "x-1", served: "gpt-4.1", count: 1 }]), "Getting gpt-4.1 instead");
  assert.equal(substitutionHint([]), "");
  const n = substitutionNote("Claude Code", subs[0], { configured: false, models: "free" });
  assert.equal(n.text, "Claude Code asked for claude-sonnet-4-6 41 times today. You have no Anthropic key, so gpt-4.1 answered.");
  assert.equal(n.offerTitle, "Get Claude through OrcaRouter");
  assert.equal(n.offerDetail, "Pay per token at Anthropic's price, no subscription");
  assert.equal(n.keep, "Keep using gpt-4.1");
  assert.equal(n.action, "setup");
  assert.equal(substitutionNote("Codex", { requested: "mystery-1", served: "gpt-4.1", count: 1 }, {}).text,
    "Codex asked for mystery-1 once today. You have no key for it, so gpt-4.1 answered.");
  // With an OrcaRouter key on free models, the action turns paid models on.
  assert.equal(substitutionNote("Claude Code", subs[0], { configured: true, models: "free" }).action, "paid");
  assert.equal(substitutionNote("Claude Code", subs[0], { configured: true, models: "all" }).action, null);
});

// ── agent rows: D5 changed, H3 hint, D3 paused ──

test("panelAgentRows marks changed agents and adds hints", () => {
  const agents = [
    { id: "claude-code", name: "Claude Code", installed: true, setup: "auto", connected: true, changed: true, config_path: "/home/a/.claude/settings.json" },
    { id: "codex", name: "Codex", installed: true, setup: "auto", connected: true, changed: false },
    { id: "opencode", name: "OpenCode", installed: true, setup: "auto", connected: false },
  ];
  const spend = [
    { id: "claude-code", today_microcents: 0, week_microcents: 0, state: "changed", substitutions: [] },
    { id: "codex", today_microcents: 2_600_000, week_microcents: 9, state: "connected", paused: false,
      substitutions: [{ requested: "claude-sonnet-4-6", served: "gpt-4.1", count: 2 }] },
  ];
  const rows = panelAgentRows(agents, spend);
  const cc = rows.find((r) => r.id === "claude-code");
  assert.equal(cc.state, "changed");
  assert.equal(cc.subtitle, "Its settings changed");
  assert.equal(cc.action, "reconnect");
  assert.equal(cc.opens, true);
  const codex = rows.find((r) => r.id === "codex");
  assert.equal(codex.subtitle, "Getting GPT instead of Claude");
  assert.equal(codex.hint, true);
  assert.equal(codex.opens, true);
  assert.equal(rows.find((r) => r.id === "opencode").opens, false);
  const paused = panelAgentRows(agents.slice(1, 2), [{ ...spend[1], paused: true, budget_cents: 500, substitutions: [] }]);
  assert.equal(paused[0].subtitle, "Paused at its $5.00 daily budget");
});

test("changedText names the file and the likely cause", () => {
  assert.equal(
    changedText("Claude Code", "/Users/a/.claude/settings.json"),
    "Something replaced Orca's settings in ~/.claude/settings.json, probably Claude Code's last update. Its requests aren't going through Orca.",
  );
  assert.equal(changedText("Codex", null), "Something replaced Orca's settings, probably Codex's last update. Its requests aren't going through Orca.");
});

// ── H4: OrcaRouter spend ──

test("hostedProviderDetail sums this month", () => {
  assert.equal(hostedProviderDetail({ month_spend_microcents: 1_800_000, month_requests: 120, month_rescued: 37 }), "$1.80 this month · 37 requests rescued");
  assert.equal(hostedProviderDetail({ month_spend_microcents: 0, month_requests: 64, month_rescued: 0 }), "$0.00 this month · 64 requests");
  assert.equal(hostedProviderDetail({ month_spend_microcents: 10_000, month_requests: 1, month_rescued: 1 }), "$0.01 this month · 1 request rescued");
  assert.equal(hostedProviderDetail({ month_spend_microcents: 0, month_requests: 0, month_rescued: 0 }), "No requests this month");
});

test("panelProviderRows puts OrcaRouter first with its balance link", () => {
  const s = {
    providers: [{ provider: "anthropic", state: "healthy" }, { provider: "orcarouter", state: "idle" }],
    hosted: { configured: true, out_of_credit: false, month_spend_microcents: 1_800_000, month_requests: 40, month_rescued: 37,
      console_url: "https://www.orcarouter.ai/console?ref=lite-panel" },
  };
  const rows = panelProviderRows(s);
  assert.equal(rows[0].id, "orcarouter");
  assert.equal(rows[0].name, "OrcaRouter");
  assert.equal(rows[0].detail, "$1.80 this month · 37 requests rescued");
  assert.equal(rows[0].link.text, "Balance");
  assert.equal(rows[0].link.url, "https://www.orcarouter.ai/console?ref=lite-panel");
  assert.equal(rows[1].name, "Anthropic");
  assert.equal(rows[1].status, "Healthy");
  const broke = panelProviderRows({ ...s, hosted: { ...s.hosted, out_of_credit: true } });
  assert.equal(broke[0].status, "Out of credit");
  assert.equal(broke[0].tone, "err");
  // Configured through the environment but not listed: still shown.
  const env = panelProviderRows({ providers: [], hosted: { ...s.hosted } });
  assert.equal(env[0].id, "orcarouter");
});

// ── H5: the model picker ──

const GROUPS = [
  { id: "yours", label: "Your keys", total: 2, models: [
    { id: "gpt-4.1", name: "gpt-4.1", provider: "openai", input_per_m: 2, output_per_m: 8, free: false, available: true },
    { id: "gpt-4o-mini", name: "gpt-4o-mini", provider: "openai", input_per_m: 0.15, output_per_m: 0.6, free: false, available: true },
  ] },
  { id: "local", label: "On this computer", total: 0, models: [] },
  { id: "free", label: "Free on OrcaRouter", total: 1, models: [
    { id: "deepseek/deepseek-v4-pro-free", name: "deepseek-v4-pro-free", provider: "orcarouter", input_per_m: 0, output_per_m: 0, free: true, available: false },
  ] },
  { id: "paid", label: "Paid on OrcaRouter", total: 2, models: [
    { id: "claude-sonnet-4.6", name: "claude-sonnet-4.6", provider: "orcarouter", input_per_m: 3, output_per_m: 15, free: false, available: false },
    { id: "kimi-k2.6", name: "kimi-k2.6", provider: "orcarouter", input_per_m: null, output_per_m: null, free: false, available: false },
  ] },
];

test("modelPrice per million tokens", () => {
  assert.equal(modelPrice(GROUPS[0].models[0]), "$2.00 / $8.00 per M tokens");
  assert.equal(modelPrice(GROUPS[0].models[1]), "$0.15 / $0.60 per M tokens");
  assert.equal(modelPrice({ free: true, provider: "orcarouter" }), "$0 · free model");
  assert.equal(modelPrice({ free: true, provider: "local" }), "$0 · on this computer");
  assert.equal(modelPrice({ input_per_m: null, output_per_m: null }), "Price not listed");
  assert.equal(modelPrice({ input_per_m: 0.075, output_per_m: 0.3 }), "$0.075 / $0.30 per M tokens");
});

test("pickerView groups, tags and explains unavailable models", () => {
  const v = pickerView(GROUPS, { query: "", hostedConfigured: false, hostedModels: "free" });
  assert.equal(v.total, 5);
  assert.deepEqual(v.groups.map((g) => g.label), ["Your keys", "Free on OrcaRouter", "Paid on OrcaRouter"]); // empty groups hidden
  const [mine] = v.groups[0].items;
  assert.equal(mine.tag, "Your key");
  assert.equal(mine.available, true);
  const free = v.groups[1].items[0];
  assert.equal(free.tag, "Free");
  assert.equal(free.reason, "Needs an OrcaRouter key");
  const paid = v.groups[2].items[0];
  assert.equal(paid.tag, "OrcaRouter");
  const keyed = pickerView(GROUPS, { query: "", hostedConfigured: true, hostedModels: "free" });
  assert.equal(keyed.groups[2].items[0].reason, "Paid models are off");
});

test("pickerView filters by every word typed", () => {
  const v = pickerView(GROUPS, { query: "GPT mini", hostedConfigured: true, hostedModels: "all" });
  assert.equal(v.groups.length, 1);
  assert.deepEqual(v.groups[0].items.map((i) => i.id), ["gpt-4o-mini"]);
  assert.equal(v.matches, 1);
  assert.equal(pickerView(GROUPS, { query: "zzz" }).groups.length, 0);
});

test("pickerChoice decides what clicking a model does", () => {
  const opts = { hostedConfigured: false, hostedModels: "free" };
  assert.equal(pickerChoice(GROUPS[0].models[0], "yours", opts).kind, "select");
  assert.equal(pickerChoice(GROUPS[2].models[0], "free", opts).kind, "needs_key");
  assert.equal(pickerChoice(GROUPS[3].models[0], "paid", opts).kind, "needs_key");
  assert.equal(pickerChoice(GROUPS[3].models[0], "paid", { hostedConfigured: true, hostedModels: "free" }).kind, "needs_paid");
  assert.equal(pickerChoice({ ...GROUPS[3].models[0], available: true }, "paid", { hostedConfigured: true, hostedModels: "all" }).kind, "select");
  assert.equal(pickerChoice({ id: "ollama/x", available: false }, "local", opts).kind, "unavailable");
});

// ── D3: budgets and the request log ──

test("agentBudgetView", () => {
  assert.deepEqual(agentBudgetView(2_600_000, 500), { hasBudget: true, caption: "$2.60 of $5.00", percent: 52, tone: "ok" });
  assert.equal(agentBudgetView(4_500_000, 500).tone, "warn");
  assert.equal(agentBudgetView(6_000_000, 500).percent, 100);
  assert.equal(agentBudgetView(6_000_000, 500).tone, "over");
  assert.equal(agentBudgetView(0, null).hasBudget, false);
  assert.equal(agentBudgetView(1, 0).tone, "over");
});

test("requestRows formats the log and explains rescues and substitutions", () => {
  const rows = requestRows([
    { at: "2026-11-24T14:32:00+00:00", model_requested: "claude-sonnet-4-6", model: "claude-sonnet-4-6", provider: "anthropic",
      input_tokens: 18_200, output_tokens: 1_100, cost_microcents: 71_000, status: 200, rescued: false, note: null },
    { at: "2026-11-24T14:21:00+00:00", model_requested: "claude-sonnet-4-6", model: "gpt-4.1", provider: "openai",
      input_tokens: 41_000, output_tokens: 900, cost_microcents: 89_000, status: 200, rescued: true, note: null },
    { at: "2026-11-24T14:10:00+00:00", model_requested: "claude-sonnet-4-6", model: "gpt-4.1", provider: "openai",
      input_tokens: 100, output_tokens: 10, cost_microcents: 1_000, status: 200, rescued: false, note: "substituted" },
    { at: "2026-11-24T14:00:00+00:00", model_requested: "claude-sonnet-4-6", model: "claude-sonnet-4-6", provider: "anthropic",
      input_tokens: 0, output_tokens: 0, cost_microcents: 0, status: 529, rescued: false, note: "no_fallback" },
    { at: "2026-11-24T13:00:00+00:00", model_requested: "auto", model: "deepseek/deepseek-v4-flash-free", provider: "orcarouter",
      input_tokens: 10, output_tokens: 5, cost_microcents: 0, status: 422, rescued: false, note: "needs_paid" },
  ], { tzOffsetMinutes: 0 });
  assert.deepEqual(
    { time: rows[0].time, model: rows[0].model, tokens: rows[0].tokens, cost: rows[0].cost, tag: rows[0].tag, note: rows[0].note },
    { time: "14:32", model: "sonnet-4-6", tokens: "18.2K→1.1K", cost: "$0.071", tag: null, note: "" },
  );
  assert.equal(rows[1].tag, "rescued");
  assert.equal(rows[1].note, "Anthropic didn't answer at 14:21; Orca sent the request to OpenAI.");
  assert.equal(rows[2].note, "Asked for claude-sonnet-4-6 at 14:10; no key of yours serves it, so gpt-4.1 answered.");
  assert.equal(rows[3].tag, "failed");
  assert.equal(rows[3].note, "Anthropic failed at 14:00 and none of your other keys could take it.");
  assert.equal(rows[4].note, "Needed a paid model at 13:00; OrcaRouter is on free models only.");
});

// ── D4: test results ──

test("requestRows explains a run of the same failure once", () => {
  const fail = (at) => ({ at, model_requested: "claude-sonnet-4-6", model: "claude-sonnet-4-6", provider: "anthropic",
    input_tokens: 0, output_tokens: 0, cost_microcents: 0, status: 529, rescued: false, note: "no_fallback" });
  const rows = requestRows([fail("2026-11-24T14:13:30Z"), fail("2026-11-24T14:13:20Z"), fail("2026-11-24T14:12:00Z")], { tzOffsetMinutes: 0 });
  assert.equal(rows[0].note, "Anthropic failed at 14:13 and none of your other keys could take it.");
  assert.equal(rows[1].note, "");
  assert.equal(rows[2].note, "");
  assert.equal(rows.every((r) => r.tag === "failed"), true);
});

test("guessHome finds the folder every agent config lives under", () => {
  const paths = ["/tmp/x/home/.claude/settings.json", "/tmp/x/home/.codex/config.toml", "/tmp/x/home/.config/opencode/opencode.json", null];
  assert.equal(guessHome(paths), "/tmp/x/home");
  assert.equal(guessHome(["C:\\Users\\a\\.claude\\settings.json", "C:\\Users\\a\\.codex\\config.toml"]), "C:\\Users\\a");
  assert.equal(guessHome(["/a/.claude/x", "/b/.codex/y"]), null);
  assert.equal(guessHome([]), null);
  assert.equal(tildePath("/tmp/x/home/.codex/config.toml", "/tmp/x/home"), "~/.codex/config.toml");
  assert.equal(changedText("Codex", "/tmp/x/home/.codex/config.toml", "/tmp/x/home"),
    "Something replaced Orca's settings in ~/.codex/config.toml, probably Codex's last update. Its requests aren't going through Orca.");
});

test("testResultView", () => {
  assert.deepEqual(testResultView({ ok: true, model: "claude-sonnet-4-6", seconds: 0.84, config_path: "~/.claude/settings.json" }), {
    tone: "ok", lead: "Works.", text: "Answered in 0.8 s by claude-sonnet-4-6, using ~/.claude/settings.json.",
  });
  assert.equal(testResultView({ ok: true, model: "gpt-4.1", seconds: 12.3, config_path: null }).text, "Answered in 12 s by gpt-4.1.");
  assert.deepEqual(testResultView({ ok: false, error: "Google rejected the key (401). Replace it in Providers, then test again." }), {
    tone: "err", lead: "", text: "Google rejected the key (401). Replace it in Providers, then test again.",
  });
  assert.equal(testResultView({ ok: null, error: "Paste the key into Cursor, then test from the agent." }).tone, "info");
  assert.equal(testResultView({ ok: false, error: null }).text, "The test didn't finish. Try again.");
});

// ── P2 · D1 + H6: this computer ──

const RUNTIMES = [
  { id: "ollama", name: "Ollama", url: "127.0.0.1:11434", running: true, models: [
    { id: "ollama/qwen3-coder:30b", name: "qwen3-coder:30b", tools: true, vision: false, context: 262144, enabled: true },
    { id: "ollama/gpt-oss:20b", name: "gpt-oss:20b", tools: true, vision: false, context: 131072, enabled: true },
    { id: "ollama/llava:7b", name: "llava:7b", tools: false, vision: true, context: 4096, enabled: false },
  ] },
  { id: "lmstudio", name: "LM Studio", url: "127.0.0.1:1234", running: false, models: [] },
];

test("localView describes runtimes and models", () => {
  const v = localView(RUNTIMES);
  assert.equal(v.anyRunning, true);
  assert.equal(v.runtimes[0].detail, "127.0.0.1:11434 · found 3 models");
  assert.equal(v.runtimes[0].status, "Running");
  assert.equal(v.runtimes[0].initials, "OL");
  assert.equal(v.runtimes[1].detail, "Not running · checks 127.0.0.1:1234");
  assert.equal(v.runtimes[1].status, "Off");
  assert.equal(localView([{ ...RUNTIMES[0], models: [RUNTIMES[0].models[0]] }]).runtimes[0].detail, "127.0.0.1:11434 · found 1 model");
  // The summary's runtimes carry a count, not a list.
  assert.equal(localView([{ id: "ollama", name: "Ollama", url: "x", running: true, models: 2 }]).runtimes[0].detail, "x · found 2 models");
  assert.equal(localView([]).anyRunning, false);
});

test("localModelDetail", () => {
  assert.equal(localModelDetail(RUNTIMES[0].models[0]), "Tools, 256K context");
  assert.equal(localModelDetail(RUNTIMES[0].models[2]), "Images, 4K context · no tool use");
  assert.equal(localModelDetail({ tools: true, vision: true, context: null }), "Tools, images");
});

test("toggleLocal turns one model on or off", () => {
  assert.deepEqual(toggleLocal(RUNTIMES, null, "ollama/gpt-oss:20b", false), ["ollama/qwen3-coder:30b"]);
  assert.deepEqual(toggleLocal(RUNTIMES, null, "ollama/llava:7b", true), ["ollama/qwen3-coder:30b", "ollama/gpt-oss:20b", "ollama/llava:7b"]);
  assert.deepEqual(toggleLocal(RUNTIMES, ["ollama/gpt-oss:20b"], "ollama/gpt-oss:20b", true), ["ollama/gpt-oss:20b"]);
});

test("weekSplitLine splits local from OrcaRouter", () => {
  assert.equal(weekSplitLine({ local_requests: 212, local_saved_microcents: 4_100_000, hosted_requests: 37 }),
    "212 answered locally, about $4.10 you didn't spend · 37 through OrcaRouter");
  assert.equal(weekSplitLine({ local_requests: 1, local_saved_microcents: 0, hosted_requests: 0 }), "1 answered locally");
  assert.equal(weekSplitLine({ local_requests: 0, hosted_requests: 5 }), "5 through OrcaRouter");
  assert.equal(weekSplitLine({ local_requests: 0, hosted_requests: 0 }), "");
});

// ── D7: settings ──

test("routerSettingsInput validates retries and rest time", () => {
  assert.deepEqual(routerSettingsInput("2", "60"), { values: { router_num_retries: 2, router_cooldown_seconds: 60 }, error: null });
  assert.deepEqual(routerSettingsInput("", " "), { values: { router_num_retries: null, router_cooldown_seconds: null }, error: null });
  assert.equal(routerSettingsInput("9", "60").error.field, "retries");
  assert.equal(routerSettingsInput("1.5", "60").error.field, "retries");
  assert.equal(routerSettingsInput("1", "4000").error.field, "cooldown");
  assert.equal(routerSettingsInput("1", "-1").error.field, "cooldown");
  assert.match(routerSettingsInput("9", "").error.message, /0 to 5/);
});

test("benchmarkKeyView", () => {
  assert.equal(benchmarkKeyView({ configured: false }).mode, "empty");
  const env = benchmarkKeyView({ configured: true, source: "env", hint: "aa-…3f2" });
  assert.equal(env.mode, "env");
  assert.match(env.text, /environment/);
  assert.deepEqual(benchmarkKeyView({ configured: true, source: "app", hint: "aa-…3f2" }), { mode: "saved", hint: "aa-…3f2", text: "Saved on this computer, encrypted." });
});

// ── H7: team ──

test("teamGatewayView", () => {
  assert.deepEqual(teamGatewayView({ url: "https://ai-gw.acme.dev/v1" }), {
    joined: true, title: "Team gateway", detail: "ai-gw.acme.dev · spend tracked by your team", initials: "AI",
  });
  assert.equal(teamGatewayView(null).joined, false);
});

// ── V2: the savings card ──

test("listNames", () => {
  assert.equal(listNames(["Claude Code"]), "Claude Code");
  assert.equal(listNames(["Claude Code", "Codex"]), "Claude Code and Codex");
  assert.equal(listNames(["A", "B", "C"]), "A, B and C");
  assert.equal(listNames(["A", "B", "C", "D", "E"]), "A, B and 3 more");
});

test("shareCardText matches the mockup and shows totals only", () => {
  const card = { week_saved_microcents: 38_400_000, week_spend_microcents: 9_000_000, rescued: 6, agents: ["Claude Code", "Codex"],
    local_requests: 0, link: "https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-card" };
  const t = shareCardText(card);
  assert.equal(t.kicker, "This week, across Claude Code and Codex");
  assert.equal(t.headline, "Orca saved me $38.40");
  assert.equal(t.sub, "and rescued 6 requests");
  assert.equal(t.footer, "github.io/OrcaRouter-Lite");
  assert.equal(t.post, "This week Orca saved me $38.40 and rescued 6 requests across Claude Code and Codex.");
  assert.equal(shareCardText({ ...card, rescued: 1 }).sub, "and rescued 1 request");
  const nothing = shareCardText({ ...card, week_saved_microcents: 0, rescued: 0, agents: [], local_requests: 0 });
  assert.equal(nothing.kicker, "This week, with my coding agents");
  assert.equal(nothing.headline, "Orca kept my coding agents on budget");
  assert.equal(nothing.sub, "");
  assert.equal(nothing.shareable, false);
  assert.equal(shareCardText({ ...card, week_saved_microcents: 0, rescued: 0, local_requests: 212 }).headline, "Orca answered 212 requests on my computer");
});

test("shareIntentUrl builds X and LinkedIn links carrying the card link", () => {
  const link = "https://continuum-ai-corp.github.io/OrcaRouter-Lite/?ref=lite-card";
  const x = new URL(shareIntentUrl("x", { text: "Saved $1.00", link }));
  assert.equal(x.origin + x.pathname, "https://x.com/intent/post");
  assert.equal(x.searchParams.get("text"), "Saved $1.00");
  assert.equal(x.searchParams.get("url"), link);
  const li = new URL(shareIntentUrl("linkedin", { text: "x", link }));
  assert.equal(li.origin + li.pathname, "https://www.linkedin.com/sharing/share-offsite/");
  assert.equal(li.searchParams.get("url"), link);
  // A link that lost its ref gets it back; a foreign link isn't shared.
  assert.equal(new URL(shareIntentUrl("x", { text: "", link: "https://continuum-ai-corp.github.io/OrcaRouter-Lite/" })).searchParams.get("url"), link);
  assert.equal(shareIntentUrl("x", { text: "", link: "https://evil.example/" }), null);
  assert.equal(shareIntentUrl("mastodon", { text: "", link }), null);
});

test("fitFontSize shrinks until the text fits", () => {
  const measure = (text, size) => text.length * size * 0.5;
  assert.equal(fitFontSize(measure, "short", 1000, { max: 40, min: 20 }), 40);
  assert.equal(fitFontSize(measure, "x".repeat(50), 1000, { max: 60, min: 20 }), 40);
  assert.equal(fitFontSize(measure, "x".repeat(500), 1000, { max: 60, min: 20 }), 20);
});

test("cardLayout keeps every line inside the card", () => {
  const measure = (text, size) => text.length * size * 0.55;
  const t = shareCardText({ week_saved_microcents: 1_234_567_000_000, rescued: 1234, agents: ["Claude Code", "Codex", "Gemini CLI", "OpenCode"], local_requests: 0 });
  const L = cardLayout(measure, t, { width: 1200, height: 630 });
  const pad = L.pad;
  for (const line of [L.kicker, L.headline, L.sub, L.footer]) {
    if (!line.text) continue;
    assert.ok(line.x >= pad && line.x + measure(line.text, line.size) <= 1200 - pad + 0.5, `${line.text} overflows`);
    assert.ok(line.y > 0 && line.y < 630, `${line.text} outside vertically`);
  }
  assert.ok(L.headline.y < L.sub.y && L.sub.y < L.footer.y);
  assert.ok(L.kicker.y < L.headline.y);
});

// ── V3: orca:// links ──

const AGENTS = [
  { id: "claude-code", name: "Claude Code", installed: true, setup: "auto", connected: false },
  { id: "codex", name: "Codex", installed: true, setup: "auto", connected: true },
  { id: "cursor", name: "Cursor", installed: true, setup: "manual", connected: false },
  { id: "goose", name: "Goose", installed: false, setup: "auto", connected: false },
];

test("linkSheet: connect", () => {
  const s = linkSheet({ action: "connect", agent: "claude-code" }, AGENTS);
  assert.equal(s.kind, "connect");
  assert.equal(s.title, "Connect Claude Code");
  assert.equal(s.ready, true);
  assert.equal(s.confirm, "Connect");
  assert.equal(linkSheet({ action: "connect", agent: "codex" }, AGENTS).detail, "Codex is already connected to Orca.");
  assert.equal(linkSheet({ action: "connect", agent: "codex" }, AGENTS).ready, false);
  assert.equal(linkSheet({ action: "connect", agent: "goose" }, AGENTS).detail, "Goose isn't installed on this computer.");
  assert.equal(linkSheet({ action: "connect", agent: "cursor" }, AGENTS).ready, true); // manual agents show the paste step
  assert.equal(linkSheet({ action: "connect", agent: "nope" }, AGENTS), null);
  assert.equal(linkSheet({ action: "connect", agent: "../x" }, AGENTS), null);
});

test("linkSheet: join shows the host, flags plain http and never takes a key from the link", () => {
  const s = linkSheet({ action: "join", gateway: "https://ai-gw.acme.dev" }, AGENTS);
  assert.equal(s.kind, "join");
  assert.equal(s.host, "ai-gw.acme.dev");
  assert.equal(s.insecure, false);
  assert.equal(s.url, "https://ai-gw.acme.dev");
  const plain = linkSheet({ action: "join", gateway: "http://192.168.1.20:8000" }, AGENTS);
  assert.equal(plain.insecure, true);
  assert.equal(plain.host, "192.168.1.20:8000");
  assert.equal(linkSheet({ action: "join", gateway: "http://evil.example" }, AGENTS), null); // http only on private networks
  assert.equal(linkSheet({ action: "join", gateway: "https://user:sk-secret@gw.example" }, AGENTS), null);
  assert.equal(linkSheet({ action: "join", gateway: "https://gw.example/?key=sk-orca-1" }, AGENTS), null);
  assert.equal(linkSheet({ action: "join", gateway: "javascript:alert(1)" }, AGENTS), null);
  assert.equal(linkSheet({ action: "setup", agents: ["codex"] }, AGENTS), null); // setup links belong to the setup window
  assert.equal(linkSheet(null, AGENTS), null);
});

test("setupHash asks setup to open at a step and keeps the key", () => {
  assert.equal(setupHash("#key=abc", "orcarouter"), "#key=abc&step=orcarouter");
  assert.equal(setupHash("#key=abc&step=gateway", "orcarouter"), "#key=abc&step=orcarouter");
  assert.equal(setupHash("", "gateway"), "#step=gateway");
  assert.throws(() => setupHash("", "evil"));
});
