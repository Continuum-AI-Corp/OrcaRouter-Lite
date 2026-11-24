// Frames for docs/launch/demo.gif. Driven by scripts/record_demo.sh:
//
//   node scripts/record_demo.cjs setup|spend|alert <base> <app key> <dir>
//       screenshots of the real setup / panel pages of a running engine
//   node scripts/record_demo.cjs compose <base> <app key> <dir>
//       lays them out on a 960x540 stage, 2 frames a second, 30 seconds:
//       Install 0:00-0:06, Connect 0:06-0:14, Spend 0:14-0:22, Alert 0:22-0:30
//
// The pages and numbers are the real app's, filled by desktop/scripts/seed_demo.py.
// Two things on the stage are drawn, because they live outside the pages: the
// "drag to Applications" step and the OS notification. The notification uses
// the app's own wording (desktop/src-tauri/src/logic.rs, Alert::BudgetWarn).
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const [phase, base, key, dir] = process.argv.slice(2);
const ROOT = path.resolve(__dirname, "..");
const png = (name) => "data:image/png;base64," + fs.readFileSync(path.join(dir, name)).toString("base64");

async function shoot(browser, url, viewport, file, after) {
  const page = await browser.newPage({ viewport, deviceScaleFactor: 2, colorScheme: "light" });
  await page.goto(url);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1200);
  if (after) await after(page);
  await page.screenshot({ path: path.join(dir, file) });
  await page.close();
}

const SCENES = [
  { id: "install", t: "0:00–0:06", title: "Install", sub: "Drag Orca to Applications. It brings its own engine: no server, no Docker.", frames: 12 },
  { id: "connect", t: "0:06–0:14", title: "Connect", sub: "Setup finds the coding agents on this computer and connects them in one click.", frames: 16 },
  { id: "spend", t: "0:14–0:22", title: "Spend", sub: "Today's total in the menu bar, split by agent.", frames: 16 },
  { id: "alert", t: "0:22–0:30", title: "Alert", sub: "A notification at 80% of the daily budget, and again at 100%.", frames: 16 },
];

