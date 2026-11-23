//! Starts (or finds) the local Lite engine and reads the app key it writes.
//!
//! The installer bundles the engine as a sidecar named `orca-engine` next to
//! this binary. In development, when no sidecar is bundled, `orca` from PATH
//! is used instead.

use std::fs::OpenOptions;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

pub const DEFAULT_PORT: u16 = 8765;

pub fn orca_home() -> PathBuf {
    if let Ok(h) = std::env::var("ORCA_HOME") {
        if !h.is_empty() {
            return PathBuf::from(h);
        }
    }
    dirs::home_dir().unwrap_or_else(|| PathBuf::from(".")).join(".orcarouter-lite")
}

pub fn port() -> u16 {
    std::env::var("ORCA_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(DEFAULT_PORT)
}

pub fn base_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

fn healthy(port: u16) -> bool {
    ureq::get(&format!("{}/health", base_url(port)))
        .timeout(Duration::from_millis(800))
        .call()
        .is_ok()
}

fn engine_command() -> Command {
    let sidecar = std::env::current_exe().ok().and_then(|exe| {
        let name = if cfg!(windows) { "orca-engine.exe" } else { "orca-engine" };
        let p = exe.parent()?.join(name);
        p.exists().then_some(p)
    });
    match sidecar {
        Some(p) => Command::new(p),
        None => Command::new("orca"),
    }
}

pub struct Engine {
    pub port: u16,
    pub base_url: String,
    pub key: String,
    pub home: PathBuf,
    child: std::sync::Mutex<Option<Child>>,
}

impl Engine {
    /// Reuse an engine already listening on the port (e.g. `orca up` in a
    /// terminal); otherwise start one and wait for it to answer.
    pub fn start() -> Result<Engine, String> {
        let port = port();
        let home = orca_home();
        std::fs::create_dir_all(&home).map_err(|e| format!("Can't create {}: {e}", home.display()))?;

        let mut child = None;
        if !healthy(port) {
            let log = OpenOptions::new()
                .create(true)
                .append(true)
                .open(home.join("engine.log"))
                .map_err(|e| e.to_string())?;
            let err = log.try_clone().map_err(|e| e.to_string())?;
            let spawned = engine_command()
                .args(["up", "--port", &port.to_string()])
                .env("ORCA_HOME", &home)
                .stdin(Stdio::null())
                .stdout(Stdio::from(log))
                .stderr(Stdio::from(err))
                .spawn()
                .map_err(|e| format!("Couldn't start the Orca engine: {e}"))?;
            child = Some(spawned);
            let deadline = Instant::now() + Duration::from_secs(90);
            while !healthy(port) {
                if Instant::now() > deadline {
                    return Err(format!(
                        "The Orca engine didn't start within 90 seconds. See {}",
                        home.join("engine.log").display()
                    ));
                }
                std::thread::sleep(Duration::from_millis(250));
            }
        }

        // The engine writes its app key during startup; give it a moment.
        let key_path = home.join("app.key");
        let deadline = Instant::now() + Duration::from_secs(15);
        let key = loop {
            if let Ok(k) = std::fs::read_to_string(&key_path) {
                let k = k.trim().to_string();
                if !k.is_empty() {
                    break k;
                }
            }
            if Instant::now() > deadline {
                return Err(format!("The engine is running but {} is missing.", key_path.display()));
            }
            std::thread::sleep(Duration::from_millis(200));
        };

        Ok(Engine { port, base_url: base_url(port), key, home, child: std::sync::Mutex::new(child) })
    }

    pub fn summary(&self) -> Option<serde_json::Value> {
        let offset = crate::tz_offset_minutes();
        ureq::get(&format!("{}/v1/app/summary?tz_offset_minutes={offset}", self.base_url))
            .set("Authorization", &format!("Bearer {}", self.key))
            .timeout(Duration::from_secs(5))
            .call()
            .ok()?
            .into_json()
            .ok()
    }

    pub fn stop(&self) {
        if let Some(mut child) = self.child.lock().ok().and_then(|mut c| c.take()) {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}
