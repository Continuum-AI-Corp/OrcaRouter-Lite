/* ==========================================================================
   OrcaRouter Lite — dashboard
   Vanilla JS, no build step. State -> render. Keyboard-first DX.
   ========================================================================== */

const KEY_STORAGE = "orca-lite-api-key";
const ONBOARDING_KEY = "orca-lite-getting-started-dismissed";
const PROVIDERS_KNOWN = [
  { id: "openai",      label: "OpenAI"      },
  { id: "anthropic",   label: "Anthropic"   },
  { id: "google",      label: "Google"      },
  { id: "groq",        label: "Groq"        },
  { id: "together",    label: "Together"    },
  { id: "fireworks",   label: "Fireworks"   },
  { id: "orcarouter",  label: "OrcaRouter (hosted)" },
];
const TAB_META = {
  overview:  { title: "Overview",     sub: "Your single-tenant LLM router at a glance." },
  providers: { title: "Provider keys", sub: "BYOK — encrypted at rest, used to call upstream LLMs." },
  routing:   { title: "Routing",      sub: "How model='auto' picks the right model for each request." },
  analytics: { title: "Analytics",    sub: "Local-only spend, latency and request history." },
  keys:      { title: "API keys",     sub: "Tokens that authenticate clients against this Lite workspace." },
};

const state = {
  apiKey: localStorage.getItem(KEY_STORAGE) || "",
  tab: "overview",
  providers: [],
  routing: { strategy: "balanced", preferred_models: [] },
  recent: [],
  spend: { total_microcents: 0, by_model: [] },
  latency: { by_provider: [] },
  savings: { saved_microcents: 0, savings_percent: 0, hosted_auto: null },
  models: [],
  hosted: { configured: false, source: null, signup_url: "https://www.orcarouter.ai/register", provider_name: "orcarouter" },
  unreachable: { hosted_configured: false, unreachable: [] },
  windowDays: 7,
  lang: "python",
};

/* ─────────────── tiny utils ─────────────── */
const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const fmtUsd = (mc) => {
  const usd = (mc || 0) / 1_000_000;
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1)    return `$${usd.toFixed(3)}`;
  if (usd < 100)  return `$${usd.toFixed(2)}`;
  return `$${Math.round(usd).toLocaleString()}`;
};
const fmtNum = (n) => (n || 0).toLocaleString();
const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now - d;
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60)   return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

const escapeHtml = (s = "") =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;" }[c]));

// Mirror of app/routes/analytics.py:_percentile — same nearest-rank
// algorithm, including Python's banker's rounding (round-half-to-even)
// for .5 ties so client-derived percentiles match the backend
// bit-for-bit on the same sample.
function bankersRound(x) {
  const floor = Math.floor(x);
  const diff = x - floor;
  if (diff < 0.5) return floor;
  if (diff > 0.5) return floor + 1;
  return floor % 2 === 0 ? floor : floor + 1;
}
function percentile(values, pct) {
  if (!values.length) return 0;
  const s = [...values].sort((a, b) => a - b);
  const idx = Math.max(0, Math.min(s.length - 1, bankersRound((s.length - 1) * pct)));
  return Math.round(s[idx]);
}

/* ─────────────── HTTP ─────────────── */
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (state.apiKey) headers["Authorization"] = `Bearer ${state.apiKey}`;
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 204) return null;
  let body = null;
  try { body = await r.json(); } catch { /* ignore */ }
  if (!r.ok) {
    const msg = body?.error?.message || body?.detail || r.statusText || "Request failed";
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return body;
}

