fn main() {
    // Declaring the app's commands makes Tauri check every call against a
    // capability. The panel and setup pages are served by the local engine
    // (a "remote" origin to Tauri), so lib.rs grants these commands to
    // exactly http://127.0.0.1:<port> at runtime and to nothing else.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "open_dashboard",
            "open_setup",
            "close_setup",
            "finish_setup",
            "open_external",
            "apply_start_at_login",
            "quit_app",
            "resize_panel",
            "can_install_updates",
            "install_update",
            "clipboard_orca_key",
            "clear_clipboard",
            "copy_png",
            "take_pending_link",
        ]),
    ))
    .expect("failed to run tauri-build");
}
