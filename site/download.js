/* Which installer to offer. Pure functions only: no DOM, no network, so they
   run under `node --test` (tests/site/) as well as in the page (main.js). */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.OrcaDownload = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const REPO = "Continuum-AI-Corp/OrcaRouter-Lite";
  const RELEASES = "https://github.com/" + REPO + "/releases/latest";
  const DOWNLOADS = "https://github.com/" + REPO + "/releases/download/";

  // Asset names come from Tauri's bundler (see .github/workflows/desktop.yml):
  // "OrcaRouter Lite_<version>_<arch>.<ext>". They carry the version, so
  // releases/latest/download/<name> can't be linked without knowing it.
  const TARGETS = {
    "mac-arm": { button: "Download for Mac", detail: "Apple silicon", label: "Mac (Apple silicon)", patterns: [/_aarch64\.dmg$/] },
    "mac-intel": { button: "Download for Mac", detail: "Intel", label: "Mac (Intel)", patterns: [/_x64\.dmg$/] },
    windows: { button: "Download for Windows", detail: "64-bit", label: "Windows", patterns: [/_x64-setup\.exe$/, /_x64_[A-Za-z-]+\.msi$/] },
    "linux-deb": { button: "Download for Linux", detail: ".deb", label: "Linux (.deb)", patterns: [/_amd64\.deb$/] },
    "linux-appimage": { button: "Download for Linux", detail: "AppImage", label: "Linux (AppImage)", patterns: [/_amd64\.AppImage$/] },
  };

  /* The build that suits this browser's computer, or "mobile" / "unknown".
     `architecture` is navigator.userAgentData's high-entropy value ("arm" or
     "x86"), which only Chromium reports; every Mac browser says "MacIntel",
     so without it a Mac gets Apple silicon, what Apple has sold since 2020. */
  function detectTarget(info) {
    const o = info || {};
    const ua = String(o.userAgent || "");
    const plat = String(o.uaPlatform || o.platform || "").toLowerCase();
    const arch = String(o.architecture || "").toLowerCase();
    const touch = Number(o.maxTouchPoints || 0);

    if (/iphone|ipad|ipod|android/i.test(ua) || /iphone|ipad|android/.test(plat)) return "mobile";
    if (plat.indexOf("mac") === 0 || (!plat && /Macintosh|Mac OS X/.test(ua))) {
      if (touch > 1) return "mobile"; // iPadOS asking for the desktop site
      return arch === "x86" ? "mac-intel" : "mac-arm";
    }
    if (plat.indexOf("win") === 0 || (!plat && /Windows/.test(ua))) return "windows";
    if (plat.indexOf("linux") === 0 || plat.indexOf("chrome os") === 0 || (!plat && /Linux|X11|CrOS/.test(ua))) {
      // Releases ship x86-64 Linux builds only.
      if (/aarch64|arm/.test(plat) || /aarch64|armv/i.test(ua) || arch === "arm") return "unknown";
      return "linux-deb";
    }
    return "unknown";
  }

  /* The installer asset for `target` from a GitHub release's asset list:
     {name, url, size} or null. Only links into this repository's releases. */
  function pickAsset(assets, target) {
    const t = TARGETS[target];
    if (!t || !Array.isArray(assets)) return null;
    for (const pattern of t.patterns) {
      const hit = assets.find(function (a) {
        return a && pattern.test(String(a.name || "")) &&
          String(a.browser_download_url || "").indexOf(DOWNLOADS) === 0;
      });
      if (hit) return { name: hit.name, url: hit.browser_download_url, size: hit.size || 0 };
    }
    return null;
  }

  function formatSize(bytes) {
    const n = Number(bytes) || 0;
    if (n <= 0) return "";
    if (n >= 1024 * 1024) return Math.round(n / (1024 * 1024)) + " MB";
    return Math.max(1, Math.round(n / 1024)) + " KB";
  }

  /* What the button needs from a release (the JSON of GitHub's
     /releases/latest endpoint): {href, version, size, name} or null. */
  function describeRelease(release, target) {
    if (!release || typeof release !== "object") return null;
    const asset = pickAsset(release.assets, target);
    if (!asset) return null;
    return {
      href: asset.url,
      name: asset.name,
      version: String(release.tag_name || "").replace(/^v/, ""),
      size: formatSize(asset.size),
    };
  }

  /* Without JavaScript or before a release exists: the latest release page. */
  function fallbackUrl(target) {
    return TARGETS[target] ? RELEASES + "#" + target : RELEASES;
  }

  return { REPO: REPO, RELEASES: RELEASES, TARGETS: TARGETS, detectTarget: detectTarget, pickAsset: pickAsset,
    formatSize: formatSize, describeRelease: describeRelease, fallbackUrl: fallbackUrl };
});