/* ─────────────── toasts ─────────────── */
const TOAST_ICONS = {
  ok:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
  err:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  info: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
};
function toast(msg, kind = "ok", ms = 2400) {
  const region = $("#toast-region");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<span class="ico">${TOAST_ICONS[kind] || TOAST_ICONS.info}</span><span>${escapeHtml(msg)}</span>`;
  region.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 220);
  }, ms);
}

/* ─────────────── clipboard ─────────────── */
async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      btn.classList.add("copied");
      setTimeout(() => btn.classList.remove("copied"), 1200);
    }
    toast("Copied to clipboard", "info", 1400);
    return true;
  } catch {
    toast("Could not copy — your browser blocked it", "err");
    return false;
  }
}

/* ==========================================================================
   AUTH
   ========================================================================== */
async function checkAuth() {
  if (!state.apiKey) return false;
  try {
    await api("/v1/keys");
    return true;
  } catch {
    return false;
  }
}

function showShell() {
  $("#auth-gate").hidden = true;
  $("#app-shell").hidden = false;
  pollHealth();
  // fire-and-forget — render once data arrives
  Promise.allSettled([
    loadProviders(),
    loadRouting(),
    loadAnalytics(),
    loadKeys(),
    loadModels(),
    loadHosted(),
    loadUnreachable(),
  ]).then(() => {
    renderProviders();
    renderRouting();
    renderAnalytics();
    renderKeys();
    renderOverview();
    renderQuickstart();
    renderHostedCard();
    renderUnreachable();
    syncOnboarding();
  });
}

function showGate() {
  $("#app-shell").hidden = true;
  $("#auth-gate").hidden = false;
  $("#api-key-input").focus();
}

/* ==========================================================================
   TABS / ROUTING
   ========================================================================== */
function setTab(tab) {
  if (!TAB_META[tab]) return;
  state.tab = tab;
  history.replaceState(null, "", `#${tab}`);
  $$("#tabs .nav-item").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".panel").forEach((p) => p.classList.remove("active"));
  $(`#panel-${tab}`).classList.add("active");
  $("#page-title").textContent = TAB_META[tab].title;
  $("#page-sub").textContent = TAB_META[tab].sub;
  // refresh the tab's data so it's fresh-on-view
  if (tab === "analytics") loadAnalytics().then(renderAnalytics);
  if (tab === "providers") {
    Promise.all([loadProviders(), loadHosted(), loadUnreachable()]).then(() => {
      renderProviders();
      renderHostedCard();
      renderUnreachable();
    });
  }
  if (tab === "keys")      loadKeys().then(renderKeys);
  if (tab === "overview")  {
    Promise.all([loadHosted(), loadUnreachable()]).then(() => {
      renderOverview();
      renderHostedCard();
      renderUnreachable();
    });
  }
}

function bindTabs() {
  $$("#tabs .nav-item").forEach((b) =>
    b.addEventListener("click", () => setTab(b.dataset.tab))
  );
  // Inline anchor "go to tab" links
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-go-tab]");
    if (t) {
      e.preventDefault();
      setTab(t.dataset.goTab);
    }
  });
  // Initial tab from hash
  const initial = (location.hash || "").replace("#", "");
  if (TAB_META[initial]) setTab(initial);
}

/* ==========================================================================
   PROVIDERS
   ========================================================================== */
async function loadProviders() {
  try {
    const data = await api("/v1/providers");
    state.providers = data.providers || [];
  } catch (e) {
    toast(`Couldn't load providers: ${e.message}`, "err");
  }
}

function renderProviders() {
  const tbody = $("#providers-table tbody");
  const empty = $("#providers-empty");
  tbody.innerHTML = "";
  if (!state.providers.length) {
    empty.classList.add("shown");
  } else {
    empty.classList.remove("shown");
    state.providers.forEach((p) => {
      const tr = document.createElement("tr");
      tr.className = "row-in";
      tr.innerHTML = `
        <td><strong>${escapeHtml(p.provider)}</strong></td>
        <td><code>${escapeHtml(p.key_prefix || "—")}</code></td>
        <td>${p.is_enabled
          ? '<span class="pill ok">Enabled</span>'
          : '<span class="pill muted">Disabled</span>'}</td>
        <td class="th-actions">
          <button class="btn btn-ghost btn-sm btn-danger del-prov" data-prov="${escapeHtml(p.provider)}">
            Remove
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    $$(".del-prov").forEach((b) =>
      b.addEventListener("click", async () => {
        const prov = b.dataset.prov;
        if (!confirm(`Remove the ${prov} key? Requests routed to ${prov} will start failing.`)) return;
        try {
          await api(`/v1/providers/${prov}`, { method: "DELETE" });
          toast(`Removed ${prov}`, "ok");
          await Promise.all([loadProviders(), loadHosted(), loadUnreachable()]);
          renderProviders();
          renderQuickAdd();
          renderHostedCard();
          renderUnreachable();
          renderOverview();
          syncOnboarding();
        } catch (e) {
          toast(e.message, "err");
        }
      })
    );
  }
  renderQuickAdd();
}

function renderQuickAdd() {
  const wrap = $("#provider-quickadd");
  if (!wrap) return;
  const configured = new Set(state.providers.map((p) => p.provider));
  wrap.innerHTML = `<span class="muted" style="font-size:12px;align-self:center;margin-right:4px">Quick-add:</span>` +
    PROVIDERS_KNOWN.map((p) => {
      const isSet = configured.has(p.id);
      return `<button class="chip ${isSet ? "configured" : ""}" data-prov-pick="${p.id}" ${isSet ? "disabled" : ""}>
        ${escapeHtml(p.label)}
      </button>`;
    }).join("");
  $$("[data-prov-pick]").forEach((b) =>
    b.addEventListener("click", () => {
      const sel = $("#provider-name");
      sel.value = b.dataset.provPick;
      $("#provider-key").focus();
    })
  );
}

function bindProviderForm() {
  $("#provider-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const provider = $("#provider-name").value;
    const apiKeyVal = $("#provider-key").value.trim();
    if (!apiKeyVal) {
      toast("API key cannot be empty", "err");
      return;
    }
    try {
      await api(`/v1/providers/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKeyVal }),
      });
      $("#provider-key").value = "";
      toast(`Saved ${provider} key`, "ok");
      await Promise.all([loadProviders(), loadHosted(), loadUnreachable()]);
      renderProviders();
      renderHostedCard();
      renderUnreachable();
      renderOverview();
      syncOnboarding();
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

