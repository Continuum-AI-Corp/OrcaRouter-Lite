/* Landing page wiring. The page works without this: every download link goes
   to the latest GitHub release. With it, the primary button names the
   visitor's OS and, once GitHub's API answers, links straight to the right
   installer. That API call is the only request the page makes on its own; no
   cookies, no analytics. */
(function () {
  "use strict";
  const dl = window.OrcaDownload;
  if (!dl) return;
  const $ = (id) => document.getElementById(id);

  const nav = window.navigator || {};
  const info = {
    userAgent: nav.userAgent,
    platform: nav.platform,
    uaPlatform: nav.userAgentData && nav.userAgentData.platform,
    maxTouchPoints: nav.maxTouchPoints,
    architecture: "",
  };
  let target = dl.detectTarget(info);
  let release = null;

  function render() {
    const t = dl.TARGETS[target];
    const button = $("download-primary");
    const meta = $("download-meta");
    $("download-mobile").hidden = target !== "mobile";

    document.querySelectorAll("#download-options a[data-target]").forEach((a) => {
      const id = a.dataset.target;
      const hit = dl.describeRelease(release, id);
      a.href = hit ? hit.href : dl.fallbackUrl(id);
      if (hit && hit.size) a.title = hit.name + " · " + hit.size;
      if (id === target) a.setAttribute("aria-current", "true");
      else a.removeAttribute("aria-current");
    });

    if (!t) {
      // Phones, tablets, unknown systems: keep the button pointing at the
      // release page and let the list below do the choosing.
      $("download-label").textContent = target === "mobile" ? "See all downloads" : "Download Orca";
      $("download-detail").textContent = "";
      button.href = dl.fallbackUrl(target);
      if (release && release.tag_name) meta.textContent = "Version " + String(release.tag_name).replace(/^v/, "") + " for macOS, Windows and Linux.";
      return;
    }
    $("download-label").textContent = t.button;
    $("download-detail").textContent = t.detail;
    const hit = dl.describeRelease(release, target);
    button.href = hit ? hit.href : dl.fallbackUrl(target);
    const parts = [];
    if (hit) parts.push("Version " + hit.version, hit.size);
    else parts.push("From the latest GitHub release");
    parts.push("detected from your browser");
    meta.textContent = parts.filter(Boolean).join(" · ");
  }

  render();

  // Chromium can tell an Intel Mac from Apple silicon; others can't, and
  // keep the Apple silicon default with "Mac (Intel)" one link away.
  if (nav.userAgentData && nav.userAgentData.getHighEntropyValues && target.indexOf("mac") === 0) {
    nav.userAgentData.getHighEntropyValues(["architecture"]).then((v) => {
      info.architecture = v && v.architecture;
      target = dl.detectTarget(info);
      render();
    }).catch(() => {});
  }

  if (window.fetch) {
    fetch("https://api.github.com/repos/" + dl.REPO + "/releases/latest", {
      headers: { Accept: "application/vnd.github+json" },
      credentials: "omit",
      referrerPolicy: "no-referrer",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => { release = json; render(); })
      .catch(() => {});
  }

  // Copy buttons appear only where the clipboard API exists.
  if (nav.clipboard && nav.clipboard.writeText) {
    document.querySelectorAll("button[data-copy]").forEach((btn) => {
      btn.hidden = false;
      btn.addEventListener("click", () => {
        const text = $(btn.dataset.copy).textContent.trim();
        nav.clipboard.writeText(text).then(() => {
          btn.textContent = "Copied";
          setTimeout(() => { btn.textContent = "Copy"; }, 1600);
        }).catch(() => {});
      });
    });
  }
})();
