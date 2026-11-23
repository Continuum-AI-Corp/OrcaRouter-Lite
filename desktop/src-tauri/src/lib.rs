//! OrcaRouter Lite menu-bar app.
//!
//! The app is a thin native shell: it starts the local engine, shows today's
//! spend in the menu bar, sends budget and failover notifications, and opens
//! the panel, setup and dashboard pages that the engine itself serves.

pub mod engine;
pub mod logic;

use std::sync::{Arc, Mutex};
use std::time::Duration;

use engine::Engine;
use tauri::ipc::CapabilityBuilder;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent};
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

fn show_panel(app: &AppHandle) {
    let state = app.state::<AppState>();
    if let Some(t) = *state.panel_hidden_at.lock().unwrap() {
        if t.elapsed() < Duration::from_millis(300) {
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
        let _ = win.hide();
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

#[tauri::command]
fn open_external(window: WebviewWindow, url: String) -> Result<(), String> {
    guard(&window)?;
    if !url.starts_with("https://") {
        return Err("Only https links can be opened.".into());
    }
    window.app_handle().opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
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
                    .permission("allow-quit-app")
                    .permission("allow-resize-panel");
                if let Err(e) = app.add_capability(cap) {
                    eprintln!("orca: capability: {e}");
                }
                let first_run = !eng.home.join("setup.json").exists();
                *state.engine.lock().unwrap() = Some(eng.clone());
                // Opened by hand (not at login): show something, so the user
                // sees the app start instead of a silent menu-bar icon.
                let launched_by_user = !std::env::args().any(|a| a == "--background");
                let h = app.clone();
                if first_run {
                    let _ = app.run_on_main_thread(move || {
                        let _ = setup_window(&h);
                    });
                } else if launched_by_user {
                    let _ = app.run_on_main_thread(move || show_panel(&h));
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

fn poll(app: AppHandle, mut eng: Arc<Engine>) {
    let mut prev: Option<logic::Snapshot> = None;
    let mut failures = 0u32;
    let mut last_restart: Option<std::time::Instant> = None;
    loop {
        match eng.summary().ok().as_ref().and_then(logic::parse_summary) {
            Some(snap) => {
                failures = 0;
                let title = logic::tray_title(&snap);
                set_tray(&app, &title, &format!("OrcaRouter Lite · {title} today"));
                for alert in logic::alerts(prev.as_ref(), &snap) {
                    let _ = app.notification().builder().title(alert.title()).body(alert.body()).show();
                }
                weekly_digest(&app, &snap);
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
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| show_panel(app)))
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_positioner::init())
        .manage(AppState::default())
        .invoke_handler(tauri::generate_handler![
            open_dashboard,
            open_setup,
            close_setup,
            finish_setup,
            open_external,
            quit_app,
            resize_panel
        ])
        .setup(|app| {
            // A menu-bar app: no Dock icon on macOS.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            let open = MenuItem::with_id(app, "open", "Show spend", true, None::<&str>)?;
            let dash = MenuItem::with_id(app, "dashboard", "Open dashboard", true, None::<&str>)?;
            let setup = MenuItem::with_id(app, "setup", "Setup…", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit OrcaRouter Lite", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &dash, &setup, &sep, &quit])?;

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
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            start_engine(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
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
