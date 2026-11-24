// Drives the panel's roadmap features in Chromium against a running engine.
// One scenario per run; prints one JSON report line for the Python test.
//   node panel_features.cjs <base> <app key> <scenario>
// Scenarios: agent, offer, credit, local, share, links, settings.
const { chromium } = require("playwright");

const [base, key, scenario] = process.argv.slice(2);
const T = { timeout: 30000 };

// Outgoing links open through window.open in a plain browser; record them
// instead of navigating to the internet.
async function recordLinks(page) {
  await page.evaluate(() => {
    window.__opened = [];
    window.open = (url) => {
      window.__opened.push(String(url));
      return null;
    };
  });
}

const opened = (page) => page.evaluate(() => window.__opened);
const lastToast = (page) => page.locator(".toast:not(.leaving)").last();

async function waitToast(page, text) {
  try {
    await page.locator(".toast:not(.leaving)", { hasText: text }).last().waitFor(T);
  } catch (err) {
    const seen = await page.locator(".toast").allTextContents();
    throw new Error(`${err.message}\nToasts on screen: ${JSON.stringify(seen)}`);
  }
  return (await lastToast(page).textContent()).trim();
}

const appFetch = (page, method, path, body) =>
  page.evaluate(
    async ([m, p, b, k]) => {
      const r = await fetch(p, { method: m, headers: { Authorization: `Bearer ${k}`, "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
      return r.json();
    },
    [method, path, body, key],
  );

const sendLink = (page, detail) => page.evaluate((d) => window.dispatchEvent(new CustomEvent("orca-link", { detail: d })), detail);

const scenarios = {
  // D2, D3, D4, D5, H3: the agent sheet, a connect with its automatic test, Reconnect.
  async agent(page, report) {
    // D5: Codex's settings were replaced; its row offers Reconnect.
    await page.getByRole("button", { name: "Reconnect Codex", exact: true }).click(T);
    report.reconnectToast = await waitToast(page, /Codex reconnected.*(Works\.|test failed)/);
    await page.getByRole("button", { name: "Disconnect Codex", exact: true }).waitFor(T);
    // D4: Connect runs the test right after.
    await page.getByRole("button", { name: "Connect OpenCode", exact: true }).click();
    report.connectToast = await waitToast(page, /OpenCode connected.*(Works\.|test failed)/);

    await page.locator('li[data-id="claude-code"] .nm-btn').click();
    await page.locator(".as-head").waitFor(T);
    report.hint = await page.locator(".as-state .note.info p").textContent(T);
    await page.locator(".reqs .req").first().waitFor(T);
    report.requests = await page.locator(".reqs .req").count();
    report.firstRequest = (await page.locator(".reqs .req").first().textContent()).trim();

    await page.getByRole("button", { name: "Test", exact: true }).click();
    await page.locator(".as-test-result:not([hidden])").waitFor(T);
    report.test = (await page.locator(".as-test-result").textContent()).trim();

    await page.locator("#as-budget-amount").fill("5");
    await page.locator("#as-budget-amount").press("Enter"); // a typed amount turns the budget on
    await page.locator(".as-budget .fine", { hasText: "Saved." }).waitFor(T);
    report.budgetStatus = await page.locator(".as-budget .fine").textContent();

    await page.locator(".pick-btn").first().click();
    await page.locator(".picker:not([hidden]) .pick-search").fill("gpt-4o-mini");
    report.pickerGroups = await page.locator(".picker:not([hidden]) .pick-group").allTextContents();
    await page.keyboard.press("Escape"); // closes, nothing chosen
    report.pickerClosedByEscape = await page.locator(".picker").first().isHidden();
    await page.locator(".pick-btn").first().click();
    await page.locator(".picker:not([hidden]) .pick-search").fill("gpt-4o-mini");
    await page.locator(".picker:not([hidden]) .pick-opt b.mono", { hasText: /^gpt-4o-mini$/ }).first().click();
    await page.locator(".as-models .fine", { hasText: "Saved." }).waitFor(T);
    report.mainShown = (await page.locator(".pick-btn .pick-val").first().textContent()).trim();
    await page.locator("#as-fallback").uncheck();
    await page.waitForTimeout(600);

    // An OrcaRouter model without an OrcaRouter key explains what's needed.
    await page.locator(".pick-btn").nth(1).click();
    await page.locator(".picker:not([hidden]) .pick-search").fill("free");
    await page.locator(".picker:not([hidden]) .pick-opt.off.active").waitFor(T); // the first match is active
    await page.keyboard.press("Enter"); // choosing it explains what it needs
    report.needsKey = (await page.locator(".picker:not([hidden]) .pick-note").textContent()).trim();
    await page.keyboard.press("Escape");

    await page.locator('[data-act="sub-keep"]').focus();
    await page.keyboard.press("Enter");
    await page.locator(".as-state .note.info").waitFor({ state: "detached", ...T });
    report.focusAfterKeep = await page.evaluate(() => document.activeElement?.id);

    await page.getByRole("button", { name: "Back", exact: true }).click();
    await page.locator("#agents").waitFor(T);
    report.backOnHome = await page.locator("#home").isVisible();
  },

  // D4: a failed Test reads as words (never "null"); Disconnect from the
  // sheet leaves focus on the agent list.
  async testfail(page, report) {
    await page.locator('li[data-id="opencode"] .nm-btn').click();
    await page.locator(".as-head").waitFor(T);
    await page.getByRole("button", { name: "Test", exact: true }).click();
    await page.locator(".as-test-result:not([hidden])").waitFor(T);
    report.test = (await page.locator(".as-test-result").textContent()).trim();
    report.testTone = await page.locator(".as-test-result").getAttribute("class");
    const btn = page.locator('[data-act="sheet-disconnect"]');
    await btn.click();
    await page.waitForTimeout(500); // past the double-click guard
    await btn.click();
    await page.locator("#home").waitFor({ state: "visible", ...T });
    await page.waitForTimeout(300);
    report.focusAfterDisconnect = await page.evaluate(() => document.activeElement?.id);
  },

  // H0: the paid-models switch under OrcaRouter and in Settings.
  async paid(page, report) {
    const sw = page.locator('#providers [role="switch"]');
    await sw.waitFor(T);
    report.before = { checked: await sw.getAttribute("aria-checked"), text: (await sw.textContent()).trim() };
    await sw.click();
    report.confirm = (await page.locator("#providers .confirm-box p").textContent()).trim();
    report.focusOnConfirm = await page.evaluate(() => document.activeElement?.textContent);
    await page.locator("#providers .confirm-box").getByRole("button", { name: "Use paid models" }).click();
    await page.locator('#providers [role="switch"][aria-checked="true"]').waitFor(T);
    report.afterOn = (await appFetch(page, "GET", "/v1/app/settings")).hosted_models;
    await page.locator("#open-settings").click();
    const set = page.locator('.view-body [role="switch"]');
    await set.waitFor(T);
    report.settingsState = (await set.textContent()).trim();
    report.settingsText = (await page.locator(".view-body .paid-switch .fine").textContent()).trim();
    await set.click(); // off needs no confirmation
    await page.locator('.view-body [role="switch"][aria-checked="false"]').waitFor(T);
    report.afterOff = (await appFetch(page, "GET", "/v1/app/settings")).hosted_models;
    report.retriesLabel = await page.locator('label[for="set-retries"]').textContent();
  },

  // H2: the backup offer after failures with no fallback, and Not now.
  async offer(page, report) {
    await page.locator("#offer").waitFor({ state: "visible", ...T });
    report.lead = await page.locator("#offer-lead").textContent();
    report.rest = await page.locator("#offer-rest").textContent();
    report.body = await page.locator("#offer-body").textContent();
    await page.getByRole("button", { name: "Add OrcaRouter backup" }).click();
    await page.waitForURL(/setup\.html/, T);
    report.setupUrlHash = new URL(page.url()).hash;
    report.stepRequest = JSON.parse(await page.evaluate(() => localStorage.getItem("orca-setup-step")));
    report.hostedModelsAfterAdd = (await appFetch(page, "GET", "/v1/app/settings")).hosted_models;
    await page.goto(`${base}/desktop/panel.html#key=${key}`);
    await page.locator("#offer").waitFor({ state: "visible", ...T });
    await page.getByRole("button", { name: "Not now" }).click();
    await page.locator("#offer").waitFor({ state: "hidden", ...T });
    await page.waitForTimeout(800); // the save and the refresh after it
    report.hiddenAfterReload = await (async () => {
      await page.reload();
      await page.locator("#agents li").first().waitFor(T);
      await page.waitForTimeout(500);
      return page.locator("#offer").isHidden();
    })();
  },

  // H4: OrcaRouter's month in Providers and the out-of-credit banner.
  async credit(page, report) {
    await page.locator("#credit").waitFor({ state: "visible", ...T });
    report.banner = (await page.locator("#credit").textContent()).replace(/\s+/g, " ").trim();
    const row = page.locator('#providers li[data-id="orcarouter"]');
    report.providerRow = (await row.textContent()).replace(/\s+/g, " ").trim();
    report.firstProvider = await page.locator("#providers li").first().getAttribute("data-id");
    await recordLinks(page);
    await page.getByRole("button", { name: /Add credit/ }).click();
    report.opened = await opened(page);
  },

  // P2 · D1: models on this computer, with a fake Ollama started by the test.
  async local(page, report) {
    await page.locator("#local-refresh").click();
    const box = page.locator('input[data-model="ollama/qwen3-coder:30b"]');
    await box.waitFor(T);
    report.runtime = (await page.locator("#local-list .rt").first().textContent()).replace(/\s+/g, " ").trim();
    report.checked = await box.isChecked();
    await box.uncheck();
    await page.waitForTimeout(800);
    report.afterOff = (await appFetch(page, "GET", "/v1/app/settings")).local_models;
    await box.check();
    await page.waitForTimeout(800);
    report.afterOn = (await appFetch(page, "GET", "/v1/app/settings")).local_models;
  },

  // V2, H7, V3: the savings card, the weekly report, Share my setup.
  async share(page, report) {
    await recordLinks(page);
    await page.locator("#share-open").click();
    await page.locator("#card-copy").waitFor(T);
    await page.waitForTimeout(300);
    report.alt = await page.locator(".card-canvas").getAttribute("aria-label");
    report.painted = await page.evaluate(() => {
      const c = document.querySelector(".card-canvas");
      const px = c.getContext("2d").getImageData(10, 10, 1, 1).data;
      return { w: c.width, h: c.height, alpha: px[3], blue: px[2] };
    });
    await page.locator("#card-copy").click();
    report.copyToast = await waitToast(page, "Image copied");
    report.clipboardTypes = await page.evaluate(async () => (await navigator.clipboard.read()).flatMap((i) => i.types));
    await page.locator("#card-x").click();
    await page.locator("#card-linkedin").click();
    report.opened = await opened(page);
    await page.getByRole("button", { name: "Back", exact: true }).click();

    await page.locator("#report-copy").click();
    report.reportToast = await waitToast(page, "Report copied");
    report.markdown = await page.evaluate(() => navigator.clipboard.readText());
    await page.locator("#report-csv").click();
    report.csvToast = await waitToast(page, "Report saved");
    await page.locator("#share-setup").click();
    report.setupToast = await waitToast(page, "Link copied");
    report.setupLink = await page.evaluate(() => navigator.clipboard.readText());
  },

  // V3: orca:// links only ever open a confirmation.
  async links(page, report) {
    await sendLink(page, { action: "connect", agent: "gemini-cli" });
    await page.locator("#link-modal").waitFor({ state: "visible", ...T });
    report.connectTitle = await page.locator("#link-title").textContent();
    report.focusOnCancel = await page.evaluate(() => document.activeElement?.id);
    await sendLink(page, { action: "join", gateway: "https://gw.example.dev" }); // waits its turn
    await page.waitForTimeout(200);
    report.titleWhileQueued = await page.locator("#link-title").textContent();
    await page.getByRole("button", { name: "Cancel" }).click();
    await page.locator("#link-title", { hasText: "Join a team gateway" }).waitFor(T);
    report.queuedHost = await page.locator("#link-host").textContent();
    await page.keyboard.press("Escape");
    await page.locator("#link-modal").waitFor({ state: "hidden", ...T });
    report.focusAfterSheets = await page.evaluate(() => document.activeElement?.tagName);
    await page.waitForTimeout(300);
    report.connectedAfterCancel = (await appFetch(page, "GET", "/v1/app/agents")).agents.find((a) => a.id === "gemini-cli").connected;

    await sendLink(page, { action: "connect", agent: "gemini-cli" });
    await page.locator("#link-modal").waitFor({ state: "visible", ...T });
    await page.locator("#link-confirm").click();
    report.connectToast = await waitToast(page, /Gemini CLI connected.*(Works\.|test failed)/);
    report.connectedAfterConfirm = (await appFetch(page, "GET", "/v1/app/agents")).agents.find((a) => a.id === "gemini-cli").connected;

    await sendLink(page, { action: "join", gateway: "http://192.168.1.20:8000" });
    await page.locator("#link-modal").waitFor({ state: "visible", ...T });
    report.joinTitle = await page.locator("#link-title").textContent();
    report.joinHost = await page.locator("#link-host").textContent();
    report.notEncrypted = await page.locator("#link-insecure").isVisible();
    report.keyField = await page.locator("#link-key").inputValue();
    await page.locator("#link-confirm").click(); // no key yet: asks for it
    report.keyHelp = await page.locator("#link-key-help").textContent();
    await page.keyboard.press("Escape");
    await page.locator("#link-modal").waitFor({ state: "hidden", ...T });

    // Links that try to carry a key, or plain http to the internet, are ignored.
    await sendLink(page, { action: "join", gateway: "https://gw.example/?key=sk-orca-leak" });
    await sendLink(page, { action: "join", gateway: "http://gw.example" });
    await sendLink(page, { action: "connect", agent: "../../etc" });
    await page.waitForTimeout(400);
    report.ignoredBadLinks = await page.locator("#link-modal").isHidden();
    report.gatewayAfter = (await appFetch(page, "GET", "/v1/app/summary")).gateway;
  },

  // D7: the Artificial Analysis key, retries and rest time.
  async settings(page, report) {
    await page.locator("#open-settings").click();
    await page.locator("#aa-key").waitFor(T);
    await page.locator("#aa-key").fill("aa-e2e-test-key-0003f2");
    await page.locator(".aa-form button").click();
    await page.locator(".aa-shown").waitFor(T);
    report.keyShown = (await page.locator(".aa-shown").textContent()).trim();
    report.keyStatus = await appFetch(page, "GET", "/v1/app/benchmark-key");
    await page.locator("#set-retries").fill("9");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    report.badRetries = await page.locator(".router-form .fine").textContent();
    await page.locator("#set-retries").fill("2");
    await page.locator("#set-cooldown").fill("60");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await page.locator(".router-form .fine", { hasText: "Saved." }).waitFor(T);
    report.routerStatus = await page.locator(".router-form .fine").textContent();
    const s = await appFetch(page, "GET", "/v1/app/settings");
    report.saved = { retries: s.router_num_retries, cooldown: s.router_cooldown_seconds };
    await page.locator("#aa-clear").click();
    await page.locator("#aa-key").waitFor(T);
    report.keyAfterRemove = await appFetch(page, "GET", "/v1/app/benchmark-key");
    report.focusAfterRemove = await page.evaluate(() => document.activeElement?.id);
    await page.getByRole("button", { name: "Back", exact: true }).click();
    report.panelCollapsed = await page.evaluate(() => getComputedStyle(document.getElementById("budget-input")).visibility);
    await page.locator("#budget-edit").click();
    await page.waitForTimeout(400);
    report.panelOpened = await page.evaluate(() => getComputedStyle(document.getElementById("budget-input")).visibility);
    await page.goto(`${base}/desktop/setup.html#key=${key}`);
    await page.locator(".collapse").first().waitFor({ state: "attached", ...T });
    await page.waitForTimeout(500);
    report.setupCollapses = await page.evaluate(() =>
      [...document.querySelectorAll(".collapse")].map((c) => ({
        open: getComputedStyle(c).gridTemplateRows !== "0px",
        visibility: getComputedStyle(c).visibility,
      })),
    );
  },
};

(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 360, height: 900 } });
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: base });
  const page = await context.newPage();
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.goto(`${base}/desktop/panel.html#key=${key}`);
  await page.locator("#agents li").first().waitFor(T);
  await scenarios[scenario](page, report);
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => {
  process.stderr.write(String((e && e.stack) || e));
  process.exit(1);
});