/* ==========================================================================
   ROUTING
   ========================================================================== */
async function loadRouting() {
  try {
    const r = await api("/v1/routing");
    state.routing = r;
  } catch (e) {
    toast(`Couldn't load routing: ${e.message}`, "err");
  }
}

function renderRouting() {
  $$(".strategy-card").forEach((c) => {
    const selected = c.dataset.value === state.routing.strategy;
    c.classList.toggle("selected", selected);
    const input = c.querySelector("input");
    if (input) input.checked = selected;
  });
}

function bindRouting() {
  $$(".strategy-card").forEach((c) => {
    c.addEventListener("click", async (e) => {
      e.preventDefault();
      const val = c.dataset.value;
      if (val === state.routing.strategy) return;
      const prev = state.routing.strategy;
      state.routing.strategy = val;
      renderRouting();
      try {
        await api("/v1/routing", { method: "PUT", body: JSON.stringify({ strategy: val }) });
        toast(`Routing strategy: ${val}`, "ok");
        syncOnboarding();
      } catch (err) {
        state.routing.strategy = prev;
        renderRouting();
        toast(err.message, "err");
      }
    });
  });
}

/* ==========================================================================
   ANALYTICS
   ========================================================================== */
async function loadAnalytics() {
  const days = state.windowDays;
  try {
    const [recent, spend, latency, savings] = await Promise.all([
      api(`/v1/analytics/recent?limit=50`),
      api(`/v1/analytics/spend?days=${days}`),
      api(`/v1/analytics/latency?days=${days}`),
      api(`/v1/analytics/savings?days=${days}&baseline=gpt-4o`).catch(() => null),
    ]);
    state.recent = recent.items || [];
    state.spend = spend;
    state.latency = latency;
    if (savings) state.savings = savings;
  } catch (e) {
    toast(`Couldn't load analytics: ${e.message}`, "err");
  }
}

/* ==========================================================================
   HOSTED FALLBACK + UNREACHABLE MODELS
   ========================================================================== */
async function loadHosted() {
  try {
    state.hosted = await api(`/v1/hosted`);
  } catch {
    // Non-fatal — card just stays in unconfigured state.
  }
}

async function loadUnreachable() {
  try {
    state.unreachable = await api(`/v1/analytics/unreachable?limit=8`);
  } catch {
    state.unreachable = { hosted_configured: false, unreachable: [] };
  }
}

function fmtPerMtok(perToken) {
  // litellm prices are USD per token; show as $/1M tokens.
  const perMillion = (perToken || 0) * 1_000_000;
  if (perMillion === 0) return "—";
  if (perMillion < 1) return `$${perMillion.toFixed(2)}`;
  return `$${perMillion.toFixed(2)}`;
}

function renderHostedCard() {
  const card = $("#hosted-card");
  if (!card) return;
  card.hidden = false;

  const pill = $("#hosted-status-pill");
  const cta = $("#hosted-cta");
  const active = $("#hosted-active");
  const signupBtn = $("#hosted-signup-btn");
  const providersPill = $("#providers-hosted-pill");
  const providersSignup = $("#providers-hosted-signup");
  const providersCard = $("#providers-hosted-card");

  const url = state.hosted.signup_url || "https://www.orcarouter.ai/register";
  if (signupBtn) signupBtn.href = url;
  if (providersSignup) providersSignup.href = url;

  if (state.hosted.configured) {
    pill.textContent = "Active";
    pill.className = "pill ok";
    cta.hidden = true;
    active.hidden = false;
    if (providersPill) { providersPill.textContent = "Active"; providersPill.className = "pill ok"; }
    if (providersCard) providersCard.hidden = true;

    // Hosted-active state: source line + extra savings projection.
    // Three branches: no comparable history yet, additional savings
    // detected, or already optimal (history exists but routing matches
    // the cheapest hosted-auto pick on every comparable request).
    const isEnv = state.hosted.source === "env";
    const ha = state.savings.hosted_auto;
    let haText;
    if (!ha || ha.comparable_request_count === 0) {
      haText = `No comparable request history yet — once traffic flows, this card will show how much routing through hosted-auto would save.`;
    } else if (ha.saved_microcents > 0) {
      // savings_percent is computed against comparable spend only (rows
      // resolved to a catalog model), not total spend — keep the copy
      // honest so non-catalog traffic doesn't make the figure misleading.
      haText = `Up to <strong>${fmtUsd(ha.saved_microcents)}</strong> additional savings detected (${ha.savings_percent}% of comparable-traffic spend) by routing through hosted-auto on the cheapest catalog model per request.`;
    } else {
      haText = `Already optimal — your current routing matches the cheapest hosted-auto pick on every comparable request.`;
    }
    $("#hosted-active-meta").innerHTML = isEnv
      ? `Active via environment variable (<code>ORCAROUTER_API_KEY</code>). Every catalog model is reachable. To disable, unset the env var and restart.`
      : `Active via dashboard. Every catalog model is reachable.`;
    $("#hosted-savings").innerHTML = haText;
    // The Remove button DELETEs the DB row; with no DB row (env-only) it
    // would 404. Hide it and let the meta line explain how to disable.
    const removeBtn = $("#hosted-remove-btn");
    if (removeBtn) removeBtn.hidden = isEnv;
  } else {
    pill.textContent = "Not configured";
    pill.className = "pill muted";
    cta.hidden = false;
    active.hidden = true;
    if (providersPill) { providersPill.textContent = "Not configured"; providersPill.className = "pill muted"; }
    if (providersCard) providersCard.hidden = false;
  }
}

