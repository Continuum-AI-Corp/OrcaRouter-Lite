//! OrcaRouter Lite menu-bar app.
//!
//! The app is a thin native shell: it starts the local engine, shows today's
//! spend in the menu bar, sends budget and failover notifications, and opens
//! the panel, setup and dashboard pages that the engine itself serves.

pub mod engine;
pub mod install;
pub mod logic;

use std::sync::{Arc, Mutex};
use std::time::Duration;

use engine::Engine;
use tauri::ipc::CapabilityBuilder;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_clipboard_manager::ClipboardExt;
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_positioner::{Position, WindowExt};

const TRAY_ID: &str = "orca";
const POLL: Duration = Duration::from_secs(20);

#[derive(Default)]
struct AppState {
    engine: Mutex<Option<Arc<Engine>>>,
    error: Mutex<Option<String>>,
    // When the panel last hid itself on blur. A tray click that closes the
    // panel blurs it first, so a show request right after is ignored.
    panel_hidden_at: Mutex<Option<std::time::Instant>>,
    // Built with the updater's public key: updates install in place.
    updates_installable: bool,
    /// The last orca:// link and when it arrived (dropped after LINK_TTL_SECS).
    pending_link: Mutex<Option<(std::time::Instant, logic::OrcaLink)>>,
}

fn engine(state: &AppState) -> Result<Arc<Engine>, String> {
    if let Some(e) = state.engine.lock().unwrap().clone() {
        return Ok(e);
    }
    Err(state.error.lock().unwrap().clone().unwrap_or_else(|| "The Orca engine is still starting.".into()))
}

/// Minutes east of UTC, the same convention the panel's JavaScript sends.
pub fn tz_offset_minutes() -> i64 {
    i64::from(chrono::Local::now().offset().local_minus_utc()) / 60
}

/// Inject the app key and refuse to navigate anywhere but the engine.
fn engine_window<'a>(
    app: &'a AppHandle,
    label: &str,
    eng: &Engine,
    path: &str,
    init: String,
) -> tauri::Result<WebviewWindowBuilder<'a, tauri::Wry, AppHandle>> {
    let url = format!("{}{}", eng.base_url, path);
    let origin = eng.base_url.clone();
    let app2 = app.clone();
    Ok(WebviewWindowBuilder::new(app, label, WebviewUrl::External(url.parse().expect("valid engine url")))
        .initialization_script(init)
        .on_navigation(move |u| {
            let ok = u.as_str().starts_with(&format!("{origin}/"));
            if !ok && (u.scheme() == "https" || u.scheme() == "http") {
                let _ = app2.opener().open_url(u.as_str(), None::<&str>);
            }
            ok
        }))
}

fn key_script(eng: &Engine) -> String {
    // Only the app's own pages under /desktop/ get the key.
    format!(
        "if (location.origin === {origin} && location.pathname.startsWith('/desktop/')) {{ window.__ORCA__ = {{ key: {key} }}; }}",
        origin = serde_json::to_string(&eng.base_url).unwrap(),
        key = serde_json::to_string(&eng.key()).unwrap(),
    )
}

/// A click on the tray icon: show the panel, or hide it if it's open.
fn show_panel(app: &AppHandle) {
    panel(app, true);
}

/// Show the panel; `toggle` hides it instead when it's already open.
fn panel(app: &AppHandle, toggle: bool) {
    let state = app.state::<AppState>();
    if let Some(t) = *state.panel_hidden_at.lock().unwrap() {
        if toggle && t.elapsed() < Duration::from_millis(300) {
            return; // this click is the one that just closed the panel
        }
    }
    let eng = match engine(&state) {
        Ok(e) => e,
        Err(msg) => {
            let _ = app.notification().builder().title("Orca isn't ready yet").body(msg).show();
            return;
        }
    };
    let win: WebviewWindow = match app.get_webview_window("panel") {
        Some(w) => w,
        None => {
            let built = engine_window(app, "panel", &eng, "/desktop/panel.html", key_script(&eng)).and_then(|b| {
                b.title("OrcaRouter Lite")
                    .inner_size(360.0, 640.0)
                    // Resizable so GTK honours set_size from resize_panel;
                    // without decorations there is no handle to drag.
                    .resizable(true)
                    .decorations(false)
                    .always_on_top(true)
                    .skip_taskbar(true)
                    .visible(false)
                    .build()
            });
            match built {
                Ok(w) => {
                    let handle = w.clone();
                    let app2 = app.clone();
                    w.on_window_event(move |e| {
                        if let WindowEvent::Focused(false) = e {
                            let _ = handle.hide();
                            *app2.state::<AppState>().panel_hidden_at.lock().unwrap() = Some(std::time::Instant::now());
                        }
                    });
                    w
                }
                Err(_) => return,
            }
        }
    };
    if win.is_visible().unwrap_or(false) {
        if toggle {
            let _ = win.hide();
        } else {
            let _ = win.set_focus();
        }
        return;
    }
    // TrayCenter sits above a bottom taskbar (Windows) and below a top menu
    // bar (macOS), flipping to fit the screen.
    if win.move_window(Position::TrayCenter).is_err() {
        let _ = win.move_window(Position::TopRight);
    }
    let _ = win.show();
    let _ = win.set_focus();
}

