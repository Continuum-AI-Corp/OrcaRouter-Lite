// Drives first-run setup with "My own API keys" (P1): the providers come
// from the engine's list, the new ones marked; a key the provider rejects
// stops setup with the provider's answer; a provider with no key check
// (MiniMax) is saved without checking. Agent checkboxes are cleared so this
// only exercises provider keys. Prints one JSON line.
const { chromium } = require("playwright");
const { stubNativeBridge, shots, waitDone } = require("./page_helpers.cjs");

const [base, key, goodKey] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 600, height: 860 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(stubNativeBridge);
  await page.goto(`${base}/desktop/setup.html#key=${key}`);
  const chips = page.locator("#provider-chips .chip");
  await chips.first().waitFor({ state: "attached" });
  await page.locator('input[name="route"][value="byok"]').check({ force: true });
  const checked = page.locator('#agents input[type="checkbox"]:checked');
  while (await checked.count()) await checked.first().uncheck({ force: true });
  report.providers = await chips.evaluateAll((els) => els.map((c) => c.firstChild.textContent));
  report.newProviders = await page.locator("#provider-chips .chip.new").evaluateAll((els) => els.map((c) => c.firstChild.textContent));
  report.pressed = await page.locator('#provider-chips .chip[aria-pressed="true"]').evaluateAll((els) => els.map((c) => c.dataset.provider));
  // A returning user (here: an OpenAI key in the environment) starts with no rows.
  const pick = async (id) => {
    const chip = page.locator(`#provider-chips [data-provider="${id}"]`);
    if ((await chip.getAttribute("aria-pressed")) !== "true") await chip.click();
  };
  await pick("openai");
  report.rows = await page.locator("#key-rows .key-row label").allTextContents();
  report.placeholders = await page.locator("#key-rows .key-row input").evaluateAll((els) => els.map((i) => i.placeholder));
  report.startAtLogin = await page.locator("#start-at-login").isChecked();

  // Pick MiniMax with the keyboard; its row says it isn't checked.
  await page.locator('#provider-chips [data-provider="minimax"]').focus();
  await page.keyboard.press("Enter");
  report.focusedAfterPick = await page.evaluate(() => document.activeElement.id);
  report.minimaxNote = await page.locator('#key-rows [data-provider="minimax"] .fine').textContent();
  await shots(page, "p1-setup-providers", page.locator('.choice[data-route="byok"]'));
  // A second click on a chip takes its row away again.
  await pick("anthropic");
  report.rowsWithAnthropic = await page.locator("#key-rows .key-row label").allTextContents();
  await page.locator('#provider-chips [data-provider="anthropic"]').click();
  report.rowsAfterUnpick = await page.locator("#key-rows .key-row label").allTextContents();

  const row = (id) => page.locator(`#key-rows [data-provider="${id}"] input`);
  await row("openai").fill("sk-wrong-key");
  await page.locator("#go").click();
  await page.waitForFunction(() => /rejected/.test(document.querySelector("#status")?.textContent || ""), null, { timeout: 15000 });
  report.rejected = await page.locator("#status").textContent();
  report.doneAfterReject = await page.locator("#done").isVisible();

  await row("openai").fill(goodKey);
  await row("minimax").fill("e2e-minimax-key-0001");
  await page.locator("#go").click();
  await waitDone(page);
  report.results = await page.locator("#results li").evaluateAll((els) => els.map((li) => `${li.querySelector("b").textContent}: ${li.querySelector("span").textContent}`));
  report.done = true;
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
