//! Pure rules for the menu-bar title and notifications. No Tauri types here,
//! so `cargo test` exercises them without a window system.

use serde_json::Value;

/// What the app needs from `/v1/app/summary` between two polls.
#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    pub today_microcents: i64,
    pub budget_state: String,
    pub used_percent: Option<f64>,
    pub daily_cents: Option<i64>,
    pub failures_avoided: i64,
    /// Budget mode "stop": agents are paused once the budget is reached.
    pub stops: bool,
    pub week_spend_microcents: i64,
    /// What the same requests would have cost on `baseline_model`, minus spend.
    pub week_saved_microcents: i64,
    pub baseline_model: String,
    /// A newer release the engine found, if any.
    pub update_version: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Alert {
    BudgetWarn { used_percent: f64, limit: String },
    BudgetOver { limit: String, stops: bool },
    Rescued { count: i64 },
    Weekly { spend: i64, saved: i64, vs: String, rescued: i64 },
    Update { version: String },
    /// D5: an agent's settings no longer point at Orca.
    AgentChanged { agent: String },
    /// H2: requests failed with no other provider left.
    BackupOffer(BackupOffer),
    /// H4: OrcaRouter answered "payment required".
    OutOfCredit,
}

/// What to do about the weekly summary notification on this poll.
#[derive(Debug, Clone, PartialEq)]
pub enum Digest {
    Nothing,
    /// Remember this week as handled without notifying.
    Record { week: String },
    Send { week: String, alert: Alert },
}

fn model_name(id: &str) -> String {
    match id {
        "gpt-4o" => "GPT-4o".into(),
        other => other.into(),
    }
}

/// One notification a week, from Monday 09:00 local time (or the first poll
/// after it, if the app was closed), summarising the last 7 days. Never on
/// first launch, and never for a week with no spend.
pub fn weekly_digest(now: chrono::NaiveDateTime, last_sent: Option<&str>, s: &Snapshot) -> Digest {
    use chrono::{Datelike, Timelike, Weekday};
    let iso = now.iso_week();
    let key = format!("{}-W{:02}", iso.year(), iso.week());
    if last_sent == Some(key.as_str()) || (now.weekday() == Weekday::Mon && now.hour() < 9) {
        return Digest::Nothing;
    }
    if last_sent.is_none() || s.week_spend_microcents <= 0 {
        return Digest::Record { week: key };
    }
    Digest::Send {
        week: key,
        alert: Alert::Weekly {
            spend: s.week_spend_microcents,
            saved: s.week_saved_microcents,
            vs: model_name(&s.baseline_model),
            rescued: s.failures_avoided,
        },
    }
}

pub fn money(microcents: i64) -> String {
    let cents = (microcents.max(0) + 5_000) / 10_000;
    let dollars = (cents / 100).to_string();
    let mut grouped = String::new();
    for (i, ch) in dollars.chars().enumerate() {
        if i > 0 && (dollars.len() - i) % 3 == 0 {
            grouped.push(',');
        }
        grouped.push(ch);
    }
    format!("${}.{:02}", grouped, cents % 100)
}

pub fn parse_summary(v: &Value) -> Option<Snapshot> {
    let today = v.get("today")?.get("spend_microcents")?.as_i64()?;
    let week = v.get("week")?;
    let budget = v.get("budget")?;
    Some(Snapshot {
        today_microcents: today,
        budget_state: budget.get("state")?.as_str()?.to_string(),
        used_percent: budget.get("used_percent").and_then(Value::as_f64),
        daily_cents: budget.get("daily_cents").and_then(Value::as_i64),
        failures_avoided: week.get("failures_avoided").and_then(Value::as_i64).unwrap_or(0),
        stops: budget.get("mode").and_then(Value::as_str) == Some("stop"),
        week_spend_microcents: week.get("spend_microcents").and_then(Value::as_i64).unwrap_or(0),
        week_saved_microcents: week.get("saved_microcents").and_then(Value::as_i64).unwrap_or(0),
        baseline_model: week.get("baseline_model").and_then(Value::as_str).unwrap_or("").to_string(),
        update_version: v
            .get("update")
            .and_then(|u| u.get("version"))
            .and_then(Value::as_str)
            .map(str::to_string),
    })
}

/// Did the engine answer our challenge with the per-launch secret from
/// engine.json? Checked before the app ever sends the engine its key.
pub fn verify_proof(secret: &str, challenge: &str, proof: &str) -> bool {
    use hmac::{Hmac, Mac};
    let Ok(expected) = hex::decode(proof) else {
        return false;
    };
    let Ok(mut mac) = Hmac::<sha2::Sha256>::new_from_slice(secret.as_bytes()) else {
        return false;
    };
    mac.update(challenge.as_bytes());
    mac.verify_slice(&expected).is_ok() // constant-time comparison
}

/// Native commands are only for the app's own pages: the engine's origin,
/// under /desktop/. (Tauri matches remote capabilities by origin only.)
pub fn is_app_page(url: &str, base_url: &str) -> bool {
    let prefix = format!("{}/desktop/", base_url.trim_end_matches('/'));
    let Some(rest) = url.strip_prefix(&prefix) else {
        return false;
    };
    let path = rest.split(['#', '?']).next().unwrap_or("");
    !path.split('/').any(|seg| seg == ".." || seg.eq_ignore_ascii_case("%2e%2e"))
}

pub fn tray_title(s: &Snapshot) -> String {
    money(s.today_microcents)
}

fn rank(state: &str) -> u8 {
    match state {
        "warn" => 1,
        "over" => 2,
        _ => 0,
    }
}

pub fn alerts(prev: Option<&Snapshot>, cur: &Snapshot) -> Vec<Alert> {
    let Some(prev) = prev else {
        return Vec::new(); // never alert on launch for something already true
    };
    let mut out = Vec::new();
    let limit = || money(cur.daily_cents.unwrap_or(0) * 10_000);
    if rank(&cur.budget_state) > rank(&prev.budget_state) {
        match cur.budget_state.as_str() {
            "warn" => out.push(Alert::BudgetWarn {
                used_percent: cur.used_percent.unwrap_or(0.0),
                limit: limit(),
            }),
            "over" => out.push(Alert::BudgetOver { limit: limit(), stops: cur.stops }),
            _ => {}
        }
    }
    if cur.failures_avoided > prev.failures_avoided {
        out.push(Alert::Rescued { count: cur.failures_avoided - prev.failures_avoided });
    }
    out
}

/// In-app updates are on only in builds made with the updater's public key
/// and an https endpoint (release CI adds them when the signing key is
/// configured). Without them the updater plugin isn't loaded at all, and the
/// panel links to the release page instead.
pub fn updates_installable(plugins: &Value) -> bool {
    let Some(updater) = plugins.get("updater") else {
        return false;
    };
    let has_key = updater.get("pubkey").and_then(Value::as_str).is_some_and(|k| !k.trim().is_empty());
    let endpoints = updater.get("endpoints").and_then(Value::as_array);
    let https = endpoints.is_some_and(|e| {
        !e.is_empty() && e.iter().all(|u| u.as_str().is_some_and(|u| u.starts_with("https://")))
    });
    has_key && https
}

/// Whether the engine's desktop settings ask to start Orca at login. On
/// unless the user turned it off: connected agents point at the engine, so
/// after a restart it has to be running before anyone opens the app.
pub fn wants_start_at_login(settings: &Value) -> bool {
    settings.get("start_at_login").and_then(Value::as_bool).unwrap_or(true)
}

/// Some(enable) when the OS login item has to change to match `wanted`.
pub fn autostart_change(wanted: bool, currently_enabled: bool) -> Option<bool> {
    (wanted != currently_enabled).then_some(wanted)
}

/// What to tell the user when the engine exits during startup: the last
/// line it wrote (its own explanation, e.g. a locked keychain), or a pointer
/// to the log when it wrote nothing.
pub fn startup_failure(new_output: &str, log_path: &str) -> String {
    match new_output.lines().map(str::trim).rfind(|l| !l.is_empty()) {
        Some(line) => line.chars().take(300).collect(),
        None => format!("The Orca engine stopped during startup. See {log_path}"),
    }
}

/// Announce a newer release once per version; the caller remembers which.
pub fn update_notice(last_announced: Option<&str>, s: &Snapshot) -> Option<(String, Alert)> {
    let version = s.update_version.as_deref()?;
    if last_announced == Some(version) {
        return None;
    }
    Some((version.to_string(), Alert::Update { version: version.to_string() }))
}

// ── H1: an OrcaRouter key on the clipboard ──

/// The clipboard text, trimmed, if the whole of it is shaped like an
/// OrcaRouter key (`sk-orca-` and 16–200 of `[A-Za-z0-9_-]`). Anything else
/// (other providers' keys, prose that mentions a key) is never returned.
pub fn orca_key_from_clipboard(text: &str) -> Option<String> {
    let t = text.trim();
    let rest = t.strip_prefix("sk-orca-")?;
    let ok = (16..=200).contains(&rest.len())
        && rest.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-');
    ok.then(|| t.to_string())
}

// ── D5 / H2 / H4: notifications from the summary ──

/// The H2 offer as the notification states it.
#[derive(Debug, Clone, PartialEq)]
pub struct BackupOffer {
    pub failed: i64,
    pub provider: String,
    pub agent: String,
}

/// What the D5, H2 and H4 notifications watch in `/v1/app/summary`.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Watch {
    /// (id, name) of each agent whose settings no longer point at Orca.
    pub changed_agents: Vec<(String, String)>,
    pub backup_offer: Option<BackupOffer>,
    pub out_of_credit: bool,
}

