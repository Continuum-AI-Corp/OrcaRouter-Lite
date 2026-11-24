// Drives the real panel in Chromium against a running engine:
// connect an agent with its button, then disconnect it (two clicks: the
// panel asks to confirm). Prints a JSON report for the Python test.
const { chromium } = require("playwright");

const [base, key, agentName] = process.argv.slice(2);
(async () => {
const report = { errors: [], steps: [] };
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 360, height: 900 } });
page.on("pageerror", (e) => report.errors.push(e.message));
await page.goto(`${base}/desktop/panel.html#key=${key}`);
await page.getByRole("button", { name: `Connect ${agentName}`, exact: true }).click();
await page.getByRole("button", { name: `Disconnect ${agentName}`, exact: true }).waitFor({ timeout: 10000 });
report.steps.push("connected");
await new Promise((r) => process.stdout.write(JSON.stringify({ ...report, phase: "connected" }) + "\n", r));
// Wait for the test to inspect the config, then disconnect.
await new Promise((r) => process.stdin.once("data", r));
await page.getByRole("button", { name: `Disconnect ${agentName}`, exact: true }).click();
await page.waitForTimeout(500); // past the double-click guard
await page.getByRole("button", { name: `Confirm disconnecting ${agentName}`, exact: true }).click();
await page.getByRole("button", { name: `Connect ${agentName}`, exact: true }).waitFor({ timeout: 10000 });
report.steps.push("disconnected");
process.stdout.write(JSON.stringify({ ...report, phase: "disconnected" }) + "\n");
await browser.close();
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
