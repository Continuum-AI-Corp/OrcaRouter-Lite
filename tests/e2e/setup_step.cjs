// Setup opened by the panel at a step ("Join" → the company gateway,
// "Add OrcaRouter backup" → OrcaRouter's key): the right choice is selected,
// the request is used once, and an old request is ignored. Prints one JSON line.
const { chromium } = require("playwright");
const { stubNativeBridge } = require("./page_helpers.cjs");

const [base, key] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 600, height: 860 } });
  const page = await context.newPage();
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(stubNativeBridge);
  const checked = () => page.evaluate(() => document.querySelector('input[name="route"]:checked')?.value);
  const load = async (hash) => {
    // A new document each time (a fragment-only change wouldn't reload).
    await page.goto("about:blank");
    await page.goto(`${base}/desktop/setup.html#key=${key}${hash}`);
    await page.locator("#provider-chips .chip").first().waitFor({ state: "attached" });
  };

  await load("&step=gateway");
  report.fromHash = await checked();
  // Used once: the step leaves the URL, so a reload starts as usual.
  report.hashAfter = await page.evaluate(() => location.hash);
  report.keyKept = report.hashAfter === `#key=${key}`;
  // Fields of choices that aren't selected are out of the tab order.
  report.gatewayInertWhenSelected = await page.evaluate(() => Boolean(document.querySelector("#gateway-url").closest("[inert]")));
  await page.locator('input[name="route"][value="byok"]').check({ force: true });
  report.gatewayInertWhenNot = await page.evaluate(() => Boolean(document.querySelector("#gateway-url").closest("[inert]")));
  report.chipsInertWhenSelected = await page.evaluate(() => Boolean(document.querySelector("#provider-chips").closest("[inert]")));

  await page.evaluate(() => localStorage.setItem("orca-setup-step", JSON.stringify({ step: "gateway", at: Date.now() })));
  await load("");
  report.fromStorage = await checked();
  report.storageLeft = await page.evaluate(() => localStorage.getItem("orca-setup-step"));
  await load("");
  report.nextOpen = await checked();

  await page.evaluate(() => localStorage.setItem("orca-setup-step", JSON.stringify({ step: "gateway", at: Date.now() - 600000 })));
  await load("");
  report.stale = await checked();

  // Setup already open: the panel's request arrives as a storage change
  // (the app only focuses the window). Played here by a second page of the
  // same origin, as the panel is.
  const panel = await context.newPage();
  await panel.goto(`${base}/desktop/panel.html#key=${key}`);
  await panel.evaluate(() => localStorage.setItem("orca-setup-step", JSON.stringify({ step: "gateway", at: Date.now() })));
  await page.waitForFunction(() => document.querySelector('input[name="route"]:checked')?.value === "company", null, { timeout: 5000 })
    .catch(() => {});
  report.whileOpen = await checked();
  report.whileOpenLeft = await page.evaluate(() => localStorage.getItem("orca-setup-step"));

  await browser.close();
  process.stdout.write(JSON.stringify(report) + "\n");
})().catch((e) => {
  process.stderr.write(String(e.stack || e));
  process.exit(1);
});