function renderUnreachable() {
  const wrap = $("#unreachable-list");
  const grid = $("#unreachable-grid");
  if (!wrap || !grid) return;
  const list = state.unreachable.unreachable || [];
  if (state.hosted.configured || list.length === 0) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  grid.innerHTML = list.map((m) => {
    const caps = [];
    if (m.supports_tools) caps.push("tools");
    if (m.supports_vision) caps.push("vision");
    if (m.supports_json_mode) caps.push("json");
    const capPills = caps.map((c) => `<span class="cap-pill">${c}</span>`).join("");
    return `
      <div class="unreachable-item" data-tooltip="Provider: ${escapeHtml(m.provider)} · ${fmtPerMtok(m.input_cost_per_token)}/$1M in · ${fmtPerMtok(m.output_cost_per_token)}/$1M out">
        <div class="unreachable-id"><code>${escapeHtml(m.id)}</code></div>
        <div class="unreachable-meta">
          <span class="unreachable-provider">${escapeHtml(m.provider)}</span>
          <span class="unreachable-price">${fmtPerMtok(m.input_cost_per_token)} / ${fmtPerMtok(m.output_cost_per_token)} per 1M</span>
        </div>
        <div class="unreachable-caps">${capPills}</div>
      </div>`;
  }).join("");
}

function bindHostedForm() {
  const form = $("#hosted-key-form");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = $("#hosted-key-input").value.trim();
      if (!v) { toast("Paste your sk-orca-* key from orcarouter.ai", "err"); return; }
      try {
        await api(`/v1/providers/orcarouter`, {
          method: "PUT",
          body: JSON.stringify({ api_key: v }),
        });
        $("#hosted-key-input").value = "";
        toast("Hosted fallback activated — every model is now reachable", "ok");
        await Promise.all([loadHosted(), loadUnreachable(), loadProviders()]);
        renderHostedCard();
        renderUnreachable();
        renderProviders();
        renderOverview();
      } catch (err) {
        toast(err.message, "err");
      }
    });
  }
  const remove = $("#hosted-remove-btn");
  if (remove) {
    remove.addEventListener("click", async () => {
      if (!confirm("Disable hosted fallback? Requests for models without a local key will start failing.")) return;
      try {
        await api(`/v1/providers/orcarouter`, { method: "DELETE" });
        toast("Hosted fallback disabled", "info");
        await Promise.all([loadHosted(), loadUnreachable(), loadProviders()]);
        renderHostedCard();
        renderUnreachable();
        renderProviders();
        renderOverview();
      } catch (err) {
        toast(err.message, "err");
      }
    });
  }
}