fn open_window(app: &AppHandle, label: &str, path: &str, title: &str, size: (f64, f64), extra_init: &str) -> Result<(), String> {
    let state = app.state::<AppState>();
    let eng = engine(&state)?;
    if let Some(w) = app.get_webview_window(label) {
        let _ = w.show();
        let _ = w.set_focus();
        return Ok(());
    }
    let init = if path.starts_with("/desktop/") {
        format!("{}\n{}", key_script(&eng), extra_init)
    } else {
        extra_init.to_string()
    };
    engine_window(app, label, &eng, path, init)
        .and_then(|b| b.title(title).inner_size(size.0, size.1).min_inner_size(480.0, 560.0).center().build())
        .map(|_| ())
        .map_err(|e| e.to_string())
}

/// Every native command checks its caller: only the app's own pages under
/// /desktop/ on the engine's origin (Tauri's remote capability is per origin).
fn guard(window: &WebviewWindow) -> Result<(), String> {
    let state = window.app_handle().state::<AppState>();
    let eng = engine(&state)?;
    let url = window.url().map_err(|e| e.to_string())?;
    if logic::is_app_page(url.as_str(), &eng.base_url) {
        Ok(())
    } else {
        Err("Not allowed from this page.".into())
    }
}

fn dashboard_window(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<AppState>();
    let eng = engine(&state)?;
    // The dashboard reads its key from localStorage on the same origin.
    let seed = format!(
        "if (location.origin === {o}) {{ try {{ localStorage.setItem('orca-lite-api-key', {k}); }} catch (e) {{}} }}",
        o = serde_json::to_string(&eng.base_url).unwrap(),
        k = serde_json::to_string(&eng.key()).unwrap(),
    );
    open_window(app, "dashboard", "/", "OrcaRouter Lite", (1200.0, 820.0), &seed)
}

fn setup_window(app: &AppHandle) -> Result<(), String> {
    if let Some(p) = app.get_webview_window("panel") {
        let _ = p.hide();
    }
    open_window(app, "setup", "/desktop/setup.html", "Set up OrcaRouter Lite", (600.0, 860.0), "")
}

/// `guard`, and the caller must be this one window.
fn guard_window(window: &WebviewWindow, label: &str) -> Result<(), String> {
    guard(window)?;
    if window.label() == label {
        Ok(())
    } else {
        Err("Not allowed from this page.".into())
    }
}

/// H1: an OrcaRouter key the user copied, offered by setup when its window
/// regains focus. Only setup may ask, only while it has focus, and only text
/// shaped like an OrcaRouter key comes back; anything else stays private.
#[tauri::command]
fn clipboard_orca_key(window: WebviewWindow) -> Result<Option<String>, String> {
    guard_window(&window, "setup")?;
    if !window.is_focused().unwrap_or(false) {
        return Ok(None);
    }
    let text = window.app_handle().clipboard().read_text().unwrap_or_default();
    Ok(logic::orca_key_from_clipboard(&text))
}

/// H1: after the key is saved, clear it from the clipboard, but only if the
/// clipboard still holds it (never something copied since).
#[tauri::command]
fn clear_clipboard(window: WebviewWindow, key: String) -> Result<bool, String> {
    guard_window(&window, "setup")?;
    let clipboard = window.app_handle().clipboard();
    let text = clipboard.read_text().unwrap_or_default();
    if logic::should_clear_clipboard(&text, &key) {
        clipboard.clear().map_err(|e| e.to_string())?;
        return Ok(true);
    }
    Ok(false)
}