/// What has been notified already, kept in `~/.orcarouter-lite/notified.json`
/// so a restart doesn't repeat it.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Notified {
    /// ISO week ("2026-W48") of the last backup-offer notification.
    pub backup_week: Option<String>,
    /// Agents announced as changed and still changed.
    pub changed_agents: Vec<String>,
    /// The current out-of-credit episode was announced.
    pub out_of_credit: bool,
}

/// Display names for provider ids, as the app shows them.
pub fn provider_name(id: &str) -> String {
    let known = match id {
        "anthropic" => "Anthropic",
        "openai" => "OpenAI",
        "google" | "gemini" => "Google",
        "deepseek" => "DeepSeek",
        "xai" => "xAI",
        "mistral" => "Mistral",
        "groq" => "Groq",
        "together" => "Together AI",
        "fireworks" => "Fireworks",
        "cohere" => "Cohere",
        "moonshot" => "Moonshot",
        "qwen" => "Qwen",
        "minimax" => "MiniMax",
        "zai" => "Z.ai",
        "openrouter" => "OpenRouter",
        "orcarouter" => "OrcaRouter",
        _ => "",
    };
    if known.is_empty() {
        humanize(id)
    } else {
        known.to_string()
    }
}

/// "some-new-one" -> "Some New One": a readable fallback for an unknown id.
fn humanize(id: &str) -> String {
    id.split(['-', '_'])
        .filter(|w| !w.is_empty())
        .map(|w| {
            let mut c = w.chars();
            c.next().map(|f| f.to_uppercase().chain(c).collect::<String>()).unwrap_or_default()
        })
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn parse_watch(v: &Value) -> Watch {
    let agents: Vec<&Value> = v.get("agents").and_then(Value::as_array).map(|a| a.iter().collect()).unwrap_or_default();
    let name_of = |id: &str| -> String {
        agents
            .iter()
            .find(|a| a.get("id").and_then(Value::as_str) == Some(id))
            .and_then(|a| a.get("name").and_then(Value::as_str))
            .map(str::to_string)
            .unwrap_or_else(|| humanize(id))
    };
    let changed_agents = agents
        .iter()
        .filter(|a| a.get("state").and_then(Value::as_str) == Some("changed"))
        .filter_map(|a| a.get("id").and_then(Value::as_str))
        .map(|id| (id.to_string(), name_of(id)))
        .collect();
    let backup_offer = v
        .get("offers")
        .and_then(Value::as_array)
        .and_then(|offers| offers.iter().find(|o| o.get("id").and_then(Value::as_str) == Some("backup")))
        .and_then(|o| {
            let failed = o.get("failed_today").and_then(Value::as_i64).filter(|n| *n > 0)?;
            let provider = provider_name(o.get("provider").and_then(Value::as_str)?);
            let agent = match o.get("agent").and_then(Value::as_str) {
                Some(id) => name_of(id),
                None => "Your coding agents".to_string(),
            };
            Some(BackupOffer { failed, provider, agent })
        });
    let out_of_credit = v
        .get("hosted")
        .and_then(|h| h.get("out_of_credit"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    Watch { changed_agents, backup_offer, out_of_credit }
}

/// The notifications due on this poll and the state to remember afterwards.
/// D5: once each time an agent becomes "changed". H2: at most once per ISO
/// week. H4: once per out-of-credit episode.
pub fn notices(today: chrono::NaiveDate, prev: &Notified, w: &Watch) -> (Notified, Vec<Alert>) {
    use chrono::Datelike;
    let mut alerts = Vec::new();
    for (id, name) in &w.changed_agents {
        if !prev.changed_agents.contains(id) {
            alerts.push(Alert::AgentChanged { agent: name.clone() });
        }
    }
    let changed_agents = w.changed_agents.iter().map(|(id, _)| id.clone()).collect();

    let iso = today.iso_week();
    let this_week = format!("{}-W{:02}", iso.year(), iso.week());
    let mut backup_week = prev.backup_week.clone();
    if let Some(offer) = &w.backup_offer {
        if backup_week.as_deref() != Some(this_week.as_str()) {
            alerts.push(Alert::BackupOffer(offer.clone()));
            backup_week = Some(this_week);
        }
    }

    if w.out_of_credit && !prev.out_of_credit {
        alerts.push(Alert::OutOfCredit);
    }
    (Notified { backup_week, changed_agents, out_of_credit: w.out_of_credit }, alerts)
}

pub fn notified_to_json(n: &Notified) -> String {
    serde_json::json!({
        "backup_week": n.backup_week,
        "changed_agents": n.changed_agents,
        "out_of_credit": n.out_of_credit,
    })
    .to_string()
}

/// Field by field, so a damaged or older file loses only what's unreadable.
pub fn notified_from_json(text: &str) -> Notified {
    let v: Value = serde_json::from_str(text).unwrap_or(Value::Null);
    Notified {
        backup_week: v.get("backup_week").and_then(Value::as_str).map(str::to_string),
        changed_agents: v
            .get("changed_agents")
            .and_then(Value::as_array)
            .map(|a| a.iter().filter_map(Value::as_str).map(str::to_string).collect())
            .unwrap_or_default(),
        out_of_credit: v.get("out_of_credit").and_then(Value::as_bool).unwrap_or(false),
    }
}

// ── V3: orca:// links ──

/// A link the app understood. It is never acted on directly: the page shows
/// what it would do and waits for the user's click.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(tag = "action", rename_all = "lowercase")]
pub enum OrcaLink {
    Connect { agent: String },
    Join { gateway: String },
    Setup { agents: Vec<String>, budget_cents: Option<u64> },
}

impl OrcaLink {
    /// The window whose page confirms the link.
    pub fn window(&self) -> &'static str {
        match self {
            OrcaLink::Setup { .. } => "setup",
            _ => "panel",
        }
    }
}

const MAX_LINK_LEN: usize = 2048;
const MAX_LINK_AGENTS: usize = 20;
const MAX_BUDGET_CENTS: u64 = 100_000_000;

/// Something that might be a credential: a token starting `sk-`, or a long
/// run of letters mixed with digits (an API key, a hex secret).
pub fn looks_like_key(s: &str) -> bool {
    let lower = s.to_ascii_lowercase();
    let bytes = lower.as_bytes();
    let sk_token = lower
        .match_indices("sk-")
        .any(|(i, _)| i == 0 || !bytes[i - 1].is_ascii_alphanumeric());
    let random_run = s.split(|c: char| !c.is_ascii_alphanumeric()).any(|run| {
        run.len() >= 24 && run.bytes().any(|b| b.is_ascii_digit()) && run.bytes().any(|b| b.is_ascii_alphabetic())
    });
    sk_token || random_run
}

fn is_agent_id(s: &str) -> bool {
    (1..=40).contains(&s.len()) && s.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

fn private_host(host: &url::Host<&str>) -> bool {
    match host {
        url::Host::Domain(d) => d.eq_ignore_ascii_case("localhost"),
        url::Host::Ipv4(ip) => ip.is_loopback() || ip.is_private() || ip.is_link_local(),
        url::Host::Ipv6(ip) => {
            let first = ip.segments()[0];
            ip.is_loopback() || (first & 0xfe00) == 0xfc00 || (first & 0xffc0) == 0xfe80
        }
    }
}

/// The gateway address a join link may carry: https, or http only to a
/// loopback or private-network address; no credentials, query or fragment;
/// the base address (not `/v1`). Same rules as the engine's gateway check.
fn gateway_url(raw: &str) -> Option<String> {
    let u = url::Url::parse(raw).ok()?;
    let host = u.host()?;
    let ok_scheme = match u.scheme() {
        "https" => true,
        "http" => private_host(&host),
        _ => false,
    };
    if !ok_scheme || !u.username().is_empty() || u.password().is_some() || u.query().is_some() || u.fragment().is_some() {
        return None;
    }
    let s = u.as_str().trim_end_matches('/').to_string();
    if u.path().trim_end_matches('/').ends_with("/v1") || looks_like_key(&s) {
        return None;
    }
    Some(s)
}

/// Parse and validate an `orca://` link. Anything not exactly one of the
/// three shapes (connect, join, setup) with only their own parameters is
/// ignored, and so is any link that seems to carry a key.
pub fn parse_orca_link(raw: &str) -> Option<OrcaLink> {
    if raw.is_empty() || raw.len() > MAX_LINK_LEN || !raw.bytes().all(|b| b.is_ascii_graphic()) {
        return None;
    }
    let u = url::Url::parse(raw).ok()?;
    if u.scheme() != "orca"
        || !u.username().is_empty()
        || u.password().is_some()
        || u.port().is_some()
        || u.fragment().is_some()
        || !matches!(u.path(), "" | "/")
    {
        return None;
    }
    let action = match u.host()? {
        url::Host::Domain(d) => d.to_string(),
        _ => return None,
    };
    let mut params: Vec<(String, String)> = Vec::new();
    for (k, v) in u.query_pairs() {
        if params.iter().any(|(seen, _)| *seen == k) || looks_like_key(&k) || looks_like_key(&v) {
            return None;
        }
        params.push((k.into_owned(), v.into_owned()));
    }
    let allowed: &[&str] = match action.as_str() {
        "connect" => &["agent"],
        "join" => &["gateway"],
        "setup" => &["agents", "budget"],
        _ => return None,
    };
    if params.iter().any(|(k, _)| !allowed.contains(&k.as_str())) {
        return None;
    }
    let get = |name: &str| params.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str());
    match action.as_str() {
        "connect" => {
            let agent = get("agent").filter(|a| is_agent_id(a))?;
            Some(OrcaLink::Connect { agent: agent.to_string() })
        }
        "join" => Some(OrcaLink::Join { gateway: gateway_url(get("gateway")?)? }),
        _ => {
            let (agents_raw, budget_raw) = (get("agents"), get("budget"));
            if agents_raw.is_none() && budget_raw.is_none() {
                return None;
            }
            let mut agents: Vec<String> = Vec::new();
            if let Some(list) = agents_raw {
                for id in list.split(',') {
                    if !is_agent_id(id) {
                        return None;
                    }
                    if !agents.iter().any(|a| a == id) {
                        agents.push(id.to_string());
                    }
                }
                if agents.len() > MAX_LINK_AGENTS {
                    return None;
                }
            }
            let budget_cents = match budget_raw {
                None => None,
                Some(b) if !b.is_empty() && b.len() <= 9 && b.bytes().all(|c| c.is_ascii_digit()) => {
                    Some(b.parse::<u64>().ok().filter(|c| *c <= MAX_BUDGET_CENTS)?)
                }
                Some(_) => return None,
            };
            Some(OrcaLink::Setup { agents, budget_cents })
        }
    }
}

/// A second launch carrying a link (Windows, Linux) is handled as the link,
/// not as a click on the app.
pub fn argv_has_orca_link(argv: &[String]) -> bool {
    // `get` rather than slicing: byte 7 may fall inside a multibyte character.
    argv.iter().skip(1).any(|a| a.get(..7).is_some_and(|p| p.eq_ignore_ascii_case("orca://")))
}

// ── V2: the savings card image ──

/// Base64 of a PNG up to about 12 MB: far more than a share card needs.
pub const MAX_PNG_BASE64: usize = 16 * 1024 * 1024;

/// The PNG bytes of a base64 string (a `data:image/png;base64,` prefix is
/// fine, since that's what a canvas gives). Anything that isn't a PNG is refused.
pub fn png_from_base64(text: &str) -> Result<Vec<u8>, String> {
    use base64::Engine as _;
    let b64 = text.strip_prefix("data:image/png;base64,").unwrap_or(text).trim();
    if b64.is_empty() || b64.len() > MAX_PNG_BASE64 {
        return Err("That image is empty or too large.".into());
    }
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(b64)
        .map_err(|_| "That image isn't valid base64.".to_string())?;
    if !bytes.starts_with(&[0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a]) {
        return Err("Only PNG images can be copied.".into());
    }
    Ok(bytes)
}

// ── D6: the orca command on the PATH ──

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Os {
    Mac,
    Linux,
    Windows,
}

/// What is already at a place the `orca` command could go.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Existing {
    Missing,
    /// A link to this app's engine.
    Current,
    /// A link to an `orca-engine` elsewhere (an earlier copy of the app).
    Stale,
    /// Something else, which is never replaced.
    Other,
}

/// `present`: anything at the path (a dangling link counts). `link_target`:
/// where it points if it's a symbolic link.
pub fn classify_existing(present: bool, link_target: Option<&str>, engine: &str) -> Existing {
    if !present {
        return Existing::Missing;
    }
    match link_target {
        Some(t) if t == engine => Existing::Current,
        Some(t) if t.rsplit(['/', '\\']).next() == Some("orca-engine") => Existing::Stale,
        _ => Existing::Other,
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CliEnv {
    pub os: Os,
    /// The bundled engine (which is also the CLI), if this build has one.
    pub engine: Option<String>,
    pub home: String,
    pub path_var: String,
    /// Running as an AppImage, from a temporary mount.
    pub appimage: bool,
    /// macOS: /usr/local/bin/orca.
    pub system: Existing,
    pub system_dir_writable: bool,
    /// ~/.local/bin/orca.
    pub user: Existing,
}

#[derive(Debug, Clone, PartialEq)]
pub enum CliStep {
    /// A symbolic link to the engine; `admin` asks for the password first.
    Link { link: String, admin: bool },
    /// Write `orca.cmd` into `dir` and add `dir` to the user's PATH.
    WindowsShim { dir: String, shim: String },
}

#[derive(Debug, Clone, PartialEq)]
pub enum CliPlan {
    Refuse(String),
    Already { at: String },
    /// Try each step in order until one works.
    Try(Vec<CliStep>),
}

pub const SYSTEM_CLI: &str = "/usr/local/bin/orca";

fn user_cli(home: &str) -> String {
    format!("{}/.local/bin/orca", home.trim_end_matches('/'))
}

/// `~` for the home folder in paths shown to the user.
pub fn tilde(path: &str, home: &str) -> String {
    let home = home.trim_end_matches(['/', '\\']);
    match path.strip_prefix(home) {
        Some(rest) if !home.is_empty() && (rest.is_empty() || rest.starts_with(['/', '\\'])) => format!("~{rest}"),
        _ => path.to_string(),
    }
}

fn someone_elses(path: &str, home: &str) -> CliPlan {
    CliPlan::Refuse(format!(
        "There's already a different orca command at {}. Remove it, then try again.",
        tilde(path, home)
    ))
}

/// Where to put the `orca` command on this computer, in order of preference.
pub fn cli_plan(env: &CliEnv) -> CliPlan {
    let Some(engine) = env.engine.as_deref() else {
        return CliPlan::Refuse("This build of OrcaRouter Lite doesn't include the orca command.".into());
    };
    let user = user_cli(&env.home);
    match env.os {
        Os::Windows => CliPlan::Try(vec![CliStep::WindowsShim {
            dir: format!("{}\\.orcarouter-lite\\bin", env.home.trim_end_matches('\\')),
            shim: windows_shim(engine, &env.home),
        }]),
        Os::Linux => {
            if env.appimage {
                return CliPlan::Refuse(
                    "The AppImage can't add the orca command, because it runs from a temporary folder. \
                     Install the .deb package to get it."
                        .into(),
                );
            }
            match env.user {
                Existing::Current => CliPlan::Already { at: user },
                Existing::Other => someone_elses(&user, &env.home),
                _ => CliPlan::Try(vec![CliStep::Link { link: user, admin: false }]),
            }
        }
        Os::Mac => {
            // A quarantined app runs from a random read-only copy; a link to
            // it would break as soon as it's moved.
            if engine.contains("/AppTranslocation/") || engine.starts_with("/Volumes/") {
                return CliPlan::Refuse(
                    "Move OrcaRouter Lite to your Applications folder, open it from there, then try again.".into(),
                );
            }
            if env.system == Existing::Current {
                return CliPlan::Already { at: SYSTEM_CLI.into() };
            }
            if env.user == Existing::Current {
                return CliPlan::Already { at: user };
            }
            let mut steps = Vec::new();
            if env.system != Existing::Other {
                steps.push(CliStep::Link { link: SYSTEM_CLI.into(), admin: !env.system_dir_writable });
            }
            if env.user != Existing::Other {
                steps.push(CliStep::Link { link: user, admin: false });
            }
            if steps.is_empty() {
                return someone_elses(SYSTEM_CLI, &env.home);
            }
            CliPlan::Try(steps)
        }
    }
}

fn same_dir(a: &str, b: &str, os: Os) -> bool {
    let (a, b) = (a.trim_end_matches(['/', '\\']), b.trim_end_matches(['/', '\\']));
    if os == Os::Windows {
        a.eq_ignore_ascii_case(b)
    } else {
        a == b
    }
}

/// The notification after the command was installed (or found installed).
pub fn cli_installed(env: &CliEnv, at: &str) -> (String, String) {
    let dir = at.rsplit_once(['/', '\\']).map(|(d, _)| d).unwrap_or(at);
    let sep = if env.os == Os::Windows { ';' } else { ':' };
    // /usr/local/bin is on every macOS PATH (/etc/paths), even when an app's own isn't.
    let on_path = env.os == Os::Windows
        || at == SYSTEM_CLI
        || env.path_var.split(sep).any(|p| same_dir(p, dir, env.os));
    let body = if on_path {
        "Installed. Open a new terminal and run orca status.".to_string()
    } else {
        format!(
            "Installed at {}, which isn't on your PATH. Add {} to your PATH, then open a new terminal and run orca status.",
            tilde(at, &env.home),
            tilde(dir, &env.home)
        )
    };
    ("Command-line tool installed".to_string(), body)
}

/// A string in single quotes for /bin/sh.
pub fn sh_quote(s: &str) -> String {
    format!("'{}'", s.replace('\'', r"'\''"))
}

fn applescript_string(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', r"\\").replace('"', "\\\""))
}

/// The osascript program that links `link` to `engine` as root, after the
/// standard macOS password prompt.
pub fn admin_link_script(engine: &str, link: &str) -> String {
    let dir = link.rsplit_once('/').map(|(d, _)| d).unwrap_or("/usr/local/bin");
    let shell = format!("mkdir -p {} && ln -sf {} {}", sh_quote(dir), sh_quote(engine), sh_quote(link));
    format!(
        "do shell script {} with prompt {} with administrator privileges",
        applescript_string(&shell),
        applescript_string(&format!("OrcaRouter Lite wants to add the orca command to {dir}."))
    )
}

/// `orca.cmd`: runs the bundled engine with the same arguments.
///
/// cmd reads a batch file in the console's codepage, not UTF-8, so a profile
/// folder like `C:\Users\José` would come out garbled; the profile part of
/// the path is written as `%USERPROFILE%`, which cmd expands correctly.
pub fn windows_shim(engine_exe: &str, home: &str) -> String {
    let home = home.trim_end_matches('\\');
    let path = match engine_exe.get(..home.len()) {
        Some(head)
            if !home.is_empty()
                && head.eq_ignore_ascii_case(home)
                && engine_exe[home.len()..].starts_with('\\') =>
        {
            format!("%USERPROFILE%{}", engine_exe[home.len()..].replace('%', "%%"))
        }
        _ => engine_exe.replace('%', "%%"),
    };
    format!("@echo off\r\n\"{path}\" %*\r\n")
}

/// Reading the user's PATH from the registry.
#[derive(Debug, Clone, PartialEq)]
pub enum PathRead {
    Found(String),
    NotFound,
    Failed(String),
}

/// The current user PATH, or an error that stops the install: only a
/// missing value is empty. Treating any other failure (access denied, say)
/// as empty would overwrite the user's whole PATH with Orca's folder.
pub fn user_path(read: PathRead) -> Result<String, String> {
    match read {
        PathRead::Found(text) => Ok(text),
        PathRead::NotFound => Ok(String::new()),
        PathRead::Failed(why) => Err(format!("Your PATH setting couldn't be read ({why}), so it wasn't changed.")),
    }
}

/// H1: clear the clipboard after saving only if it still holds the key that
/// was saved, never another key or anything copied since.
pub fn should_clear_clipboard(clipboard: &str, saved: &str) -> bool {
    let saved = saved.trim();
    !saved.is_empty() && clipboard.trim() == saved
}

/// V3: how long a link waits for its window to take it. Older links are
/// dropped so a confirmation never appears long after, out of context.
pub const LINK_TTL_SECS: u64 = 120;

pub fn link_is_fresh(age: std::time::Duration) -> bool {
    age.as_secs() < LINK_TTL_SECS
}

/// The user PATH with `dir` appended, or None when it's already there.
pub fn path_with_entry(current: &str, dir: &str) -> Option<String> {
    if current.split(';').any(|p| same_dir(p.trim(), dir, Os::Windows)) {
        return None;
    }
    let base = current.trim_end_matches(';');
    Some(if base.is_empty() { dir.to_string() } else { format!("{base};{dir}") })
}

fn requests(n: i64) -> String {
    format!("{} {}", n, if n == 1 { "request" } else { "requests" })
}

impl Alert {
    pub fn title(&self) -> String {
        match self {
            Alert::BudgetWarn { used_percent, limit } => {
                format!("{:.0}% of today's {} budget used", used_percent, limit)
            }
            Alert::BudgetOver { limit, .. } => format!("Today's {} budget is used up", limit),
            Alert::Rescued { count } => format!("{} rescued by fallback", requests(*count)),
            Alert::Weekly { spend, .. } => format!("Last 7 days: {} on coding agents", money(*spend)),
            Alert::Update { version } => format!("OrcaRouter Lite {version} is available"),
            Alert::AgentChanged { agent } => format!("{agent} stopped using Orca"),
            Alert::BackupOffer(o) => format!(
                "{} hit {} {} from {}",
                o.agent,
                o.failed,
                if o.failed == 1 { "error" } else { "errors" },
                o.provider
            ),
            Alert::OutOfCredit => "OrcaRouter is out of credit".into(),
        }
    }

    pub fn body(&self) -> String {
        match self {
            Alert::BudgetWarn { .. } => "Your coding agents keep working. Open Orca to see which agent is spending.".into(),
            Alert::BudgetOver { stops: true, .. } => {
                "Orca paused your coding agents for today. Raise the budget in Orca to let them continue.".into()
            }
            Alert::BudgetOver { stops: false, .. } => {
                "Your agents keep working; Orca only alerts. Raise the budget or switch to auto-routing in Orca.".into()
            }
            Alert::Rescued { .. } => "A provider failed or rate-limited you, and Orca sent the request elsewhere.".into(),
            Alert::Update { .. } => "Open Orca from the menu bar and choose Download.".into(),
            Alert::AgentChanged { .. } => "Its settings changed. Open Orca to reconnect.".into(),
            Alert::BackupOffer(_) => {
                "Orca can retry these through OrcaRouter next time. Open Orca to set it up.".into()
            }
            Alert::OutOfCredit => "Orca is using your own keys only.".into(),
            Alert::Weekly { saved, vs, rescued, .. } => {
                let mut parts = Vec::new();
                if *saved > 0 {
                    parts.push(format!("Saved {} vs {}.", money(*saved), vs));
                }
                if *rescued > 0 {
                    parts.push(format!("{} rescued by fallback.", requests(*rescued)));
                }
                if parts.is_empty() {
                    "Open Orca to see which agent spent it.".into()
                } else {
                    parts.join(" ")
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn snap(today: i64, state: &str, pct: Option<f64>, daily: Option<i64>, rescued: i64) -> Snapshot {
        Snapshot {
            today_microcents: today,
            budget_state: state.into(),
            used_percent: pct,
            daily_cents: daily,
            failures_avoided: rescued,
            stops: false,
            week_spend_microcents: 0,
            week_saved_microcents: 0,
            baseline_model: String::new(),
            update_version: None,
        }
    }

    fn week(spend: i64, saved: i64, rescued: i64) -> Snapshot {
        Snapshot {
            week_spend_microcents: spend,
            week_saved_microcents: saved,
            baseline_model: "gpt-4o".into(),
            ..snap(0, "ok", None, None, rescued)
        }
    }

    fn at(y: i32, m: u32, d: u32, h: u32) -> chrono::NaiveDateTime {
        chrono::NaiveDate::from_ymd_opt(y, m, d).unwrap().and_hms_opt(h, 0, 0).unwrap()
    }

    // 2026-11-23 is a Monday, ISO week 2026-W48.

    #[test]
    fn weekly_digest_is_sent_on_monday_morning_once_per_week() {
        let s = week(42_500_000, 61_000_000, 3);
        match weekly_digest(at(2026, 11, 23, 9), Some("2026-W47"), &s) {
            Digest::Send { week, alert } => {
                assert_eq!(week, "2026-W48");
                assert_eq!(alert.title(), "Last 7 days: $42.50 on coding agents");
                assert_eq!(alert.body(), "Saved $61.00 vs GPT-4o. 3 requests rescued by fallback.");
            }
            other => panic!("expected a digest, got {other:?}"),
        }
        assert_eq!(weekly_digest(at(2026, 11, 23, 15), Some("2026-W48"), &s), Digest::Nothing);
    }

    #[test]
    fn weekly_digest_waits_for_monday_nine_am() {
        let s = week(1_000_000, 0, 0);
        assert_eq!(weekly_digest(at(2026, 11, 23, 8), Some("2026-W47"), &s), Digest::Nothing);
        // Missed Monday (app was closed): the first poll later that week sends it.
        assert!(matches!(weekly_digest(at(2026, 11, 26, 8), Some("2026-W47"), &s), Digest::Send { .. }));
    }

    #[test]
    fn weekly_digest_is_not_sent_on_first_launch_or_for_an_idle_week() {
        let s = week(1_000_000, 0, 0);
        assert_eq!(
            weekly_digest(at(2026, 11, 23, 10), None, &s),
            Digest::Record { week: "2026-W48".into() }
        );
        assert_eq!(
            weekly_digest(at(2026, 11, 23, 10), Some("2026-W47"), &week(0, 0, 0)),
            Digest::Record { week: "2026-W48".into() }
        );
    }

    #[test]
    fn parses_an_available_update() {
        let v = json!({
            "today": {"spend_microcents": 0}, "week": {},
            "budget": {"state": "none"},
            "update": {"version": "0.3.0", "url": "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/tag/v0.3.0"}
        });
        assert_eq!(parse_summary(&v).unwrap().update_version.as_deref(), Some("0.3.0"));
        let none = json!({"today": {"spend_microcents": 0}, "week": {}, "budget": {"state": "none"}, "update": null});
        assert_eq!(parse_summary(&none).unwrap().update_version, None);
    }

    #[test]
    fn an_update_is_announced_once_per_version() {
        let mut s = snap(0, "ok", None, None, 0);
        assert_eq!(update_notice(None, &s), None);
        s.update_version = Some("0.3.0".into());
        let (version, alert) = update_notice(None, &s).expect("announce 0.3.0");
        assert_eq!(version, "0.3.0");
        assert_eq!(alert.title(), "OrcaRouter Lite 0.3.0 is available");
        assert_eq!(alert.body(), "Open Orca from the menu bar and choose Download.");
        assert_eq!(update_notice(Some("0.3.0"), &s), None);
        s.update_version = Some("0.4.0".into());
        assert!(update_notice(Some("0.3.0"), &s).is_some());
    }

    #[test]
    fn in_app_updates_need_a_key_and_an_https_endpoint() {
        let ok = json!({"updater": {"pubkey": "dW50cnVzdGVk", "endpoints": [
            "https://github.com/Continuum-AI-Corp/OrcaRouter-Lite/releases/latest/download/latest.json"]}});
        assert!(updates_installable(&ok));
        assert!(!updates_installable(&json!({})));
        assert!(!updates_installable(&json!({"updater": {"pubkey": "", "endpoints": ["https://x/latest.json"]}})));
        assert!(!updates_installable(&json!({"updater": {"pubkey": "k", "endpoints": []}})));
        assert!(!updates_installable(&json!({"updater": {"pubkey": "k", "endpoints": ["http://x/latest.json"]}})));
    }

    #[test]
    fn a_failed_start_says_why_in_the_engines_own_words() {
        let out = "INFO starting\nOrca's encryption key for /home/u/.orcarouter-lite is kept in the OS keychain, \
                   but the OS keychain is switched off (ORCA_KEYCHAIN=0).\n\n";
        assert_eq!(
            startup_failure(out, "/home/u/.orcarouter-lite/engine.log"),
            "Orca's encryption key for /home/u/.orcarouter-lite is kept in the OS keychain, \
             but the OS keychain is switched off (ORCA_KEYCHAIN=0)."
        );
        assert_eq!(
            startup_failure("  \n", "/x/engine.log"),
            "The Orca engine stopped during startup. See /x/engine.log"
        );
        let long = "x".repeat(600);
        assert!(startup_failure(&long, "/x/engine.log").chars().count() <= 300);
    }

    #[test]
    fn weekly_digest_body_leaves_out_what_did_not_happen() {
        let a = Alert::Weekly { spend: 2_000_000, saved: 0, vs: "GPT-4o".into(), rescued: 1 };
        assert_eq!(a.body(), "1 request rescued by fallback.");
        let a = Alert::Weekly { spend: 2_000_000, saved: 0, vs: "GPT-4o".into(), rescued: 0 };
        assert_eq!(a.body(), "Open Orca to see which agent spent it.");
    }

    #[test]
    fn money_rounds_half_up_to_cents() {
        assert_eq!(money(0), "$0.00");
        assert_eq!(money(4_999), "$0.00");
        assert_eq!(money(5_000), "$0.01");
        assert_eq!(money(3_200_000), "$3.20");
        assert_eq!(money(123_456_789_000), "$123,456.79");
    }

    #[test]
    fn parses_the_engine_summary() {
        let v = json!({
            "today": {"spend_microcents": 3_200_000, "requests": 4},
            "week": {"spend_microcents": 9, "failures_avoided": 2},
            "budget": {"daily_cents": 2000, "used_percent": 16.0, "state": "ok"}
        });
        let mut want = snap(3_200_000, "ok", Some(16.0), Some(2000), 2);
        want.week_spend_microcents = 9;
        assert_eq!(parse_summary(&v), Some(want));
    }

    #[test]
    fn parses_a_summary_without_budget() {
        let v = json!({
            "today": {"spend_microcents": 0},
            "week": {"failures_avoided": 0},
            "budget": {"daily_cents": null, "used_percent": null, "state": "none"}
        });
        assert_eq!(parse_summary(&v), Some(snap(0, "none", None, None, 0)));
    }

    #[test]
    fn rejects_a_malformed_summary() {
        assert_eq!(parse_summary(&json!({"oops": 1})), None);
    }

    #[test]
    fn money_matches_the_shared_vectors() {
        let vectors: Vec<(i64, String)> =
            serde_json::from_str(include_str!("../../tests/money_vectors.json")).unwrap();
        for (micro, text) in vectors {
            assert_eq!(money(micro), text, "money({micro})");
        }
    }

    #[test]
    fn accepts_only_the_right_proof() {
        // HMAC-SHA256("s3cret", "abc123abc123abc123abc123"), as the engine computes it.
        let good = "4d9a6c39e3a3b8b9a4a2f5a2d2f9c4b3e9a0e0a7f1d9b4c0a2e3f4b5c6d7e8f9";
        let real = {
            use hmac::{Hmac, Mac};
            let mut m = Hmac::<sha2::Sha256>::new_from_slice(b"s3cret").unwrap();
            m.update(b"abc123abc123abc123abc123");
            hex::encode(m.finalize().into_bytes())
        };
        assert!(verify_proof("s3cret", "abc123abc123abc123abc123", &real));
        assert!(!verify_proof("s3cret", "abc123abc123abc123abc123", good));
        assert!(!verify_proof("wrong", "abc123abc123abc123abc123", &real));
        assert!(!verify_proof("s3cret", "abc123abc123abc123abc123", ""));
    }

    #[test]
    fn only_the_apps_own_pages_may_call_native_commands() {
        let base = "http://127.0.0.1:8765";
        assert!(is_app_page("http://127.0.0.1:8765/desktop/panel.html", base));
        assert!(is_app_page("http://127.0.0.1:8765/desktop/setup.html#key=x", base));
        assert!(!is_app_page("http://127.0.0.1:8765/", base));
        assert!(!is_app_page("http://127.0.0.1:8765/static/app.js", base));
        assert!(!is_app_page("http://127.0.0.1:8765/desktopx/panel.html", base));
        assert!(!is_app_page("http://127.0.0.1:87650/desktop/panel.html", base));
        assert!(!is_app_page("http://evil.example/desktop/panel.html", base));
        assert!(!is_app_page("http://127.0.0.1:8765/desktop/../docs", base));
    }

    #[test]
    fn tray_title_is_todays_spend() {
        assert_eq!(tray_title(&snap(3_200_000, "ok", None, None, 0)), "$3.20");
    }

    #[test]
    fn first_poll_never_alerts() {
        assert!(alerts(None, &snap(9_000_000, "over", Some(450.0), Some(200), 5)).is_empty());
    }

    #[test]
    fn crossing_into_warn_alerts_once() {
        let a = snap(1_500_000, "ok", Some(75.0), Some(200), 0);
        let b = snap(1_700_000, "warn", Some(85.0), Some(200), 0);
        assert_eq!(alerts(Some(&a), &b), vec![Alert::BudgetWarn { used_percent: 85.0, limit: "$2.00".into() }]);
        assert!(alerts(Some(&b), &b).is_empty());
    }

    #[test]
    fn crossing_into_over_alerts_even_when_skipping_warn() {
        let a = snap(100, "ok", Some(1.0), Some(200), 0);
        let b = snap(2_500_000, "over", Some(125.0), Some(200), 0);
        assert_eq!(alerts(Some(&a), &b), vec![Alert::BudgetOver { limit: "$2.00".into(), stops: false }]);
    }

    #[test]
    fn new_day_resets_without_alerting() {
        let late = snap(2_500_000, "over", Some(125.0), Some(200), 0);
        let morning = snap(0, "ok", Some(0.0), Some(200), 0);
        assert!(alerts(Some(&late), &morning).is_empty());
    }

    #[test]
    fn rescued_requests_alert_with_the_new_count() {
        let a = snap(0, "none", None, None, 3);
        let b = snap(0, "none", None, None, 7);
        assert_eq!(alerts(Some(&a), &b), vec![Alert::Rescued { count: 4 }]);
    }

    #[test]
    fn over_budget_in_stop_mode_says_agents_are_paused() {
        let v = json!({
            "today": {"spend_microcents": 2_000_000},
            "week": {"failures_avoided": 0},
            "budget": {"daily_cents": 200, "used_percent": 100.0, "state": "over", "mode": "stop"}
        });
        let snap = parse_summary(&v).unwrap();
        assert!(snap.stops);
        let a = snap.clone();
        let prev = Snapshot { budget_state: "ok".into(), ..a };
        let alerts = alerts(Some(&prev), &snap);
        assert_eq!(alerts.len(), 1);
        assert!(alerts[0].body().contains("paused"), "{}", alerts[0].body());
    }

    #[test]
    fn alert_copy_is_specific() {
        let w = Alert::BudgetWarn { used_percent: 85.0, limit: "$20.00".into() };
        assert_eq!(w.title(), "85% of today's $20.00 budget used");
        let o = Alert::BudgetOver { limit: "$20.00".into(), stops: false };
        assert_eq!(o.title(), "Today's $20.00 budget is used up");
        let r = Alert::Rescued { count: 1 };
        assert_eq!(r.title(), "1 request rescued by fallback");
        assert_eq!(Alert::Rescued { count: 3 }.title(), "3 requests rescued by fallback");
        assert!(!o.body().is_empty());
    }

    #[test]
    fn start_at_login_is_on_unless_the_user_turned_it_off() {
        assert!(wants_start_at_login(&json!({"daily_budget_cents": null})));
        assert!(wants_start_at_login(&json!({"start_at_login": true})));
        assert!(!wants_start_at_login(&json!({"start_at_login": false})));
        assert!(wants_start_at_login(&json!("garbage")));
    }

    #[test]
    fn only_orca_shaped_keys_are_taken_from_the_clipboard() {
        let k = "sk-orca-AbCdEf0123456789_-xy";
        assert_eq!(orca_key_from_clipboard(k), Some(k.to_string()));
        // Copying from a web page often adds surrounding whitespace.
        assert_eq!(orca_key_from_clipboard(&format!("  {k}\n")), Some(k.to_string()));
        assert_eq!(orca_key_from_clipboard("sk-orca-short"), None);
        assert_eq!(orca_key_from_clipboard(&format!("sk-orca-{}", "a".repeat(201))), None);
        assert!(orca_key_from_clipboard(&format!("sk-orca-{}", "a".repeat(200))).is_some());
        assert_eq!(orca_key_from_clipboard("sk-ant-api03-0123456789abcdefghij"), None);
        assert_eq!(orca_key_from_clipboard("my key is sk-orca-0123456789abcdefgh"), None);
        assert_eq!(orca_key_from_clipboard("sk-orca-0123456789abcdef gh"), None);
        assert_eq!(orca_key_from_clipboard("sk-orca-0123456789abcdefgh\nsecond line"), None);
        assert_eq!(orca_key_from_clipboard("sk-orca-0123456789abcdéfgh"), None);
        assert_eq!(orca_key_from_clipboard(""), None);
    }

    fn watch_summary() -> Value {
        json!({
            "today": {"spend_microcents": 0}, "week": {}, "budget": {"state": "none"},
            "agents": [
                {"id": "claude-code", "name": "Claude Code", "state": "changed"},
                {"id": "codex", "name": "Codex", "state": "connected"},
                {"id": "other", "name": "Other apps"}
            ],
            "offers": [{"id": "backup", "failed_today": 3, "provider": "anthropic", "agent": "claude-code",
                        "models": ["claude-sonnet-4-6"]}],
            "hosted": {"configured": true, "out_of_credit": true}
        })
    }

    #[test]
    fn parses_what_the_notifications_watch() {
        let w = parse_watch(&watch_summary());
        assert_eq!(w.changed_agents, vec![("claude-code".to_string(), "Claude Code".to_string())]);
        assert_eq!(
            w.backup_offer,
            Some(BackupOffer { failed: 3, provider: "Anthropic".into(), agent: "Claude Code".into() })
        );
        assert!(w.out_of_credit);
        // An engine without these fields yet: nothing to notify.
        let bare = parse_watch(&json!({"today": {}, "agents": [{"id": "codex", "name": "Codex"}]}));
        assert_eq!(bare, Watch::default());
    }

    #[test]
    fn a_backup_offer_names_the_agent_and_provider_plainly() {
        let v = json!({"offers": [{"id": "backup", "failed_today": 1, "provider": "openai", "agent": "aider"}],
                       "agents": []});
        let offer = parse_watch(&v).backup_offer.unwrap();
        assert_eq!(offer, BackupOffer { failed: 1, provider: "OpenAI".into(), agent: "Aider".into() });
        let v = json!({"offers": [{"id": "backup", "failed_today": 2, "provider": "some-new-one", "agent": null}]});
        let offer = parse_watch(&v).backup_offer.unwrap();
        assert_eq!(offer.agent, "Your coding agents");
        assert_eq!(offer.provider, "Some New One");
        // Only "backup" offers notify, and only with a real count.
        let v = json!({"offers": [{"id": "something-else", "failed_today": 2, "provider": "openai"}]});
        assert_eq!(parse_watch(&v).backup_offer, None);
        let v = json!({"offers": [{"id": "backup", "failed_today": 0, "provider": "openai"}]});
        assert_eq!(parse_watch(&v).backup_offer, None);
    }

    fn day(y: i32, m: u32, d: u32) -> chrono::NaiveDate {
        chrono::NaiveDate::from_ymd_opt(y, m, d).unwrap()
    }

    #[test]
    fn notification_copy_matches_the_roadmap() {
        let d5 = Alert::AgentChanged { agent: "Claude Code".into() };
        assert_eq!(d5.title(), "Claude Code stopped using Orca");
        assert_eq!(d5.body(), "Its settings changed. Open Orca to reconnect.");
        let h2 = Alert::BackupOffer(BackupOffer { failed: 3, provider: "Anthropic".into(), agent: "Claude Code".into() });
        assert_eq!(h2.title(), "Claude Code hit 3 errors from Anthropic");
        assert_eq!(h2.body(), "Orca can retry these through OrcaRouter next time. Open Orca to set it up.");
        let one = Alert::BackupOffer(BackupOffer { failed: 1, provider: "Anthropic".into(), agent: "Codex".into() });
        assert_eq!(one.title(), "Codex hit 1 error from Anthropic");
        let h4 = Alert::OutOfCredit;
        assert_eq!(h4.title(), "OrcaRouter is out of credit");
        assert_eq!(h4.body(), "Orca is using your own keys only.");
    }

    #[test]
    fn an_agent_that_changed_is_announced_once_per_change() {
        let w = parse_watch(&watch_summary());
        let w = Watch { backup_offer: None, out_of_credit: false, ..w };
        let (state, alerts) = notices(day(2026, 11, 24), &Notified::default(), &w);
        assert_eq!(alerts, vec![Alert::AgentChanged { agent: "Claude Code".into() }]);
        assert_eq!(state.changed_agents, vec!["claude-code".to_string()]);
        // Still changed on the next poll (or after a restart): quiet.
        let (state2, alerts) = notices(day(2026, 11, 24), &state, &w);
        assert!(alerts.is_empty());
        assert_eq!(state2, state);
        // Reconnected, then changed again: a new change, a new notification.
        let (state3, alerts) = notices(day(2026, 11, 24), &state, &Watch::default());
        assert!(alerts.is_empty());
        assert!(state3.changed_agents.is_empty());
        let (_, alerts) = notices(day(2026, 11, 25), &state3, &w);
        assert_eq!(alerts.len(), 1);
    }

    #[test]
    fn the_backup_offer_notifies_at_most_once_per_iso_week() {
        let offer = BackupOffer { failed: 3, provider: "Anthropic".into(), agent: "Claude Code".into() };
        let w = Watch { backup_offer: Some(offer.clone()), ..Watch::default() };
        // 2026-11-24 is a Tuesday in 2026-W48.
        let (state, alerts) = notices(day(2026, 11, 24), &Notified::default(), &w);
        assert_eq!(alerts, vec![Alert::BackupOffer(offer)]);
        assert_eq!(state.backup_week.as_deref(), Some("2026-W48"));
        let (_, alerts) = notices(day(2026, 11, 29), &state, &w); // Sunday, same week
        assert!(alerts.is_empty());
        let (state, alerts) = notices(day(2026, 11, 30), &state, &w); // Monday, W49
        assert_eq!(alerts.len(), 1);
        assert_eq!(state.backup_week.as_deref(), Some("2026-W49"));
        // ISO weeks, not calendar years: 2026-12-31 is in 2026-W53, 2027-01-01 too.
        let (state, _) = notices(day(2026, 12, 31), &Notified::default(), &w);
        assert_eq!(state.backup_week.as_deref(), Some("2026-W53"));
        let (_, alerts) = notices(day(2027, 1, 1), &state, &w);
        assert!(alerts.is_empty(), "2027-01-01 is still 2026-W53");
        // No offer: nothing, and the week isn't used up.
        let (state, alerts) = notices(day(2026, 11, 24), &Notified::default(), &Watch::default());
        assert!(alerts.is_empty());
        assert_eq!(state.backup_week, None);
    }

    #[test]
    fn out_of_credit_notifies_once_per_episode() {
        let out = Watch { out_of_credit: true, ..Watch::default() };
        let (state, alerts) = notices(day(2026, 11, 24), &Notified::default(), &out);
        assert_eq!(alerts, vec![Alert::OutOfCredit]);
        assert!(state.out_of_credit);
        let (state, alerts) = notices(day(2026, 11, 24), &state, &out);
        assert!(alerts.is_empty(), "same episode");
        let (state, alerts) = notices(day(2026, 11, 24), &state, &Watch::default());
        assert!(alerts.is_empty());
        assert!(!state.out_of_credit, "credit was added: the episode ended");
        let (_, alerts) = notices(day(2026, 11, 24), &state, &out);
        assert_eq!(alerts, vec![Alert::OutOfCredit], "a new episode");
    }

    #[test]
    fn notified_state_survives_a_round_trip_and_tolerates_old_files() {
        let state = Notified {
            backup_week: Some("2026-W48".into()),
            changed_agents: vec!["codex".into()],
            out_of_credit: true,
        };
        let text = notified_to_json(&state);
        assert_eq!(notified_from_json(&text), state);
        assert_eq!(notified_from_json("{}"), Notified::default());
        assert_eq!(notified_from_json("not json"), Notified::default());
        assert!(notified_from_json(r#"{"backup_week": 7, "out_of_credit": true}"#).out_of_credit);
    }

    // ── orca:// links ──

    fn connect(agent: &str) -> Option<OrcaLink> {
        Some(OrcaLink::Connect { agent: agent.into() })
    }

    fn join(gateway: &str) -> Option<OrcaLink> {
        Some(OrcaLink::Join { gateway: gateway.into() })
    }

    #[test]
    fn connect_links_carry_one_agent_id() {
        assert_eq!(parse_orca_link("orca://connect?agent=claude-code"), connect("claude-code"));
        assert_eq!(parse_orca_link("orca://connect/?agent=codex"), connect("codex"));
        assert_eq!(parse_orca_link("ORCA://connect?agent=codex"), connect("codex"));
        assert_eq!(parse_orca_link(&format!("orca://connect?agent={}", "a".repeat(40))), connect(&"a".repeat(40)));
        for bad in [
            "orca://connect",
            "orca://connect?agent=",
            "orca://connect?agent=Claude-Code",
            "orca://connect?agent=claude_code",
            "orca://connect?agent=claude%20code",
            "orca://connect?agent=../../etc",
            "orca://connect?agent=codex&agent=aider",
            "orca://connect?agent=codex&extra=1",
            "orca://connect?agent=codex#frag",
            "orca://connect/elsewhere?agent=codex",
            "orca://user@connect?agent=codex",
            "orca://connect:99?agent=codex",
        ] {
            assert_eq!(parse_orca_link(bad), None, "{bad}");
        }
        assert_eq!(parse_orca_link(&format!("orca://connect?agent={}", "a".repeat(41))), None);
    }

    #[test]
    fn join_links_need_https_or_a_private_network() {
        assert_eq!(parse_orca_link("orca://join?gateway=https://ai-gw.acme.dev"), join("https://ai-gw.acme.dev"));
        assert_eq!(
            parse_orca_link("orca://join?gateway=https%3A%2F%2Fai-gw.acme.dev%2Fteam%2F"),
            join("https://ai-gw.acme.dev/team")
        );
        assert_eq!(parse_orca_link("orca://join?gateway=https://gw.acme.dev:8443"), join("https://gw.acme.dev:8443"));
        assert_eq!(parse_orca_link("orca://join?gateway=http://127.0.0.1:8765"), join("http://127.0.0.1:8765"));
        assert_eq!(parse_orca_link("orca://join?gateway=http://localhost:4000"), join("http://localhost:4000"));
        assert_eq!(parse_orca_link("orca://join?gateway=http://10.1.2.3"), join("http://10.1.2.3"));
        assert_eq!(parse_orca_link("orca://join?gateway=http://172.20.0.5:80"), join("http://172.20.0.5"));
        assert_eq!(parse_orca_link("orca://join?gateway=http://192.168.1.20:4000"), join("http://192.168.1.20:4000"));
        assert_eq!(parse_orca_link("orca://join?gateway=http://[::1]:4000"), join("http://[::1]:4000"));
        assert_eq!(parse_orca_link("orca://join?gateway=http://[fd00::5]"), join("http://[fd00::5]"));
        for bad in [
            "orca://join",
            "orca://join?gateway=http://ai-gw.acme.dev",
            "orca://join?gateway=http://8.8.8.8",
            "orca://join?gateway=http://172.32.0.1",
            "orca://join?gateway=http://[2001:db8::1]",
            "orca://join?gateway=ftp://ai-gw.acme.dev",
            "orca://join?gateway=javascript:alert(1)",
            "orca://join?gateway=https://ai-gw.acme.dev/v1",
            "orca://join?gateway=https://bob:pw@ai-gw.acme.dev",
            "orca://join?gateway=https://ai-gw.acme.dev?key=sk-orca-0123456789abcdef",
            "orca://join?gateway=https://ai-gw.acme.dev#frag",
            "orca://join?gateway=https://ai-gw.acme.dev&key=sk-orca-0123456789abcdef",
            "orca://join?gateway=https://ai-gw.acme.dev/sk-orca-0123456789abcdefghij",
            "orca://join?gateway=https://",
        ] {
            assert_eq!(parse_orca_link(bad), None, "{bad}");
        }
        let long = format!("orca://join?gateway=https://gw.acme.dev/{}", "a/".repeat(1100));
        assert_eq!(parse_orca_link(&long), None);
    }

    #[test]
    fn setup_links_carry_agent_ids_and_a_budget_only() {
        assert_eq!(
            parse_orca_link("orca://setup?agents=claude-code,codex&budget=500"),
            Some(OrcaLink::Setup { agents: vec!["claude-code".into(), "codex".into()], budget_cents: Some(500) })
        );
        assert_eq!(
            parse_orca_link("orca://setup?budget=0&agents=codex"),
            Some(OrcaLink::Setup { agents: vec!["codex".into()], budget_cents: Some(0) })
        );
        assert_eq!(
            parse_orca_link("orca://setup?agents=codex,codex"),
            Some(OrcaLink::Setup { agents: vec!["codex".into()], budget_cents: None })
        );
        assert_eq!(
            parse_orca_link("orca://setup?budget=100000000"),
            Some(OrcaLink::Setup { agents: vec![], budget_cents: Some(100_000_000) })
        );
        for bad in [
            "orca://setup",
            "orca://setup?agents=",
            "orca://setup?agents=codex,",
            "orca://setup?agents=codex,,aider",
            "orca://setup?agents=Codex",
            "orca://setup?budget=100000001",
            "orca://setup?budget=-1",
            "orca://setup?budget=5.00",
            "orca://setup?budget=1e3",
            "orca://setup?budget=99999999999999999999999",
            "orca://setup?agents=codex&budget=500&key=sk-orca-0123456789abcdef",
            "orca://setup?agents=codex&api_key=x",
            "orca://setup?agents=codex&token=x",
        ] {
            assert_eq!(parse_orca_link(bad), None, "{bad}");
        }
        let many = (0..21).map(|i| format!("a{i}")).collect::<Vec<_>>().join(",");
        assert_eq!(parse_orca_link(&format!("orca://setup?agents={many}")), None);
    }

    #[test]
    fn nothing_that_looks_like_a_key_gets_through() {
        for bad in [
            "orca://connect?agent=sk-orca-0123456789abcdef",
            "orca://connect?agent=sk-ant-api03-abcdefgh",
            "orca://setup?agents=codex,sk-proj-abcdef0123456789",
            "orca://connect?agent=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "orca://join?gateway=https://AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6.example.com",
        ] {
            assert_eq!(parse_orca_link(bad), None, "{bad}");
        }
        assert!(looks_like_key("sk-orca-0123456789abcdef"));
        assert!(looks_like_key("ghp_0123456789abcdefABCDEF0123456789abcd"));
        assert!(!looks_like_key("claude-code"));
        assert!(!looks_like_key("ai-gw.acme.dev"));
        assert!(!looks_like_key("opencode"));
    }

    #[test]
    fn other_links_are_ignored() {
        for bad in [
            "",
            "orca:",
            "orca://",
            "orca://disconnect?agent=codex",
            "orca://Connect?agent=codex",
            "https://connect?agent=codex",
            "orcarouter://connect?agent=codex",
            "orca:connect?agent=codex",
            "orca://connect?agent=codex\n",
            "not a url",
        ] {
            assert_eq!(parse_orca_link(bad), None, "{bad:?}");
        }
        assert_eq!(parse_orca_link(&format!("orca://connect?agent=codex&{}", "x".repeat(5000))), None);
    }

    #[test]
    fn links_open_the_page_that_confirms_them_and_serialize_for_it() {
        assert_eq!(connect("codex").unwrap().window(), "panel");
        assert_eq!(join("https://gw.acme.dev").unwrap().window(), "panel");
        let setup = parse_orca_link("orca://setup?agents=codex&budget=500").unwrap();
        assert_eq!(setup.window(), "setup");
        assert_eq!(
            serde_json::to_value(&setup).unwrap(),
            json!({"action": "setup", "agents": ["codex"], "budget_cents": 500})
        );
        assert_eq!(serde_json::to_value(connect("codex").unwrap()).unwrap(), json!({"action": "connect", "agent": "codex"}));
        assert_eq!(
            serde_json::to_value(join("https://gw.acme.dev").unwrap()).unwrap(),
            json!({"action": "join", "gateway": "https://gw.acme.dev"})
        );
    }

    #[test]
    fn a_second_launch_with_a_link_is_not_a_tray_click() {
        let argv = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert!(argv_has_orca_link(&argv(&["/opt/orca/app", "orca://connect?agent=codex"])));
        assert!(argv_has_orca_link(&argv(&["app.exe", "ORCA://setup?budget=1"])));
        assert!(!argv_has_orca_link(&argv(&["/opt/orca/app"])));
        assert!(!argv_has_orca_link(&argv(&["/opt/orca/app", "--background"])));
    }

    #[test]
    fn the_savings_card_must_be_a_png() {
        let png = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13];
        let b64 = "iVBORw0KGgoAAAAN";
        assert_eq!(png_from_base64(b64).unwrap(), png.to_vec());
        assert_eq!(png_from_base64(&format!("data:image/png;base64,{b64}")).unwrap(), png.to_vec());
        assert!(png_from_base64("R0lGODlhAQABAAAAACw=").is_err(), "a GIF");
        assert!(png_from_base64("not base64!").is_err());
        assert!(png_from_base64("").is_err());
        let huge = "A".repeat(MAX_PNG_BASE64 + 4);
        assert!(png_from_base64(&huge).is_err());
    }

    // ── command-line tool ──

    const MAC_ENGINE: &str = "/Applications/OrcaRouter Lite.app/Contents/MacOS/orca-engine";

    fn mac_env() -> CliEnv {
        CliEnv {
            os: Os::Mac,
            engine: Some(MAC_ENGINE.into()),
            home: "/Users/ana".into(),
            path_var: "/usr/bin:/bin:/usr/sbin:/sbin".into(),
            appimage: false,
            system: Existing::Missing,
            system_dir_writable: false,
            user: Existing::Missing,
        }
    }

    fn linux_env() -> CliEnv {
        CliEnv {
            os: Os::Linux,
            engine: Some("/usr/bin/orca-engine".into()),
            home: "/home/ana".into(),
            path_var: "/home/ana/.local/bin:/usr/local/bin:/usr/bin".into(),
            ..mac_env()
        }
    }

    #[test]
    fn macos_links_into_usr_local_bin_with_a_password_prompt_then_falls_back_to_home() {
        assert_eq!(
            cli_plan(&mac_env()),
            CliPlan::Try(vec![
                CliStep::Link { link: "/usr/local/bin/orca".into(), admin: true },
                CliStep::Link { link: "/Users/ana/.local/bin/orca".into(), admin: false },
            ])
        );
        let writable = CliEnv { system_dir_writable: true, ..mac_env() };
        assert_eq!(
            cli_plan(&writable),
            CliPlan::Try(vec![
                CliStep::Link { link: "/usr/local/bin/orca".into(), admin: false },
                CliStep::Link { link: "/Users/ana/.local/bin/orca".into(), admin: false },
            ])
        );
        // A stale link from an earlier copy of the app is replaced.
        let stale = CliEnv { system: Existing::Stale, ..mac_env() };
        assert!(matches!(cli_plan(&stale), CliPlan::Try(steps) if steps.len() == 2));
    }

    #[test]
    fn macos_never_replaces_someone_elses_orca() {
        let other = CliEnv { system: Existing::Other, ..mac_env() };
        assert_eq!(
            cli_plan(&other),
            CliPlan::Try(vec![CliStep::Link { link: "/Users/ana/.local/bin/orca".into(), admin: false }])
        );
        let both = CliEnv { system: Existing::Other, user: Existing::Other, ..mac_env() };
        assert_eq!(
            cli_plan(&both),
            CliPlan::Refuse(
                "There's already a different orca command at /usr/local/bin/orca. Remove it, then try again.".into()
            )
        );
    }

    #[test]
    fn macos_needs_the_app_in_a_real_folder() {
        for engine in [
            "/private/var/folders/x/T/AppTranslocation/1234/d/OrcaRouter Lite.app/Contents/MacOS/orca-engine",
            "/Volumes/OrcaRouter Lite/OrcaRouter Lite.app/Contents/MacOS/orca-engine",
        ] {
            let env = CliEnv { engine: Some(engine.into()), ..mac_env() };
            assert_eq!(
                cli_plan(&env),
                CliPlan::Refuse(
                    "Move OrcaRouter Lite to your Applications folder, open it from there, then try again.".into()
                ),
                "{engine}"
            );
        }
    }

    #[test]
    fn an_installed_link_is_reported_not_redone() {
        let env = CliEnv { system: Existing::Current, ..mac_env() };
        assert_eq!(cli_plan(&env), CliPlan::Already { at: "/usr/local/bin/orca".into() });
        let env = CliEnv { user: Existing::Current, ..linux_env() };
        assert_eq!(cli_plan(&env), CliPlan::Already { at: "/home/ana/.local/bin/orca".into() });
    }

    #[test]
    fn linux_links_into_the_home_folder() {
        assert_eq!(
            cli_plan(&linux_env()),
            CliPlan::Try(vec![CliStep::Link { link: "/home/ana/.local/bin/orca".into(), admin: false }])
        );
        let other = CliEnv { user: Existing::Other, ..linux_env() };
        assert_eq!(
            cli_plan(&other),
            CliPlan::Refuse(
                "There's already a different orca command at ~/.local/bin/orca. Remove it, then try again.".into()
            )
        );
        let appimage = CliEnv { appimage: true, engine: Some("/tmp/.mount_Orca123/usr/bin/orca-engine".into()), ..linux_env() };
        assert_eq!(
            cli_plan(&appimage),
            CliPlan::Refuse(
                "The AppImage can't add the orca command, because it runs from a temporary folder. \
                 Install the .deb package to get it."
                    .into()
            )
        );
    }

    #[test]
    fn a_build_without_the_engine_has_nothing_to_install() {
        for env in [CliEnv { engine: None, ..mac_env() }, CliEnv { engine: None, ..linux_env() }] {
            assert_eq!(
                cli_plan(&env),
                CliPlan::Refuse("This build of OrcaRouter Lite doesn't include the orca command.".into())
            );
        }
    }

    #[test]
    fn windows_adds_a_shim_folder_to_the_user_path() {
        let env = CliEnv {
            os: Os::Windows,
            engine: Some(r"C:\Users\ana\AppData\Local\OrcaRouter Lite\orca-engine.exe".into()),
            home: r"C:\Users\ana".into(),
            path_var: String::new(),
            ..mac_env()
        };
        assert_eq!(
            cli_plan(&env),
            CliPlan::Try(vec![CliStep::WindowsShim {
                dir: r"C:\Users\ana\.orcarouter-lite\bin".into(),
                shim: "@echo off\r\n\"%USERPROFILE%\\AppData\\Local\\OrcaRouter Lite\\orca-engine.exe\" %*\r\n".into(),
            }])
        );
        // cmd expands %VAR% even inside quotes.
        assert_eq!(windows_shim(r"C:\100%\orca-engine.exe", r"C:\Users\ana"), "@echo off\r\n\"C:\\100%%\\orca-engine.exe\" %*\r\n");
    }

    #[test]
    fn the_user_path_gains_the_folder_once() {
        let dir = r"C:\Users\ana\.orcarouter-lite\bin";
        assert_eq!(path_with_entry("", dir), Some(dir.to_string()));
        assert_eq!(
            path_with_entry(r"%USERPROFILE%\bin;C:\tools;", dir),
            Some(format!(r"%USERPROFILE%\bin;C:\tools;{dir}"))
        );
        assert_eq!(path_with_entry(&format!(r"C:\tools;{dir}"), dir), None);
        assert_eq!(path_with_entry(r"C:\tools;c:\users\ANA\.orcarouter-lite\bin\", dir), None);
        assert_eq!(path_with_entry(r"%USERPROFILE%\.orcarouter-lite\bin", dir), Some(format!(r"%USERPROFILE%\.orcarouter-lite\bin;{dir}")));
    }

    #[test]
    fn existing_commands_are_classified_by_where_they_point() {
        assert_eq!(classify_existing(false, None, MAC_ENGINE), Existing::Missing);
        assert_eq!(classify_existing(true, Some(MAC_ENGINE), MAC_ENGINE), Existing::Current);
        assert_eq!(classify_existing(true, Some("/Users/ana/Downloads/OrcaRouter Lite.app/Contents/MacOS/orca-engine"), MAC_ENGINE), Existing::Stale);
        assert_eq!(classify_existing(true, Some("/opt/homebrew/bin/orca"), MAC_ENGINE), Existing::Other);
        assert_eq!(classify_existing(true, None, MAC_ENGINE), Existing::Other); // a real file
    }

    #[test]
    fn the_outcome_is_said_in_plain_words() {
        assert_eq!(
            cli_installed(&mac_env(), "/usr/local/bin/orca"),
            ("Command-line tool installed".to_string(), "Installed. Open a new terminal and run orca status.".to_string())
        );
        assert_eq!(
            cli_installed(&linux_env(), "/home/ana/.local/bin/orca").1,
            "Installed. Open a new terminal and run orca status."
        );
        let off_path = CliEnv { path_var: "/usr/bin:/bin".into(), ..linux_env() };
        assert_eq!(
            cli_installed(&off_path, "/home/ana/.local/bin/orca").1,
            "Installed at ~/.local/bin/orca, which isn't on your PATH. \
             Add ~/.local/bin to your PATH, then open a new terminal and run orca status."
        );
        assert_eq!(
            cli_installed(&mac_env(), "/Users/ana/.local/bin/orca").1,
            "Installed at ~/.local/bin/orca, which isn't on your PATH. \
             Add ~/.local/bin to your PATH, then open a new terminal and run orca status."
        );
        let trailing = CliEnv { path_var: "/usr/bin:/home/ana/.local/bin/".into(), ..linux_env() };
        assert_eq!(cli_installed(&trailing, "/home/ana/.local/bin/orca").1, "Installed. Open a new terminal and run orca status.");
    }

    #[test]
    fn the_admin_prompt_quotes_paths_for_applescript_and_the_shell() {
        assert_eq!(
            admin_link_script(MAC_ENGINE, "/usr/local/bin/orca"),
            "do shell script \"mkdir -p '/usr/local/bin' && ln -sf '/Applications/OrcaRouter Lite.app/Contents/MacOS/orca-engine' '/usr/local/bin/orca'\" \
             with prompt \"OrcaRouter Lite wants to add the orca command to /usr/local/bin.\" with administrator privileges"
        );
        let odd = admin_link_script("/Apps/O'Brien \"x\" \\.app/orca-engine", "/usr/local/bin/orca");
        assert!(odd.contains(r#"'/Apps/O'\\''Brien \"x\" \\.app/orca-engine'"#), "{odd}");
    }

    #[test]
    fn autostart_changes_only_when_it_differs() {
        assert_eq!(autostart_change(true, false), Some(true));
        assert_eq!(autostart_change(false, true), Some(false));
        assert_eq!(autostart_change(true, true), None);
        assert_eq!(autostart_change(false, false), None);
    }

    // ── review fixes ──

    #[test]
    fn a_non_ascii_argument_is_not_a_link_and_never_panics() {
        let argv = vec!["orca".to_string(), "/home/é".to_string(), "ünïcødé-arg".to_string()];
        assert!(!argv_has_orca_link(&argv));
        assert!(argv_has_orca_link(&["orca".into(), "ORCA://connect?agent=codex".into()]));
    }

    #[test]
    fn the_shim_names_the_profile_by_variable_so_cmd_can_read_it() {
        // cmd reads a batch file in the console's codepage, not UTF-8, so a
        // profile like C:\Users\José would come out garbled.
        assert_eq!(
            windows_shim(r"C:\Users\José\AppData\Local\OrcaRouter Lite\orca-engine.exe", r"C:\Users\José"),
            "@echo off\r\n\"%USERPROFILE%\\AppData\\Local\\OrcaRouter Lite\\orca-engine.exe\" %*\r\n"
        );
        assert_eq!(
            windows_shim(r"C:\Program Files\OrcaRouter Lite\orca-engine.exe", r"C:\Users\ana"),
            "@echo off\r\n\"C:\\Program Files\\OrcaRouter Lite\\orca-engine.exe\" %*\r\n"
        );
    }

    #[test]
    fn only_a_missing_path_value_counts_as_empty() {
        assert_eq!(user_path(PathRead::Found("C:\\a".into())), Ok("C:\\a".into()));
        assert_eq!(user_path(PathRead::NotFound), Ok(String::new()));
        // Any other failure must stop the install: treating it as empty
        // would overwrite the user's whole PATH.
        assert!(user_path(PathRead::Failed("access denied".into())).is_err());
    }

    #[test]
    fn the_clipboard_is_cleared_only_if_it_still_holds_the_saved_key() {
        let saved = "sk-orca-abcdefghijklmnop1234";
        assert!(should_clear_clipboard(&format!(" {saved}\n"), saved));
        assert!(!should_clear_clipboard("sk-orca-zzzzzzzzzzzzzzzzzzzz", saved));
        assert!(!should_clear_clipboard("hello", saved));
        assert!(!should_clear_clipboard("", ""));
    }

    #[test]
    fn a_link_waits_two_minutes_at_most() {
        use std::time::Duration;
        assert!(link_is_fresh(Duration::from_secs(5)));
        assert!(link_is_fresh(Duration::from_secs(119)));
        assert!(!link_is_fresh(Duration::from_secs(121)));
    }
}