function stage(scene, i, assets) {
  const steps = SCENES.map((s) => `<li class="${s.id === scene.id ? "on" : ""}">${s.title}</li>`).join("");
  const progress = Math.round(((i + 1) / scene.frames) * 100);
  let art = "";
  if (scene.id === "install") {
    const x = Math.min(1, i / (scene.frames - 4)) * 250;
    art = `<div class="drag">
        <div class="dmg"><img src="${assets.icon}" style="transform: translateX(${x}px)"><span>OrcaRouter Lite</span></div>
        <div class="arrow">→</div>
        <div class="apps"><div class="folder"></div><span>Applications</span></div>
      </div>`;
  } else if (scene.id === "connect") {
    art = `<img class="shot setup" src="${assets.setup}">`;
  } else if (scene.id === "spend") {
    art = `<div class="menubar"><span></span><b><img src="${assets.icon}">${assets.today}</b><span class="clock">9:41</span></div>
      <img class="shot panel" src="${assets.spend}">`;
  } else {
    const show = i >= 3;
    art = `<div class="menubar"><span></span><b><img src="${assets.icon}">${assets.today}</b><span class="clock">9:41</span></div>
      <img class="shot panel" src="${assets.alert}">
      <div class="note ${show ? "in" : ""}"><img src="${assets.icon}"><div><b>${assets.alertTitle}</b>
      <p>Your coding agents keep working. Open Orca to see which agent is spending.</p></div></div>`;
  }
  return `<!doctype html><html><head><style>
    * { box-sizing: border-box; margin: 0; }
    body { width: 960px; height: 540px; overflow: hidden; font: 16px/1.45 -apple-system, "Segoe UI", Inter, Roboto, Arial, sans-serif;
      color: #0A0F1C; background: linear-gradient(135deg, #EAF2FF 0%, #FFFFFF 60%); display: grid; grid-template-columns: 360px 1fr; }
    .copy { padding: 54px 20px 0 48px; display: flex; flex-direction: column; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 600; color: #1B5FCC; }
    .brand img { width: 28px; height: 28px; border-radius: 7px; }
    .t { margin-top: 56px; font: 600 14px/1 ui-monospace, Menlo, monospace; color: #5F6F86; }
    h1 { font-size: 52px; line-height: 1.05; letter-spacing: -0.02em; margin-top: 10px; }
    .sub { margin-top: 14px; font-size: 19px; color: #4A5A72; }
    ol { list-style: none; display: flex; gap: 8px; padding: 0; margin-top: auto; margin-bottom: 40px; }
    ol li { font-size: 13px; font-weight: 600; color: #8A99B2; padding: 5px 10px; border-radius: 999px; background: #EFF3F8; }
    ol li.on { color: #fff; background: #1B5FCC; }
    .bar { position: absolute; left: 0; bottom: 0; height: 4px; background: #2D7FF9; width: ${progress}%; }
    .art { position: relative; display: grid; place-items: center; padding: 28px 40px 28px 0; }
    .shot { box-shadow: 0 24px 48px -12px rgba(15,23,42,.28), 0 2px 6px rgba(15,23,42,.08); border-radius: 14px; border: 1px solid #E4E9F0; background: #fff; }
    .shot.setup { width: 520px; height: 470px; object-fit: cover; object-position: top; }
    .shot.panel { height: 430px; margin-top: 40px; }
    .menubar { position: absolute; top: 0; left: 0; right: 40px; height: 30px; display: flex; justify-content: flex-end; gap: 18px; align-items: center;
      padding: 0 14px; background: rgba(255,255,255,.85); border: 1px solid #E4E9F0; border-top: 0; border-radius: 0 0 10px 10px; font-size: 14px; }
    .menubar b { display: flex; align-items: center; gap: 6px; padding: 2px 8px; border-radius: 6px; background: #EAF2FF; }
    .menubar b img { width: 16px; height: 16px; border-radius: 4px; }
    .drag { display: flex; align-items: center; gap: 30px; background: #fff; border: 1px solid #E4E9F0; border-radius: 16px; padding: 40px 48px;
      box-shadow: 0 24px 48px -12px rgba(15,23,42,.2); }
    .dmg, .apps { display: flex; flex-direction: column; align-items: center; gap: 10px; font-size: 14px; color: #4A5A72; width: 140px; }
    .dmg img { width: 110px; height: 110px; border-radius: 24px; position: relative; z-index: 2; }
    .arrow { font-size: 40px; color: #8A99B2; }
    .folder { width: 120px; height: 96px; border-radius: 10px; background: linear-gradient(#7FB2FF, #2D7FF9); position: relative; }
    .folder::before { content: ""; position: absolute; top: -10px; left: 10px; width: 44px; height: 16px; border-radius: 6px 6px 0 0; background: #7FB2FF; }
    .note { position: absolute; top: 44px; right: 48px; width: 340px; display: flex; gap: 12px; padding: 14px 16px; border-radius: 16px;
      background: rgba(246,248,251,.97); border: 1px solid #E4E9F0; box-shadow: 0 18px 40px -10px rgba(15,23,42,.35);
      opacity: 0; transform: translateY(-14px); }
    .note.in { opacity: 1; transform: none; }
    .note img { width: 32px; height: 32px; border-radius: 8px; }
    .note b { font-size: 15px; }
    .note p { font-size: 13px; color: #4A5A72; margin-top: 2px; }
  </style></head><body>
    <div class="copy">
      <div class="brand"><img src="${assets.icon}">Orca Router Lite</div>
      <div class="t">${scene.t}</div>
      <h1>${scene.title}</h1>
      <p class="sub">${scene.sub}</p>
      <ol>${steps}</ol>
    </div>
    <div class="art">${art}</div>
    <div class="bar"></div>
  </body></html>`;
}

(async () => {
  const browser = await chromium.launch();
  try {
    if (phase === "setup") {
      await shoot(browser, `${base}/desktop/setup.html#key=${key}`, { width: 600, height: 560 }, "setup.png");
    } else if (phase === "spend" || phase === "alert") {
      await shoot(browser, `${base}/desktop/panel.html#key=${key}`, { width: 360, height: 680 }, `panel-${phase}.png`);
      const r = await fetch(`${base}/v1/app/summary`, { headers: { Authorization: `Bearer ${key}` } });
      fs.writeFileSync(path.join(dir, `summary-${phase}.json`), JSON.stringify(await r.json()));
    } else if (phase === "compose") {
      const summary = JSON.parse(fs.readFileSync(path.join(dir, "summary-alert.json"), "utf8"));
      const money = (micro) => "$" + (micro / 1_000_000).toFixed(2);
      const b = summary.budget || {};
      const assets = {
        icon: "data:image/png;base64," + fs.readFileSync(path.join(ROOT, "desktop/ui/assets/orca.png")).toString("base64"),
        setup: png("setup.png"),
        spend: png("panel-spend.png"),
        alert: png("panel-alert.png"),
        today: money(summary.today.spend_microcents),
        alertTitle: `${Math.round(b.used_percent)}% of today's $${(b.daily_cents / 100).toFixed(2)} budget used`,
      };
      const page = await browser.newPage({ viewport: { width: 960, height: 540 } });
      let n = 0;
      for (const scene of SCENES) {
        for (let i = 0; i < scene.frames; i++) {
          await page.setContent(stage(scene, i, assets));
          await page.screenshot({ path: path.join(dir, `frame-${String(n++).padStart(3, "0")}.png`) });
        }
      }
      console.log(`${n} frames`);
    } else {
      throw new Error(`unknown phase ${phase}`);
    }
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
