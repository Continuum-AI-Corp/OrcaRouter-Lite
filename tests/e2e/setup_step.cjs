// Setup opened by the panel at a step ("Join" → the company gateway,
// "Add OrcaRouter backup" → OrcaRouter's key): the right choice is selected,
// the request is used once, and an old request is ignored. Prints one JSON line.
const { chromium } = require("playwright");
const { stubNativeBridge } = require("./page_helpers.cjs");

const [base, key] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 600, height: 860 } });
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

  await page.evaluate(() => localStorage.setItem("orca-setup-step", JSON.stringify({ step: "gateway", at: Date.now() })));
  await load("");
  report.fromStorage = await checked();
  report.storageLeft = await page.evaluate(() => localStorage.getItem("orca-setup-step"));
  await load("");
  report.nextOpen = await checked();

  await page.evaluate(() => localStorage.setItem("orca-setup-step", JSON.stringify({ step: "gateway", at: Date.now() - 600000 })));
  await load("");
  report.stale = await checked();

  await browser.close();
  process.stdout.write(JSON.stringify(report) + "\n");
})().catch((e) => {
  process.stderr.write(String(e.stack || e));
  process.exit(1);
});