function renderAnalytics() {
  // Spend summary
  const totalReq = state.spend.by_model.reduce((a, m) => a + m.request_count, 0);
  $("#spend-summary").innerHTML =
    `Last <strong>${state.spend.days || state.windowDays}d</strong> · ` +
    `<strong>${fmtUsd(state.spend.total_microcents)}</strong> across ` +
    `<strong>${fmtNum(totalReq)}</strong> requests`;

  // Bar chart
  const chart = $("#bar-chart");
  if (!state.spend.by_model.length) {
    chart.innerHTML = `<div class="empty-mini">
      <p>No spend data yet for this window.</p>
      <p class="muted">Send a request through <code>/v1/chat/completions</code> to see your costs here.</p>
    </div>`;
  } else {
    const max = Math.max(...state.spend.by_model.map((m) => m.cost_microcents)) || 1;
    chart.innerHTML = state.spend.by_model.slice(0, 10).map((m) => {
      const pct = Math.max(2, (m.cost_microcents / max) * 100);
      return `
        <div class="bar-row" data-tooltip="${fmtNum(m.request_count)} requests, ${fmtUsd(m.cost_microcents)}">
          <div class="bar-label">${escapeHtml(m.model || "—")}</div>
          <div class="bar-track"><div class="bar-fill" style="right:${100 - pct}%"></div></div>
          <div class="bar-value">${fmtUsd(m.cost_microcents)} <span class="reqs">${fmtNum(m.request_count)} req</span></div>
        </div>`;
    }).join("");
  }

  // Latency table
  const lt = $("#latency-table tbody");
  if (!state.latency.by_provider.length) {
    lt.innerHTML = `<tr><td colspan="4" class="muted" style="text-align:center;padding:24px">No data yet for this window.</td></tr>`;
  } else {
    lt.innerHTML = state.latency.by_provider.map((p) => `
      <tr class="row-in">
        <td><strong>${escapeHtml(p.provider)}</strong></td>
        <td>${fmtNum(p.request_count)}</td>
        <td>${fmtNum(p.p50_ms)} ms</td>
        <td>${fmtNum(p.p99_ms)} ms</td>
      </tr>
    `).join("");
  }

  // Recent table
  const rt = $("#recent-table tbody");
  const rEmpty = $("#recent-empty");
  if (!state.recent.length) {
    rt.innerHTML = "";
    rEmpty.hidden = false;
    rEmpty.classList.add("shown");
  } else {
    rEmpty.hidden = true;
    rEmpty.classList.remove("shown");
    rt.innerHTML = state.recent.map((it) => {
      const ok = (it.status_code || 0) < 400;
      const pillCls = ok ? "ok" : "err";
      const pillTxt = ok ? `${it.status_code} OK` : `${it.status_code} ${it.error_type || "error"}`;
      return `
        <tr class="row-in copy-row" data-trace="${escapeHtml(it.trace_id || "")}" data-tooltip="Click to copy trace ID">
          <td>${fmtTime(it.created_at)}</td>
          <td><code>${escapeHtml(it.model_resolved || it.model_requested || "—")}</code></td>
          <td>${escapeHtml(it.provider || "—")}</td>
          <td>${fmtNum(it.input_tokens)} / ${fmtNum(it.output_tokens)}</td>
          <td>${fmtNum(it.latency_ms)} ms</td>
          <td><span class="pill ${pillCls}">${escapeHtml(pillTxt)}</span></td>
        </tr>`;
    }).join("");
    $$(".copy-row").forEach((row) =>
      row.addEventListener("click", () => {
        const tid = row.dataset.trace;
        if (tid) copyToClipboard(tid);
      })
    );
  }
}

