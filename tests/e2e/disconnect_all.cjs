// Clicks the panel's "Disconnect all" (twice: it asks to confirm) and waits
// for the agents to show as not connected. Prints one JSON line.
const { chromium } = require("playwright");

const [base, key] = process.argv.slice(2);
(async () => {
  const errors = [];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 360, height: 900 } });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/desktop/panel.html#key=${key}`);
  const btn = page.locator("#disconnect-all");
  await btn.waitFor({ state: "visible", timeout: 10000 });
  const label = await btn.textContent();
  await btn.click();
  await page.waitForTimeout(400);
  const armed = await btn.textContent();
  await btn.click();
  await btn.waitFor({ state: "hidden", timeout: 15000 });
  const toast = await page.locator(".toast").last().textContent();
  process.stdout.write(JSON.stringify({ errors, label, armed, toast }) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
