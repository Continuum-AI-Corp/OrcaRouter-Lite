//! Windows "start at login": always the current user's `Run` key.
//!
//! tauri-plugin-autostart 2.7 drives auto-launch 0.6 in its default Dynamic
//! mode, which writes HKLM (every account on the machine) whenever Orca runs
//! as administrator, pointing at this user's own AppData. Its is_enabled only
//! checks that a value exists, so a value left by an older install, pointing
//! at a deleted exe, was never corrected. And its enable() resets Task
//! Manager's "disabled" flag, overriding the user's choice there; this module
//! never touches that flag.
use crate::logic::{self, LoginItemAction};
use windows_registry::{Key, CURRENT_USER, LOCAL_MACHINE};

const RUN: &str = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run";
// HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND): no such key or value.
const NOT_FOUND: u32 = 0x8007_0002;

fn read(root: &Key, name: &str) -> Result<Option<String>, String> {
    match root.open(RUN).and_then(|key| key.get_string(name)) {
        Ok(value) => Ok(Some(value)),
        Err(e) if e.code().0 as u32 == NOT_FOUND => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

fn remove(root: &Key, name: &str) -> windows_registry::Result<()> {
    match root.options().write().open(RUN).and_then(|key| key.remove_value(name)) {
        Err(e) if e.code().0 as u32 == NOT_FOUND => Ok(()),
        result => result,
    }
}

pub fn sync(app_name: &str, wanted: bool) -> Result<(), String> {
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let desired = logic::login_item_command(&exe.display().to_string());
    match logic::login_item_action(wanted, read(CURRENT_USER, app_name)?.as_deref(), &desired) {
        LoginItemAction::Write => CURRENT_USER
            .create(RUN)
            .and_then(|key| key.set_string(app_name, &desired))
            .map_err(|e| e.to_string())?,
        LoginItemAction::Remove => remove(CURRENT_USER, app_name).map_err(|e| e.to_string())?,
        LoginItemAction::Nothing => {}
    }
    // A machine-wide item from an older Orca run as administrator. Removing it
    // needs admin rights; without them it stays for the uninstaller (or the
    // next elevated run) to clear.
    if let Ok(Some(machine)) = read(LOCAL_MACHINE, app_name) {
        if logic::is_orca_login_command(&machine) {
            if let Err(e) = remove(LOCAL_MACHINE, app_name) {
                eprintln!("orca: start at login: couldn't remove the machine-wide login item ({e})");
            }
        }
    }
    Ok(())
}