function bindWindowSeg() {
  $$("#window-seg .seg-btn").forEach((b) =>
    b.addEventListener("click", async () => {
      $$("#window-seg .seg-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.windowDays = parseInt(b.dataset.days, 10);
      await loadAnalytics();
      renderAnalytics();
      renderOverview();
    })
  );
}

/* ==========================================================================
   KEYS
   ========================================================================== */
async function loadKeys() {
  try {
    const data = await api("/v1/keys");
    state.keys = data.keys || [];
  } catch (e) {
    toast(`Couldn't load keys: ${e.message}`, "err");
  }
}

function renderKeys() {
  const tbody = $("#keys-table tbody");
  tbody.innerHTML = "";
  if (!state.keys || !state.keys.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted" style="text-align:center;padding:24px">
      No keys yet. Create one above.
    </td></tr>`;
    return;
  }
  state.keys.forEach((k) => {
    const tr = document.createElement("tr");
    tr.className = "row-in";
    tr.innerHTML = `
      <td><strong>${escapeHtml(k.name)}</strong></td>
      <td><code>${escapeHtml(k.key_prefix)}</code></td>
      <td>${k.is_active ? '<span class="pill ok">Active</span>' : '<span class="pill muted">Revoked</span>'}</td>
      <td>${k.last_used_at ? fmtTime(k.last_used_at) : '<span class="muted">Never</span>'}</td>
      <td class="th-actions">
        ${k.is_active
          ? `<button class="btn btn-ghost btn-sm btn-danger rev-key" data-id="${escapeHtml(k.id)}" data-name="${escapeHtml(k.name)}">Revoke</button>`
          : ""}
      </td>
    `;
    tbody.appendChild(tr);
  });
  $$(".rev-key").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm(`Revoke "${b.dataset.name}"? Any client using it will start getting 401 immediately.`)) return;
      try {
        await api(`/v1/keys/${b.dataset.id}`, { method: "DELETE" });
        toast(`Revoked ${b.dataset.name}`, "ok");
        await loadKeys();
        renderKeys();
      } catch (e) {
        toast(e.message, "err");
      }
    })
  );
}

function bindKeyForm() {
  $("#key-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("#key-name").value.trim();
    if (!name) { toast("Give the key a name first", "err"); return; }
    try {
      const r = await api("/v1/keys", { method: "POST", body: JSON.stringify({ name }) });
      $("#key-name").value = "";
      const display = $("#new-key-display");
      $("#new-key-value").textContent = r.api_key;
      display.hidden = false;
      $("#new-key-copy").onclick = (ev) => copyToClipboard(r.api_key, ev.currentTarget);
      toast(`Created ${name}`, "ok");
      await loadKeys();
      renderKeys();
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

/* ==========================================================================
   MODELS
   ========================================================================== */
async function loadModels() {
  try {
    const data = await api("/v1/models");
    state.models = data.data || [];
  } catch (e) {
    // Non-fatal — overview just shows "—".
    state.models = [];
  }
}

/* ==========================================================================
   OVERVIEW
   ========================================================================== */
function renderOverview() {
  // KPI cards
  const totalReq = (state.spend.by_model || []).reduce((a, m) => a + m.request_count, 0);
  $("#kpi-spend").textContent = fmtUsd(state.spend.total_microcents);
  $("#kpi-spend-sub").textContent = `across ${fmtNum(totalReq)} requests`;
  $("#kpi-saved").textContent = fmtUsd(state.savings.saved_microcents || 0);
  $("#kpi-saved-sub").textContent =
    state.savings.savings_percent
      ? `vs always-GPT-4o (${state.savings.savings_percent}% off)`
      : "vs always-GPT-4o baseline";

  // Second row: what hosted-auto could save on top of current routing.
  const hostedAuto = state.savings.hosted_auto;
  const haEl = $("#kpi-hosted-auto-value");
  if (haEl) {
    if (hostedAuto && hostedAuto.saved_microcents > 0) {
      haEl.textContent = `+${fmtUsd(hostedAuto.saved_microcents)} (${hostedAuto.savings_percent}%)`;
    } else if (hostedAuto && hostedAuto.comparable_request_count > 0) {
      haEl.textContent = "already optimal";
    } else {
      haEl.textContent = "—";
    }
  }

  // True p50/p99 across raw request samples — averaging per-provider
  // percentiles is the "median of medians" trap. The /v1/analytics/latency
  // endpoint only exposes pre-aggregated per-provider values, so we derive
  // global percentiles from the raw latency_ms in /v1/analytics/recent
  // (already loaded into state.recent), using the same algorithm as the
  // backend's _percentile() in app/routes/analytics.py.
  const rawLat = (state.recent || [])
    .map((r) => r.latency_ms)
    .filter((n) => Number.isFinite(n) && n >= 0);
  const p50 = percentile(rawLat, 0.5);
  const p99 = percentile(rawLat, 0.99);
  $("#kpi-p50").textContent = rawLat.length ? `${fmtNum(p50)} ms` : "— ms";
  $("#kpi-p99").textContent = rawLat.length ? `p99 ${fmtNum(p99)} ms` : "p99 — ms";

  $("#kpi-models").textContent = state.models.length ? fmtNum(state.models.length) : "—";
  $("#kpi-providers").textContent = `${state.providers.length} provider${state.providers.length === 1 ? "" : "s"} configured`;

  // Recent mini
  const mini = $("#overview-recent");
  if (!state.recent.length) {
    mini.innerHTML = `<div class="empty-mini">
      <p>No requests yet.</p>
      <p class="muted">Once you send your first <code>chat.completions</code> call, it'll show up here.</p>
    </div>`;
  } else {
    mini.innerHTML = state.recent.slice(0, 5).map((it) => {
      const ok = (it.status_code || 0) < 400;
      return `
        <div class="recent-row">
          <span class="recent-when">${fmtTime(it.created_at)}</span>
          <span class="recent-model">${escapeHtml(it.model_resolved || "—")}</span>
          <span class="recent-latency">${fmtNum(it.latency_ms)} ms</span>
          <span class="pill ${ok ? "ok" : "err"}">${ok ? "OK" : it.status_code}</span>
        </div>`;
    }).join("");
  }
}

/* ─────────────── quickstart snippet ─────────────── */
function snippetFor(lang, baseUrl, key) {
  const k = key && key.startsWith("sk-orca-") ? key : "sk-orca-...";
  if (lang === "node") {
    return `import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "${baseUrl}",
  apiKey:  "${k}",
});

const r = await client.chat.completions.create({
  model: "auto",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(r.choices[0].message.content);`;
  }
  if (lang === "curl") {
    return `curl ${baseUrl}/chat/completions \\
  -H "Authorization: Bearer ${k}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "auto",
    "messages": [{"role":"user","content":"Hello!"}]
  }'`;
  }
  return `from openai import OpenAI

client = OpenAI(
    base_url="${baseUrl}",
    api_key="${k}",
)

r = client.chat.completions.create(
    model="auto",  # or "gpt-4o-mini", "claude-3-5-sonnet-latest", ...
    messages=[{"role": "user", "content": "Hello!"}],
)
print(r.choices[0].message.content)`;
}