/// V2: put the savings card (a PNG, base64) on the clipboard.
#[tauri::command]
fn copy_png(window: WebviewWindow, base64: String) -> Result<(), String> {
    guard_window(&window, "panel")?;
    let bytes = logic::png_from_base64(&base64)?;
    let image = tauri::image::Image::from_bytes(&bytes).map_err(|_| "That image couldn't be read.".to_string())?;
    window.app_handle().clipboard().write_image(&image).map_err(|e| e.to_string())
}

/// V3: the orca:// link waiting for this page, if any (a page that opened
/// after the link arrived missed its `orca-link` event). Taking it clears it.
#[tauri::command]
fn take_pending_link(window: WebviewWindow) -> Result<Option<logic::OrcaLink>, String> {
    guard(&window)?;
    let state = window.app_handle().state::<AppState>();
    let mut pending = state.pending_link.lock().unwrap();
    if pending.as_ref().is_some_and(|(at, _)| !logic::link_is_fresh(at.elapsed())) {
        *pending = None;
    }
    if pending.as_ref().is_some_and(|(_, l)| l.window() == window.label()) {
        return Ok(pending.take().map(|(_, l)| l));
    }
    Ok(None)
}

/// V3: an orca:// link arrived. Validate it, keep it for its page, open that
/// page and tell it. Nothing happens until the user confirms on the page.
fn handle_link(app: &AppHandle, raw: &str) {
    let Some(link) = logic::parse_orca_link(raw) else {
        return; // anything else is ignored
    };
    *app.state::<AppState>().pending_link.lock().unwrap() = Some((std::time::Instant::now(), link));
    if engine(&app.state::<AppState>()).is_err() {
        return; // start_engine opens it once the engine is up
    }
    let h = app.clone();
    let _ = app.run_on_main_thread(move || open_pending_link(&h));
}

/// Open the page for the pending link, and send it the `orca-link` event
/// if it's already loaded. The event's detail is the link as JSON.
fn open_pending_link(app: &AppHandle) {
    let Some((_, link)) = app.state::<AppState>().pending_link.lock().unwrap().clone() else {
        return;
    };
    let label = link.window();
    if label == "setup" {
        let _ = setup_window(app);
    } else {
        panel(app, false);
    }
    if let Some(w) = app.get_webview_window(label) {
        let detail = serde_json::to_string(&link).unwrap_or_else(|_| "null".into());
        let _ = w.eval(format!("window.dispatchEvent(new CustomEvent('orca-link', {{ detail: {detail} }}));"));
    }
}

/// D8: copy the engine's diagnostics report and say so.
fn copy_diagnostics(app: &AppHandle) {
    let from_engine = engine(&app.state::<AppState>()).ok().and_then(|e| e.diagnostics().ok());
    let text = from_engine.or_else(Engine::cli_diagnostics);
    let (title, body) = match text.map(|t| app.clipboard().write_text(t)) {
        Some(Ok(())) => (
            "Diagnostics copied",
            "Paste them into a GitHub issue. Keys and prompts were left out.".to_string(),
        ),
        Some(Err(e)) => ("Couldn't copy diagnostics", format!("The clipboard isn't available: {e}")),
        None => (
            "Couldn't copy diagnostics",
            "The Orca engine isn't responding. Its log is at ~/.orcarouter-lite/engine.log.".to_string(),
        ),
    };
    let _ = app.notification().builder().title(title).body(body).show();
}

/// D6: put the `orca` command on the PATH and say what happened.
fn install_cli(app: &AppHandle) {
    let (title, body) = install::install();
    let _ = app.notification().builder().title(title).body(body).show();
}

#[tauri::command]
fn open_dashboard(window: WebviewWindow) -> Result<(), String> {
    guard(&window)?;
    dashboard_window(window.app_handle())
}

#[tauri::command]
fn open_setup(window: WebviewWindow) -> Result<(), String> {
    guard(&window)?;
    setup_window(window.app_handle())
}

#[tauri::command]
fn close_setup(window: WebviewWindow) -> Result<(), String> {
    guard(&window)?;
    if let Some(w) = window.app_handle().get_webview_window("setup") {
        let _ = w.close();
    }
    Ok(())
}

#[tauri::command]
fn finish_setup(window: WebviewWindow) -> Result<(), String> {
    guard(&window)?;
    let state = window.app_handle().state::<AppState>();
    let eng = engine(&state)?;
    std::fs::write(eng.home.join("setup.json"), b"{\"done\": true}\n").map_err(|e| e.to_string())
}

