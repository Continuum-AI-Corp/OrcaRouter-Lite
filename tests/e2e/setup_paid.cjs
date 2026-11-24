// "Add OrcaRouter backup" in the panel opens setup at OrcaRouter's key with
// `then: "paid"`: once a key is saved (from the clipboard or pasted), paid
// models are turned on as a backup and setup says so. Without the request
// nothing about paid models changes. Prints one JSON line.
const { chromium } = require("playwright");
const { stubNativeBridge, shots, waitDone } = require("./page_helpers.cjs");

const [base, key, orcaKey] = process.argv.slice(2);
(async () => {
  const report = { errors: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 600, height: 860 }, deviceScaleFactor: 2, reducedMotion: "reduce" });
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(stubNativeBridge);
  let loads = 0;
  const open = async (hash = "") => {
    await page.goto(`${base}/desktop/setup.html?load=${++loads}#key=${key}${hash}`);
    await page.locator("#provider-chips .chip").first().waitFor({ state: "attached" });
  };
  const hostedModels = () => page.evaluate(async (k) => {
    const r = await fetch("/v1/app/settings", { headers: { Authorization: `Bearer ${k}` } });
    return (await r.json()).hosted_models;
  }, key);
  const setHostedModels = (value) => page.evaluate(async ([k, v]) => {
    await fetch("/v1/app/settings", { method: "PUT", headers: { Authorization: `Bearer ${k}`, "Content-Type": "application/json" },
      body: JSON.stringify({ hosted_models: v }) });
  }, [key, value]);
  report.before = await (async () => { await open(); return hostedModels(); })();

  // 1. From the browser's #step=orcarouter&then=paid; the key comes from the clipboard.
  await open("&step=orcarouter&then=paid");
  report.selected = await page.locator('input[name="route"]:checked').getAttribute("value");
  await page.evaluate((k) => (window.__clip = k), orcaKey);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.locator("#clip-use").click();
  await page.locator("#key-saved").waitFor({ timeout: 15000 });
  report.saved = await page.locator("#key-saved").innerText();
  report.afterClipboard = await hostedModels();
  await shots(page, "h2-paid-backup-saved", page.locator('.choice[data-route="hosted"]'));
  await setHostedModels("free");

  // 2. From the stored request the native panel leaves; the key is pasted.
  await page.evaluate(() => localStorage.setItem("orca-setup-step", JSON.stringify({ step: "orcarouter", at: Date.now(), then: "paid" })));
  await open();
  await page.locator("#hosted-key").fill(orcaKey);
  const checked = page.locator('#agents input[type="checkbox"]:checked');
  while (await checked.count()) await checked.first().uncheck();
  await page.locator("#go").click();
  await waitDone(page);
  report.results = await page.locator("#results li").evaluateAll((els) => els.map((li) => `${li.querySelector("b").textContent}: ${li.querySelector("span").textContent}`));
  report.afterPaste = await hostedModels();
  await setHostedModels("free");

  // 3. Without the request, saving a key leaves paid models off.
  await open("&step=orcarouter");
  await page.locator("#hosted-key").fill(orcaKey);
  while (await checked.count()) await checked.first().uncheck();
  await page.locator("#go").click();
  await waitDone(page);
  report.withoutRequest = await hostedModels();
  report.resultsWithout = await page.locator("#results li").evaluateAll((els) => els.map((li) => li.querySelector("b").textContent));
  process.stdout.write(JSON.stringify(report) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
