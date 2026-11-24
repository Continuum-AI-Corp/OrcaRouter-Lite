// An orca://setup link reaching the setup window (V3): it asks first, Cancel
// and Escape change nothing, Continue ticks the linked agents and fills in
// the budget, and nothing is connected until the user clicks Connect.
// Prints one JSON line.
const { chromium } = require("playwright");
const { sendLink, stubNativeBridge, shots } = require("./page_helpers.cjs");

const [base, key] = process.argv.slice(2);
const LINK = { action: "setup", agents: ["claude-code", "codex"], budget_cents: 500 };
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 600, height: 860 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(stubNativeBridge);
  await page.goto(`${base}/desktop/setup.html#key=${key}`);
  await page.locator("#provider-chips .chip").first().waitFor({ state: "attached" });
  const ticked = () => page.locator('#agents input[type="checkbox"]:checked').evaluateAll((els) => els.map((e) => e.value));
  const budget = () => page.locator("#budget").inputValue();
  report.before = await ticked();
  report.budgetBefore = await budget();

  await sendLink(page, LINK);
  await page.locator("#link-sheet").waitFor({ state: "visible" });
  report.text = await page.locator("#link-text").textContent();
  const dialog = page.locator('[role="dialog"]');
  report.dialog = { role: await dialog.getAttribute("role"), modal: await dialog.getAttribute("aria-modal") };
  report.focused = await page.evaluate(() => document.activeElement.id);
  await shots(page, "v3-link", "viewport");
  await page.locator("#link-cancel").click();
  report.afterCancel = await ticked();
  report.budgetAfterCancel = await budget();

  await sendLink(page, LINK);
  await page.locator("#link-sheet").waitFor({ state: "visible" });
  await page.keyboard.press("Escape");
  report.escapeClosed = await page.locator("#link-sheet").isHidden();

  await sendLink(page, LINK);
  await page.locator("#link-sheet").waitFor({ state: "visible" });
  await page.locator("#link-continue").click();
  report.afterContinue = await ticked();
  report.budgetAfterContinue = await budget();
  report.button = await page.locator("#go").textContent();
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
