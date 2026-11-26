// The dashboard as the desktop app opens it (the app key in localStorage,
// like the app's window does): the Quality tab points to Orca's Settings
// (D7) where a server would say .env; the Providers tab lists the engine's
// providers (P1); the OrcaRouter card's links carry the dashboard's ref (H0).
// Prints one JSON line.
const { chromium } = require("playwright");
const { shots } = require("./page_helpers.cjs");

const [base, key] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
  await context.addInitScript((k) => localStorage.setItem("orca-lite-api-key", k), key);
  const page = await context.newPage();
  page.on("pageerror", (e) => report.errors.push(e.message));

  const qualitySteps = async (query = "") => {
    await page.goto(`${base}/${query}#quality`);
    const card = page.locator("#quality-setup-card");
    await card.waitFor({ state: "visible", timeout: 15000 });
    await page.waitForFunction(() => [...document.querySelectorAll("#quality-setup-card [data-mode]")].some((el) => !el.hidden));
    return card.locator("ol:not([hidden])").innerText();
  };
  report.desktopSteps = await qualitySteps();
  await shots(page, "d7-quality-desktop", page.locator("#quality-setup-card"));

  await page.goto(`${base}/#providers`);
  await page.locator("#provider-quickadd .chip").first().waitFor({ timeout: 15000 });
  report.options = await page.locator("#provider-name option").evaluateAll((els) => els.map((o) => o.value));
  report.newChips = await page.locator("#provider-quickadd .chip.new").evaluateAll((els) =>
    els.map((c) => c.firstChild.textContent.trim()));
  await page.locator('#provider-quickadd [data-prov-pick="moonshot"]').click();
  report.moonshotPlaceholder = await page.locator("#provider-key").getAttribute("placeholder");
  await shots(page, "p1-dashboard-providers", page.locator("#provider-form").locator(".."));

  await page.goto(`${base}/#overview`);
  await page.locator("#hosted-card").waitFor({ state: "visible", timeout: 15000 });
  await page.waitForFunction(() => document.querySelector("#hosted-signup-btn").getAttribute("href") !== "#");
  report.hostedLinks = await page.locator("#hosted-signup-btn, #hosted-register-link, #providers-hosted-signup")
    .evaluateAll((els) => els.map((a) => a.href));
  // With OrcaRouter's key saved (the setup tests did), the card says what's ready.
  const hostedActive = async () => {
    await page.locator("#hosted-active").waitFor({ state: "visible", timeout: 15000 });
    await page.waitForFunction(() => !document.querySelector("#hosted-active-meta").hidden || !document.querySelector("#hosted-ready-desktop").hidden);
    return page.locator("#hosted-active").innerText();
  };
  report.hostedActive = await hostedActive();
  await shots(page, "h0-dashboard-hosted-active", page.locator("#hosted-card"));

  // A server's engine has no /v1/app: the same tab keeps its .env steps.
  await page.route("**/v1/app/benchmark-key", (route) => route.fulfill({ status: 404, body: "{}" }));
  report.serverSteps = await qualitySteps("?server"); // a fresh page load
  await page.goto(`${base}/?server2#overview`);
  report.serverHostedActive = await hostedActive();
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
