// Drives first-run setup with "Use my own API keys": a key the provider
// rejects stops setup with the provider's answer, two keys for one provider
// are refused, and the right key goes through. Agent checkboxes are cleared
// so this only exercises provider keys. Prints one JSON line.
const { chromium } = require("playwright");

const [base, key, goodKey] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 600, height: 1000 } });
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.goto(`${base}/desktop/setup.html#key=${key}`);
  await page.locator('input[name="route"][value="byok"]').check({ force: true });
  const checked = page.locator('#agents input[type="checkbox"]:checked');
  while (await checked.count()) await checked.first().uncheck({ force: true });
  report.providers = await page.locator("#key-rows .key-row").first().locator("select option").allTextContents();

  const rows = page.locator("#key-rows .key-row");
  await rows.nth(0).locator("select").selectOption("openai");
  await rows.nth(1).locator("select").selectOption("openai");
  await rows.nth(0).locator("input").fill("sk-one");
  await rows.nth(1).locator("input").fill("sk-two");
  await page.locator("#go").click();
  await page.waitForTimeout(500);
  report.duplicate = await page.locator("#status").textContent();

  await rows.nth(1).locator(".remove").click();
  await rows.nth(0).locator("input").fill("sk-wrong-key");
  await page.locator("#go").click();
  await page.waitForFunction(() => /rejected/.test(document.querySelector("#status")?.textContent || ""), null, { timeout: 15000 });
  report.rejected = await page.locator("#status").textContent();
  report.doneAfterReject = await page.locator("#done").isVisible();

  await rows.nth(0).locator("input").fill(goodKey);
  await page.locator("#go").click();
  await page.locator("#done").waitFor({ state: "visible", timeout: 15000 });
  report.done = true;
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