function renderQuickstart() {
  const baseUrl = `${location.origin}/v1`;
  $("#base-url-code").textContent = baseUrl;
  $("#help-base-url").textContent = baseUrl;
  $("#quickstart-code").textContent = snippetFor(state.lang, baseUrl, state.apiKey);
}

function bindQuickstart() {
  $$("#lang-seg .seg-btn").forEach((b) =>
    b.addEventListener("click", () => {
      $$("#lang-seg .seg-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.lang = b.dataset.lang;
      renderQuickstart();
    })
  );
  $("#copy-snippet").addEventListener("click", (e) => {
    copyToClipboard($("#quickstart-code").textContent, e.currentTarget);
  });
  $("#copy-base-url").addEventListener("click", () => {
    copyToClipboard(`${location.origin}/v1`);
  });
}

/* ─────────────── onboarding checklist ─────────────── */
function syncOnboarding() {
  const banner = $("#getting-started");
  if (!banner) return;
  if (localStorage.getItem(ONBOARDING_KEY) === "1") {
    banner.classList.add("dismissed");
    return;
  }
  const step1 = state.providers.length > 0;
  const step2 = !!state.routing.strategy;
  const step3 = state.recent.length > 0;
  $("#step-1").classList.toggle("done", step1);
  $("#step-2").classList.toggle("done", step2);
  $("#step-3").classList.toggle("done", step3);
  if (step1 && step2 && step3) {
    setTimeout(() => {
      banner.classList.add("dismissed");
      localStorage.setItem(ONBOARDING_KEY, "1");
    }, 1800);
  }
}

function bindOnboarding() {
  $("#dismiss-getting-started").addEventListener("click", () => {
    localStorage.setItem(ONBOARDING_KEY, "1");
    $("#getting-started").classList.add("dismissed");
  });
}

/* ==========================================================================
   HEALTH POLLING
   ========================================================================== */
async function pollHealth() {
  const dot = $("#health-dot");
  const txt = $("#health-text");
  async function tick() {
    try {
      await api("/health");
      dot.classList.remove("err"); dot.classList.add("ok");
      txt.textContent = "Connected";
    } catch {
      dot.classList.remove("ok"); dot.classList.add("err");
      txt.textContent = "Disconnected";
    }
  }
  await tick();
  setInterval(tick, 15_000);
}

/* ==========================================================================
   HELP DRAWER
   ========================================================================== */
function openHelp() {
  $("#help-drawer").hidden = false;
  $("#scrim").hidden = false;
}
function closeHelp() {
  const d = $("#help-drawer");
  d.hidden = true;
  $("#scrim").hidden = true;
}
function bindHelp() {
  $("#open-help").addEventListener("click", openHelp);
  $("#close-help").addEventListener("click", closeHelp);
  $("#scrim").addEventListener("click", () => {
    closeHelp();
  });
}

/* ==========================================================================
   COMMAND PALETTE
   ========================================================================== */
function paletteCommands() {
  return [
    { id: "go-overview",  title: "Go to Overview",       meta: "Tab",  hint: "1",  do: () => setTab("overview")  },
    { id: "go-providers", title: "Go to Providers",      meta: "Tab",  hint: "2",  do: () => setTab("providers") },
    { id: "go-routing",   title: "Go to Routing",        meta: "Tab",  hint: "3",  do: () => setTab("routing")   },
    { id: "go-analytics", title: "Go to Analytics",      meta: "Tab",  hint: "4",  do: () => setTab("analytics") },
    { id: "go-keys",      title: "Go to API keys",       meta: "Tab",  hint: "5",  do: () => setTab("keys")      },
    { id: "copy-base",    title: "Copy base URL",        meta: "Action", hint: "", do: () => copyToClipboard(`${location.origin}/v1`) },
    { id: "copy-snip",    title: "Copy quickstart snippet", meta: "Action", hint: "", do: () => copyToClipboard($("#quickstart-code").textContent) },
    { id: "open-help",    title: "Open help & docs",     meta: "Help", hint: "?",  do: () => openHelp() },
    { id: "open-docs",    title: "Open docs.orcarouter.ai", meta: "Link", hint: "↗", do: () => window.open("https://docs.orcarouter.ai/introduction", "_blank") },
    { id: "open-site",    title: "Open orcarouter.ai",   meta: "Link", hint: "↗",  do: () => window.open("https://www.orcarouter.ai", "_blank") },
    { id: "logout",       title: "Sign out (forget API key)", meta: "Action", hint: "", do: () => logout() },
  ];
}

let paletteFocus = 0;

function openPalette() {
  $("#palette").hidden = false;
  $("#palette-input").value = "";
  paletteFocus = 0;
  renderPalette("");
  setTimeout(() => $("#palette-input").focus(), 10);
}
function closePalette() { $("#palette").hidden = true; }

function renderPalette(query) {
  const q = query.trim().toLowerCase();
  const all = paletteCommands();
  const items = q ? all.filter((c) => c.title.toLowerCase().includes(q)) : all;
  const list = $("#palette-list");
  if (!items.length) {
    list.innerHTML = `<li class="palette-empty">No matches</li>`;
    return;
  }
  list.innerHTML = items.map((c, i) => `
    <li class="palette-item ${i === paletteFocus ? "focused" : ""}" data-id="${c.id}">
      <span>${escapeHtml(c.title)}</span>
      <span class="meta">${escapeHtml(c.hint || c.meta)}</span>
    </li>
  `).join("");
  $$("#palette-list .palette-item").forEach((el) =>
    el.addEventListener("click", () => {
      const cmd = items.find((c) => c.id === el.dataset.id);
      if (cmd) { closePalette(); cmd.do(); }
    })
  );
}

function bindPalette() {
  $("#open-palette").addEventListener("click", openPalette);
  $("#palette-close").addEventListener("click", closePalette);
  const input = $("#palette-input");
  input.addEventListener("input", () => { paletteFocus = 0; renderPalette(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
      return;
    }
    const visible = $$("#palette-list .palette-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      paletteFocus = Math.min(visible.length - 1, paletteFocus + 1);
      renderPalette(input.value);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      paletteFocus = Math.max(0, paletteFocus - 1);
      renderPalette(input.value);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const focused = visible[paletteFocus];
      if (focused) {
        const all = paletteCommands();
        const q = input.value.trim().toLowerCase();
        const items = q ? all.filter((c) => c.title.toLowerCase().includes(q)) : all;
        const cmd = items.find((c) => c.id === focused.dataset.id);
        if (cmd) { closePalette(); cmd.do(); }
      }
    }
  });
  // click on the backdrop (anywhere outside the card) closes
  $("#palette").addEventListener("click", (e) => {
    if (!e.target.closest(".palette-card")) closePalette();
  });
}

/* ==========================================================================
   LOGOUT
   ========================================================================== */
function logout() {
  localStorage.removeItem(KEY_STORAGE);
  state.apiKey = "";
  showGate();
  toast("Signed out — your key is forgotten on this device", "info");
}

/* ==========================================================================
   GLOBAL KEYBOARD SHORTCUTS
   ========================================================================== */
function bindKeyboard() {
  document.addEventListener("keydown", (e) => {
    const inField = e.target.matches("input, textarea, [contenteditable=true]");
    const cmdK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";

    if (cmdK) {
      e.preventDefault();
      if ($("#palette").hidden) openPalette(); else closePalette();
      return;
    }
    if (e.key === "Escape") {
      if (!$("#palette").hidden) closePalette();
      else if (!$("#help-drawer").hidden) closeHelp();
      return;
    }
    if (inField) return;
    if ($("#auth-gate").hidden === false) return;

    if (e.key === "?") { e.preventDefault(); $("#help-drawer").hidden ? openHelp() : closeHelp(); }
    if (e.key >= "1" && e.key <= "5") {
      const order = ["overview", "providers", "routing", "analytics", "keys"];
      const idx = parseInt(e.key, 10) - 1;
      if (order[idx]) setTab(order[idx]);
    }
  });
}

/* ==========================================================================
   AUTH FORM BIND
   ========================================================================== */
function bindAuth() {
  const form = $("#auth-form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const v = $("#api-key-input").value.trim();
    if (!v) return;
    state.apiKey = v;
    localStorage.setItem(KEY_STORAGE, v);
    const status = $("#auth-status");
    status.textContent = "Checking…";
    status.classList.remove("ok");
    const ok = await checkAuth();
    if (ok) {
      status.textContent = "Welcome aboard.";
      status.classList.add("ok");
      setTimeout(showShell, 350);
    } else {
      status.textContent = "That key didn't work. Double-check the prefix sk-orca-…";
      localStorage.removeItem(KEY_STORAGE);
      state.apiKey = "";
    }
  });

  $("#api-key-toggle").addEventListener("click", () => {
    const i = $("#api-key-input");
    i.type = i.type === "password" ? "text" : "password";
  });

  $("#logout-btn").addEventListener("click", logout);
}

/* ==========================================================================
   BOOT
   ========================================================================== */
document.addEventListener("DOMContentLoaded", async () => {
  bindAuth();
  bindTabs();
  bindProviderForm();
  bindRouting();
  bindWindowSeg();
  bindKeyForm();
  bindHelp();
  bindPalette();
  bindKeyboard();
  bindQuickstart();
  bindOnboarding();
  bindHostedForm();

  // Probe existing key
  const ok = await checkAuth();
  if (ok) showShell();
  else showGate();
});

window.addEventListener("hashchange", () => {
  const t = (location.hash || "").replace("#", "");
  if (TAB_META[t]) setTab(t);
});
