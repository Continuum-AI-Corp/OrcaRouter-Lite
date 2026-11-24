//! "Install command-line tool…": put the bundled engine, which is also the
//! `orca` CLI, on the PATH. Which place to use is decided by
//! `logic::cli_plan`; this file only looks at the disk and carries it out.
//!
//! - macOS: a link at /usr/local/bin/orca (the standard password prompt when
//!   that folder isn't writable), or ~/.local/bin/orca if that's declined.
//! - Linux: a link at ~/.local/bin/orca.
//! - Windows: ~/.orcarouter-lite/bin/orca.cmd, a one-line shim that runs the
//!   engine, and that folder on the user's PATH (HKCU\Environment). The
//!   uninstaller removes both (windows/hooks.nsh).

use std::path::Path;

use crate::logic::{self, CliEnv, CliPlan, CliStep, Existing, Os};

fn os() -> Os {
    if cfg!(target_os = "macos") {
        Os::Mac
    } else if cfg!(windows) {
        Os::Windows
    } else {
        Os::Linux
    }
}

fn existing(path: &Path, engine: &str) -> Existing {
    let present = std::fs::symlink_metadata(path).is_ok();
    let target = std::fs::read_link(path).ok().map(|t| t.to_string_lossy().into_owned());
    logic::classify_existing(present, target.as_deref(), engine)
}

fn dir_writable(dir: &Path) -> bool {
    let probe = dir.join(format!(".orca-write-test-{}", std::process::id()));
    match std::fs::File::create(&probe) {
        Ok(_) => {
            let _ = std::fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

pub fn env() -> CliEnv {
    let engine = crate::engine::sidecar().map(|p| p.to_string_lossy().into_owned());
    let home = dirs::home_dir().map(|h| h.to_string_lossy().into_owned()).unwrap_or_default();
    let e = engine.clone().unwrap_or_default();
    let user = Path::new(&home).join(".local").join("bin").join("orca");
    let system = Path::new(logic::SYSTEM_CLI);
    CliEnv {
        os: os(),
        engine,
        path_var: std::env::var("PATH").unwrap_or_default(),
        appimage: std::env::var_os("APPIMAGE").is_some(),
        system: if cfg!(target_os = "macos") { existing(system, &e) } else { Existing::Missing },
        system_dir_writable: cfg!(target_os = "macos") && dir_writable(Path::new("/usr/local/bin")),
        user: existing(&user, &e),
        home,
    }
}

#[cfg(unix)]
fn link(engine: &str, link: &str) -> Result<(), String> {
    let path = Path::new(link);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("Couldn't create {}: {e}", dir.display()))?;
    }
    // Only a missing path or a link to an engine gets this far (cli_plan).
    if std::fs::symlink_metadata(path).is_ok() {
        std::fs::remove_file(path).map_err(|e| format!("Couldn't replace {link}: {e}"))?;
    }
    std::os::unix::fs::symlink(engine, path).map_err(|e| format!("Couldn't create {link}: {e}"))
}

#[cfg(not(unix))]
fn link(_engine: &str, _link: &str) -> Result<(), String> {
    Err("Links are for macOS and Linux.".into())
}

fn admin_link(engine: &str, link: &str) -> Result<(), String> {
    let out = std::process::Command::new("/usr/bin/osascript")
        .arg("-e")
        .arg(logic::admin_link_script(engine, link))
        .output()
        .map_err(|e| format!("Couldn't ask for your password: {e}"))?;
    if out.status.success() {
        Ok(())
    } else {
        Err("The password prompt was cancelled.".into())
    }
}

#[cfg(windows)]
fn add_to_user_path(dir: &str) -> Result<(), String> {
    use windows_registry::{Type, CURRENT_USER};
    let key = CURRENT_USER
        .create("Environment")
        .map_err(|e| format!("Couldn't open your environment settings: {e}"))?;
    // Keep the value's type: REG_EXPAND_SZ entries like %USERPROFILE%\bin
    // must stay unexpanded.
    let (current, kind) = match key.get_value("Path") {
        Ok(v) => {
            let kind = v.ty();
            // A PATH that isn't text is left alone rather than overwritten.
            let text = String::try_from(v).map_err(|_| "Your PATH setting couldn't be read, so it wasn't changed.".to_string())?;
            (text, kind)
        }
        Err(_) => (String::new(), Type::ExpandString),
    };
    if let Some(updated) = logic::path_with_entry(&current, dir) {
        let result = if kind == Type::String {
            key.set_string("Path", &updated)
        } else {
            key.set_expand_string("Path", &updated)
        };
        result.map_err(|e| format!("Couldn't update your PATH: {e}"))?;
        broadcast_environment_change();
    }
    Ok(())
}

/// Tell Explorer (and so every terminal opened from now on) that the user's
/// environment changed.
#[cfg(windows)]
fn broadcast_environment_change() {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        SendMessageTimeoutW, HWND_BROADCAST, SMTO_ABORTIFHUNG, WM_SETTINGCHANGE,
    };
    let name: Vec<u16> = "Environment".encode_utf16().chain(std::iter::once(0)).collect();
    unsafe {
        SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            name.as_ptr() as isize,
            SMTO_ABORTIFHUNG,
            5000,
            std::ptr::null_mut(),
        );
    }
}

#[cfg(not(windows))]
fn add_to_user_path(_dir: &str) -> Result<(), String> {
    Err("The PATH entry is for Windows.".into())
}

fn shim(dir: &str, body: &str) -> Result<String, String> {
    std::fs::create_dir_all(dir).map_err(|e| format!("Couldn't create {dir}: {e}"))?;
    let path = Path::new(dir).join("orca.cmd");
    std::fs::write(&path, body).map_err(|e| format!("Couldn't write {}: {e}", path.display()))?;
    add_to_user_path(dir)?;
    Ok(path.to_string_lossy().into_owned())
}

/// Install the command and say what happened: (title, body) for the notification.
pub fn install() -> (String, String) {
    let env = env();
    let failed = |why: String| ("Couldn't install the command-line tool".to_string(), why);
    let engine = env.engine.clone().unwrap_or_default();
    match logic::cli_plan(&env) {
        CliPlan::Refuse(why) => failed(why),
        CliPlan::Already { at } => logic::cli_installed(&env, &at),
        CliPlan::Try(steps) => {
            let mut last_error = String::from("Nothing to install.");
            for step in steps {
                let result = match &step {
                    CliStep::Link { link: at, admin: false } => link(&engine, at).map(|_| at.clone()),
                    CliStep::Link { link: at, admin: true } => admin_link(&engine, at).map(|_| at.clone()),
                    CliStep::WindowsShim { dir, shim: body } => shim(dir, body),
                };
                match result {
                    Ok(at) => return logic::cli_installed(&env, &at),
                    Err(e) => last_error = e,
                }
            }
            failed(last_error)
        }
    }
}
