// Connects a one-paste-step agent in the real panel at the app's window size
// and reports whether the "Finish in <agent>" card is on screen, so the user
// sees the values to paste without scrolling. Prints one JSON line.
const { chromium } = require("playwright");

const [base, key, agentName] = process.argv.slice(2);
(async () => {
  const errors = [];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 360, height: 680 } });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`${base}/desktop/panel.html#key=${key}`);
  await page.getByRole("button", { name: `Connect ${agentName}`, exact: true }).click();
  const card = page.locator("#manual");
  await card.waitFor({ state: "visible", timeout: 10000 });
  await page.waitForTimeout(600); // let any scroll settle
  const box = await card.boundingBox();
  const title = await page.locator("#manual-title").textContent();
  const onScreen = !!box && box.y >= 0 && box.y + box.height <= 680;
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByRole("button", { name: `Disconnect ${agentName}`, exact: true }).click();
  await page.waitForTimeout(500);
  await page.getByRole("button", { name: `Confirm disconnecting ${agentName}`, exact: true }).click();
  await page.getByRole("button", { name: `Connect ${agentName}`, exact: true }).waitFor({ timeout: 10000 });
  process.stdout.write(JSON.stringify({ errors, title, onScreen, box }) + "\n");
  await browser.close();
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