/// Make the OS login item match the "start at login" setting (on unless the
/// user turned it off). Runs once the engine is up and after setup saves.
fn sync_start_at_login(app: &AppHandle, eng: &engine::Engine) {
    use tauri_plugin_autostart::ManagerExt;
    let Ok(settings) = eng.settings() else {
        return;
    };
    let launcher = app.autolaunch();
    let enabled = launcher.is_enabled().unwrap_or(false);
    let result = match logic::autostart_change(logic::wants_start_at_login(&settings), enabled) {
        Some(true) => launcher.enable(),
        Some(false) => launcher.disable(),
        None => Ok(()),
    };
    if let Err(e) = result {
        eprintln!("orca: start at login: {e}");
    }
}

#[tauri::command]
fn apply_start_at_login(window: WebviewWindow) -> Result<(), String> {
    guard(&window)?;
    let app = window.app_handle().clone();
    let state = app.state::<AppState>();
    let eng = engine(&state)?;
    std::thread::spawn(move || sync_start_at_login(&app, &eng));
    Ok(())
}

#[tauri::command]
fn open_external(window: WebviewWindow, url: String) -> Result<(), String> {
    guard(&window)?;
    if !url.starts_with("https://") {
        return Err("Only https links can be opened.".into());
    }
    window.app_handle().opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

/// Whether this build can install updates itself (it carries the updater's
/// public key). Otherwise the panel links to the release page.
#[tauri::command]
fn can_install_updates(window: WebviewWindow) -> Result<bool, String> {
    guard(&window)?;
    Ok(window.app_handle().state::<AppState>().updates_installable)
}

/// Download the latest release, check its signature against the public key
/// built into this app, install it and restart. The updater plugin does the
/// verification; nothing unsigned is ever installed.
#[tauri::command]
async fn install_update(window: WebviewWindow) -> Result<(), String> {
    use tauri_plugin_updater::UpdaterExt;

    guard(&window)?;
    let app = window.app_handle().clone();
    if !app.state::<AppState>().updates_installable {
        return Err("This build can't install updates itself; download the new version instead.".into());
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| format!("Couldn't check for the update: {e}"))?
        .ok_or_else(|| "You already have the latest version.".to_string())?;
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|e| format!("Couldn't install the update: {e}"))?;
    app.restart();
}

#[tauri::command]
fn quit_app(window: WebviewWindow) -> Result<(), String> {
    guard(&window)?;
    window.app_handle().exit(0);
    Ok(())
}

