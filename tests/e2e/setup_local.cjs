// Setup with Ollama running (H6, P2): the local choices come first, the
// OrcaRouter key step sits under "Ollama first, OrcaRouter for the rest",
// and saving turns on the local-first strategy. Prints one JSON line.
const { chromium } = require("playwright");
const { stubNativeBridge, shots, waitDone } = require("./page_helpers.cjs");

const [base, key] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 600, height: 860 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(stubNativeBridge);
  // A query that changes each time: the same URL with a #fragment wouldn't reload.
  let loads = 0;
  const open = async () => {
    await page.goto(`${base}/desktop/setup.html?load=${++loads}#key=${key}`);
    await page.locator("#provider-chips .chip").first().waitFor({ state: "attached" });
  };
  // A first run (no keys yet) starts on the local choice.
  await page.route("**/v1/app/summary*", async (route) => {
    const response = await route.fetch();
    route.fulfill({ response, json: { ...(await response.json()), providers: [] } });
  });
  await open();
  report.firstRunSelected = await page.locator('input[name="route"]:checked').getAttribute("value");
  await page.unroute("**/v1/app/summary*");
  await open();
  const visible = page.locator(".choice:not([hidden])");
  report.choices = await visible.locator(".body > b").evaluateAll((els) => els.map((e) => e.firstChild.textContent.trim()));
  report.descriptions = await visible.locator(".body > small").allTextContents();
  report.selected = await page.locator('input[name="route"]:checked').getAttribute("value");
  report.page = await page.locator("body").innerText();
  await shots(page, "h6-step2", page.locator("#s2").locator(".."));
  // Keyboard: arrow keys move between the choices; the key step follows.
  await page.locator('input[name="route"][value="local_hosted"]').focus();
  await page.keyboard.press("ArrowDown");
  report.afterArrow = await page.locator('input[name="route"]:checked').getAttribute("value");
  await shots(page, "h6-only-this-computer", page.locator("#s2").locator(".."));
  await page.keyboard.press("ArrowUp");
  report.keyStepUnderLocal = await page.locator('.choice[data-route="local_hosted"] #orca-key').count() === 1;
  await shots(page, "h6-local-hosted", page.locator("#s2").locator(".."));

  const checked = page.locator('#agents input[type="checkbox"]:checked');
  while (await checked.count()) await checked.first().uncheck();
  await page.locator("#go").click();
  await waitDone(page);
  report.results = await page.locator("#results li").evaluateAll((els) => els.map((li) => `${li.querySelector("b").textContent}: ${li.querySelector("span").textContent}`));

  // Reopened, setup starts from what was chosen.
  await open();
  report.reopenedSelected = await page.locator('input[name="route"]:checked').getAttribute("value");
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
