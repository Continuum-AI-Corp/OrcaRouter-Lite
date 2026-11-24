// Setup's step 2 with OrcaRouter first (H0), then an OrcaRouter key found on
// the clipboard when the window regains focus (H1), then the done screen's
// README badge (V6). The native bridge is played by the page
// (page_helpers.cjs). Prints one JSON line.
const { chromium } = require("playwright");
const { stubNativeBridge, shots, waitDone } = require("./page_helpers.cjs");

const [base, key, goodKey, otherKey] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 600, height: 860 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: base });
  const page = await context.newPage();
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(stubNativeBridge);
  // A first run: no provider has a key yet (this engine has an OpenAI key in
  // its environment, which would make setup start from "My own API keys").
  await page.route("**/v1/app/summary*", async (route) => {
    const response = await route.fetch();
    route.fulfill({ response, json: { ...(await response.json()), providers: [] } });
  });
  await page.goto(`${base}/desktop/setup.html#key=${key}`);
  await page.locator("#provider-chips .chip").first().waitFor({ state: "attached" });

  const visible = page.locator(".choice:not([hidden])");
  report.choices = await visible.locator(".body > b").evaluateAll((els) => els.map((e) => e.firstChild.textContent.trim()));
  report.descriptions = await visible.locator(".body > small").allTextContents();
  report.pill = await page.locator('.choice[data-route="hosted"] .pill').textContent();
  report.selected = await page.locator('input[name="route"]:checked').getAttribute("value");
  report.page = await page.locator("body").innerText();
  await shots(page, "h0-step2", page.locator("#s2").locator(".."));

  await page.locator("#get-key").click();
  report.opened = await page.evaluate(() => window.__native.opened);

  const focus = () => page.evaluate(() => window.dispatchEvent(new Event("focus")));
  const offerShown = () => page.locator("#clip-offer").isVisible();
  // Something that isn't a key is ignored.
  await page.evaluate(() => (window.__clip = "notes I copied"));
  await focus();
  await page.waitForTimeout(200);
  report.offerForText = await offerShown();
  // A key on the clipboard is offered only when the window regains focus...
  await page.evaluate((k) => (window.__clip = k), otherKey);
  await page.waitForTimeout(300);
  report.offerBeforeFocus = await offerShown();
  await focus();
  await page.locator("#clip-offer").waitFor();
  report.offerText = await page.locator("#clip-offer-text").innerText();
  await shots(page, "h1-offer", page.locator('.choice[data-route="hosted"]'));
  // ...and once: "No" leaves the clipboard alone and doesn't ask again.
  await page.locator("#clip-no").click();
  report.offerAfterNo = await offerShown();
  await focus();
  await page.waitForTimeout(300);
  report.offerAgain = await offerShown();
  report.clearedAfterNo = await page.evaluate(() => window.__native.cleared);
  report.clipAfterNo = await page.evaluate(() => window.__clip);

  // A new key: use it. It's checked with OrcaRouter, saved, the clipboard cleared.
  await page.evaluate((k) => (window.__clip = k), goodKey);
  await focus();
  await page.locator("#clip-offer").waitFor();
  report.secondOffer = await page.locator("#clip-offer-text").innerText();
  await page.locator("#clip-use").click();
  await page.locator("#key-saved").waitFor({ timeout: 15000 });
  report.saved = await page.locator("#key-saved").innerText();
  report.cleared = await page.evaluate(() => window.__native.cleared);
  report.pasteStillThere = await page.locator("#hosted-key").count();
  await shots(page, "h1-saved", page.locator('.choice[data-route="hosted"]'));

  // Finish without connecting agents; the done screen shows the badge.
  const checked = page.locator('#agents input[type="checkbox"]:checked');
  while (await checked.count()) await checked.first().uncheck();
  await page.locator("#go").click();
  await waitDone(page);
  report.results = await page.locator("#results li").evaluateAll((els) => els.map((li) => `${li.querySelector("b").textContent}: ${li.querySelector("span").textContent}`));
  report.badge = await page.locator("#badge-md").textContent();
  await page.locator("#badge-copy").click();
  await page.waitForFunction(() => document.querySelector("#badge-copy").textContent !== "Copy");
  report.copyLabel = await page.locator("#badge-copy").textContent();
  report.copied = await page.evaluate(() => navigator.clipboard.readText());
  await shots(page, "v6-done");
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
