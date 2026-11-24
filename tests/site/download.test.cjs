// Landing-page download logic (site/download.js): which build the primary
// button offers, and which release asset each OS link points at.
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const dl = require(path.join(__dirname, "..", "..", "site", "download.js"));

const UA = {
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
  win: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
  linux: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
  linuxArm: "Mozilla/5.0 (X11; Linux aarch64; rv:132.0) Gecko/20100101 Firefox/132.0",
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
  android: "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36",
  cros: "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
};

test("a Mac defaults to Apple silicon, Intel when the browser says x86", () => {
  assert.equal(dl.detectTarget({ userAgent: UA.mac, platform: "MacIntel" }), "mac-arm");
  assert.equal(dl.detectTarget({ userAgent: UA.mac, platform: "MacIntel", architecture: "arm" }), "mac-arm");
  assert.equal(dl.detectTarget({ userAgent: UA.mac, platform: "MacIntel", architecture: "x86" }), "mac-intel");
  assert.equal(dl.detectTarget({ userAgent: UA.win, uaPlatform: "macOS", architecture: "x86" }), "mac-intel");
});

test("Windows and Linux", () => {
  assert.equal(dl.detectTarget({ userAgent: UA.win, platform: "Win32" }), "windows");
  assert.equal(dl.detectTarget({ userAgent: UA.linux, platform: "Linux x86_64" }), "linux-deb");
  assert.equal(dl.detectTarget({ userAgent: UA.cros, platform: "Linux x86_64" }), "linux-deb");
});

test("phones and tablets get no installer, and nor do ARM Linux boxes", () => {
  assert.equal(dl.detectTarget({ userAgent: UA.iphone, platform: "iPhone" }), "mobile");
  assert.equal(dl.detectTarget({ userAgent: UA.android, platform: "Linux armv8l" }), "mobile");
  // iPadOS asks for the desktop site and claims to be a Mac; touch gives it away.
  assert.equal(dl.detectTarget({ userAgent: UA.mac, platform: "MacIntel", maxTouchPoints: 5 }), "mobile");
  assert.equal(dl.detectTarget({ userAgent: UA.linuxArm, platform: "Linux aarch64" }), "unknown");
  assert.equal(dl.detectTarget({}), "unknown");
});

const v = "0.2.0";
const ASSETS = [
  `OrcaRouter Lite_${v}_aarch64.dmg`,
  `OrcaRouter Lite_${v}_x64.dmg`,
  `OrcaRouter Lite_${v}_aarch64.app.tar.gz`,
  `OrcaRouter Lite_${v}_aarch64.app.tar.gz.sig`,
  `OrcaRouter Lite_${v}_x64_en-US.msi`,
  `OrcaRouter Lite_${v}_x64-setup.exe`,
  `OrcaRouter Lite_${v}_x64-setup.exe.sig`,
  `OrcaRouter Lite_${v}_amd64.deb`,
  `OrcaRouter Lite_${v}_amd64.AppImage`,
  `OrcaRouter Lite_${v}_amd64.AppImage.sig`,
  "latest.json",
  "orcarouter-lite.rb",
].map((name, i) => ({
  name,
  size: (i + 1) * 1024 * 1024,
  browser_download_url: `https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/download/v${v}/${encodeURIComponent(name)}`,
}));

test("each target maps to its installer, never an update bundle or signature", () => {
  const pick = (t) => dl.pickAsset(ASSETS, t)?.name;
  assert.equal(pick("mac-arm"), `OrcaRouter Lite_${v}_aarch64.dmg`);
  assert.equal(pick("mac-intel"), `OrcaRouter Lite_${v}_x64.dmg`);
  assert.equal(pick("windows"), `OrcaRouter Lite_${v}_x64-setup.exe`);
  assert.equal(pick("linux-deb"), `OrcaRouter Lite_${v}_amd64.deb`);
  assert.equal(pick("linux-appimage"), `OrcaRouter Lite_${v}_amd64.AppImage`);
  assert.equal(pick("mobile"), undefined);
  assert.equal(dl.pickAsset([], "windows"), null);
  assert.equal(dl.pickAsset(undefined, "windows"), null);
});

test("Windows falls back to the .msi when there is no setup .exe", () => {
  const msiOnly = ASSETS.filter((a) => !a.name.endsWith("-setup.exe"));
  assert.equal(dl.pickAsset(msiOnly, "windows").name, `OrcaRouter Lite_${v}_x64_en-US.msi`);
});

test("a release resolves to direct links with version and size", () => {
  const r = dl.describeRelease({ tag_name: `v${v}`, assets: ASSETS }, "mac-arm");
  assert.equal(r.version, v);
  assert.equal(r.href, ASSETS[0].browser_download_url);
  assert.equal(r.size, "1 MB");
  assert.equal(dl.describeRelease({ tag_name: "v0.2.0", assets: [] }, "mac-arm"), null);
  assert.equal(dl.describeRelease(null, "mac-arm"), null);
});

test("download links only ever point at this repository's releases", () => {
  const evil = [{ name: `OrcaRouter Lite_${v}_aarch64.dmg`, size: 1, browser_download_url: "https://evil.example/x.dmg" }];
  assert.equal(dl.pickAsset(evil, "mac-arm"), null);
});

test("fallback links go to the latest release page", () => {
  assert.equal(dl.fallbackUrl("windows"), "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest#windows");
  assert.equal(dl.fallbackUrl("mobile"), "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest");
});

test("sizes read like a person wrote them", () => {
  assert.equal(dl.formatSize(109 * 1024 * 1024), "109 MB");
  assert.equal(dl.formatSize(1536), "2 KB");
  assert.equal(dl.formatSize(0), "");
  assert.equal(dl.formatSize(undefined), "");
});

test("button labels", () => {
  assert.equal(dl.TARGETS["mac-arm"].button, "Download for Mac");
  assert.equal(dl.TARGETS["mac-arm"].detail, "Apple silicon");
  assert.equal(dl.TARGETS.windows.button, "Download for Windows");
  assert.equal(dl.TARGETS["linux-deb"].button, "Download for Linux");
});