/// The panel reports its content height so the window has no dead space.
#[tauri::command]
fn resize_panel(window: WebviewWindow, height: f64) -> Result<(), String> {
    guard(&window)?;
    let h = height.clamp(360.0, 680.0);
    if let Some(w) = window.app_handle().get_webview_window("panel") {
        w.set_size(tauri::LogicalSize::new(360.0, h)).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn start_engine(app: AppHandle) {
    std::thread::spawn(move || {
        let state = app.state::<AppState>();
        match Engine::start() {
            Ok(eng) => {
                let eng = Arc::new(eng);
                // Let only the engine's own pages call the commands above.
                // Only the app's own pages, never the dashboard or other paths.
                let cap = CapabilityBuilder::new("engine-pages")
                    .remote(format!("{}/*", eng.base_url))
                    .windows(["panel", "setup"])
                    .permission("allow-open-dashboard")
                    .permission("allow-open-setup")
                    .permission("allow-close-setup")
                    .permission("allow-finish-setup")
                    .permission("allow-open-external")
                    .permission("allow-apply-start-at-login")
                    .permission("allow-quit-app")
                    .permission("allow-resize-panel")
                    .permission("allow-can-install-updates")
                    .permission("allow-install-update")
                    .permission("allow-take-pending-link");
                // The clipboard key check is setup's alone; the card copy the panel's.
                let setup_only = CapabilityBuilder::new("engine-setup")
                    .remote(format!("{}/*", eng.base_url))
                    .windows(["setup"])
                    .permission("allow-clipboard-orca-key")
                    .permission("allow-clear-clipboard");
                let panel_only = CapabilityBuilder::new("engine-panel")
                    .remote(format!("{}/*", eng.base_url))
                    .windows(["panel"])
                    .permission("allow-copy-png");
                for cap in [cap, setup_only, panel_only] {
                    if let Err(e) = app.add_capability(cap) {
                        eprintln!("orca: capability: {e}");
                    }
                }
                let first_run = !eng.home.join("setup.json").exists();
                *state.engine.lock().unwrap() = Some(eng.clone());
                // Opened by hand (not at login): show something, so the user
                // sees the app start instead of a silent menu-bar icon.
                let launched_by_user = !std::env::args().any(|a| a == "--background");
                let h = app.clone();
                let link_waiting = state.pending_link.lock().unwrap().is_some();
                if first_run {
                    let _ = app.run_on_main_thread(move || {
                        let _ = setup_window(&h);
                    });
                } else if link_waiting {
                    // Opened by an orca:// link: show the page that confirms it.
                    let _ = app.run_on_main_thread(move || open_pending_link(&h));
                } else if launched_by_user {
                    let _ = app.run_on_main_thread(move || show_panel(&h));
                }
                {
                    let (h, e) = (app.clone(), eng.clone());
                    std::thread::spawn(move || sync_start_at_login(&h, &e));
                }
                poll(app.clone(), eng);
            }
            Err(msg) => {
                *state.error.lock().unwrap() = Some(msg.clone());
                set_tray(&app, "!", &msg);
                let _ = app.notification().builder().title("Orca couldn't start").body(msg).show();
            }
        }
    });
}

fn set_tray(app: &AppHandle, title: &str, tooltip: &str) {
    if let Some(tray) = app.tray_by_id(TRAY_ID) {
        let _ = tray.set_title(Some(title));
        let _ = tray.set_tooltip(Some(tooltip));
    }
}

/// The Monday summary. The last week it covered is kept in the Orca folder
/// so a restart doesn't repeat it.
fn weekly_digest(app: &AppHandle, snap: &logic::Snapshot) {
    let path = engine::orca_home().join("weekly-digest");
    let last = std::fs::read_to_string(&path).ok().map(|s| s.trim().to_string());
    let now = chrono::Local::now().naive_local();
    match logic::weekly_digest(now, last.as_deref(), snap) {
        logic::Digest::Nothing => {}
        logic::Digest::Record { week } => {
            let _ = std::fs::write(&path, week);
        }
        logic::Digest::Send { week, alert } => {
            // Record first: a notification that fails to show isn't retried every 30 s.
            if std::fs::write(&path, week).is_ok() {
                let _ = app.notification().builder().title(alert.title()).body(alert.body()).show();
            }
        }
    }
}

/// One notification per new release; the version announced last is kept in
/// the Orca folder so restarts don't repeat it.
fn announce_update(app: &AppHandle, snap: &logic::Snapshot) {
    let path = engine::orca_home().join("update-announced");
    let last = std::fs::read_to_string(&path).ok().map(|s| s.trim().to_string());
    if let Some((version, alert)) = logic::update_notice(last.as_deref(), snap) {
        if std::fs::write(&path, version).is_ok() {
            let _ = app.notification().builder().title(alert.title()).body(alert.body()).show();
        }
    }
}

/// D5, H2 and H4. What was announced is kept in notified.json so a restart
/// doesn't repeat it.
fn watch_notices(app: &AppHandle, summary: &serde_json::Value) {
    let path = engine::orca_home().join("notified.json");
    let prev = std::fs::read_to_string(&path).map(|t| logic::notified_from_json(&t)).unwrap_or_default();
    let today = chrono::Local::now().date_naive();
    let (next, alerts) = logic::notices(today, &prev, &logic::parse_watch(summary));
    // Record first: a notification that fails to show isn't retried every poll.
    if next != prev && std::fs::write(&path, logic::notified_to_json(&next)).is_err() {
        return;
    }
    for alert in alerts {
        let _ = app.notification().builder().title(alert.title()).body(alert.body()).show();
    }
}

fn poll(app: AppHandle, mut eng: Arc<Engine>) {
    let mut prev: Option<logic::Snapshot> = None;
    let mut failures = 0u32;
    let mut last_restart: Option<std::time::Instant> = None;
    loop {
        let summary = eng.summary().ok();
        match summary.as_ref().and_then(logic::parse_summary) {
            Some(snap) => {
                failures = 0;
                let title = logic::tray_title(&snap);
                set_tray(&app, &title, &format!("OrcaRouter Lite · {title} today"));
                for alert in logic::alerts(prev.as_ref(), &snap) {
                    let _ = app.notification().builder().title(alert.title()).body(alert.body()).show();
                }
                weekly_digest(&app, &snap);
                if let Some(v) = &summary {
                    watch_notices(&app, v);
                }
                announce_update(&app, &snap);
                prev = Some(snap);
            }
            None => {
                failures += 1;
                if failures >= 3 {
                    // Don't keep showing a number that may be stale.
                    set_tray(&app, "—", "OrcaRouter Lite: the engine isn't responding");
                }
                let may_restart = last_restart.map_or(true, |t| t.elapsed() > Duration::from_secs(60));
                if eng.exited() && may_restart {
                    last_restart = Some(std::time::Instant::now());
                    if let Ok(fresh) = Engine::start() {
                        let fresh = Arc::new(fresh);
                        *app.state::<AppState>().engine.lock().unwrap() = Some(fresh.clone());
                        eng = fresh;
                        failures = 0;
                    }
                }
            }
        }
        std::thread::sleep(POLL);
    }
}

pub fn run() {
    let context = tauri::generate_context!();
    let plugins = serde_json::Value::Object(context.config().plugins.0.clone().into_iter().collect());
    let updates_installable = logic::updates_installable(&plugins);

    let mut builder = tauri::Builder::default()
        // First: a second launch hands over (with the deep-link feature, its
        // orca:// link goes to the deep-link plugin) and exits.
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            if !logic::argv_has_orca_link(&argv) {
                show_panel(app);
            }
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_positioner::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--background"]),
        ));
    if updates_installable {
        // Without a public key the plugin refuses to start, so it's only
        // loaded in builds that have one.
        builder = builder.plugin(tauri_plugin_updater::Builder::new().build());
    }
    let app = builder
        .manage(AppState { updates_installable, ..AppState::default() })
        .invoke_handler(tauri::generate_handler![
            open_dashboard,
            open_setup,
            close_setup,
            finish_setup,
            open_external,
            apply_start_at_login,
            quit_app,
            resize_panel,
            can_install_updates,
            install_update,
            clipboard_orca_key,
            clear_clipboard,
            copy_png,
            take_pending_link
        ])
        .setup(|app| {
            // A menu-bar app: no Dock icon on macOS.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            let open = MenuItem::with_id(app, "open", "Show spend", true, None::<&str>)?;
            let dash = MenuItem::with_id(app, "dashboard", "Open dashboard", true, None::<&str>)?;
            let setup = MenuItem::with_id(app, "setup", "Setup…", true, None::<&str>)?;
            let cli = MenuItem::with_id(app, "cli", "Install command-line tool…", true, None::<&str>)?;
            let diag = MenuItem::with_id(app, "diagnostics", "Copy diagnostics", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit OrcaRouter Lite", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &dash, &setup, &cli, &diag, &sep, &quit])?;

            TrayIconBuilder::with_id(TRAY_ID)
                .icon(tauri::image::Image::from_bytes(include_bytes!("../icons/tray.png"))?)
                .icon_as_template(true)
                .title("…")
                .tooltip("OrcaRouter Lite is starting")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    tauri_plugin_positioner::on_tray_event(tray.app_handle(), &event);
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        show_panel(tray.app_handle());
                    }
                })
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_panel(app),
                    "dashboard" => {
                        let _ = dashboard_window(app);
                    }
                    "setup" => {
                        let _ = setup_window(app);
                    }
                    "cli" => {
                        let h = app.clone();
                        std::thread::spawn(move || install_cli(&h));
                    }
                    "diagnostics" => {
                        let h = app.clone();
                        std::thread::spawn(move || copy_diagnostics(&h));
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // orca:// links: while running (macOS, and second launches on
            // Windows and Linux) and the one that started the app, if any.
            // Installers register the scheme; an AppImage or a dev build
            // registers it here.
            #[cfg(target_os = "linux")]
            if std::env::var_os("APPIMAGE").is_some() || cfg!(debug_assertions) {
                let _ = app.deep_link().register_all();
            }
            let h = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                for url in event.urls() {
                    handle_link(&h, url.as_str());
                }
            });
            if let Ok(Some(urls)) = app.deep_link().get_current() {
                for url in urls {
                    handle_link(app.handle(), url.as_str());
                }
            }

            start_engine(app.handle().clone());
            Ok(())
        })
        .build(context)
        .expect("error while building OrcaRouter Lite");

    app.run(|app, event| match event {
        // Closing the last window keeps the menu-bar app running.
        RunEvent::ExitRequested { code: None, api, .. } => api.prevent_exit(),
        RunEvent::Exit => {
            if let Some(eng) = app.state::<AppState>().engine.lock().unwrap().clone() {
                eng.stop();
            }
        }
        _ => {}
    });
}
