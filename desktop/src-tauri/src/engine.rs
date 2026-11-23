//! Starts (or finds) the local Lite engine and talks to it.
//!
//! The installer bundles the engine as a sidecar named `orca-engine` next to
//! this binary. In development, when no sidecar is bundled, `orca` from PATH
//! is used instead.
//!
//! Lifetime: the engine is started with `--exit-with-stdin` and a pipe on its
//! stdin that this process never writes to. When the app exits for any reason
//! (quit, crash, force-quit) the OS closes the pipe and the engine stops, so
//! it can't linger on the port and be reused after an update.
//!
//! Trust: before the app sends the engine its key, the engine must answer a
//! random challenge with an HMAC keyed by the per-launch secret `orca up`
//! wrote to engine.json (0600). Another program on the port can't.

use std::fs::OpenOptions;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub const DEFAULT_PORT: u16 = 8765;
const START_TIMEOUT: Duration = Duration::from_secs(120);

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
    #[allow(unused_mut)]
    let mut cmd = match sidecar {
        Some(p) => Command::new(p),
        None => Command::new("orca"),
    };
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

fn random_hex(bytes: usize) -> String {
    // Unpredictable enough for a challenge: hash the time, pid and an address.
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(format!("{:?}{}{:p}", Instant::now(), std::process::id(), &bytes).as_bytes());
    h.update(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
            .to_le_bytes(),
    );
    hex::encode(h.finalize())[..bytes * 2].to_string()
}

/// Ask whoever owns the port to prove it holds engine.json's secret.
pub fn verify_engine(home: &std::path::Path, port: u16) -> Result<(), String> {
    let info: serde_json::Value = std::fs::read_to_string(home.join("engine.json"))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .ok_or_else(|| format!("{} is missing; the engine on port {port} wasn't started by Orca.", home.join("engine.json").display()))?;
    let secret = info.get("secret").and_then(|s| s.as_str()).unwrap_or_default();
    let challenge = random_hex(16);
    let proof = ureq::get(&format!("{}/health/identity", base_url(port)))
        .query("challenge", &challenge)
        .timeout(Duration::from_secs(3))
        .call()
        .ok()
        .and_then(|r| r.into_json::<serde_json::Value>().ok())
        .and_then(|v| v.get("proof").and_then(|p| p.as_str()).map(str::to_string))
        .unwrap_or_default();
    if crate::logic::verify_proof(secret, &challenge, &proof) {
        Ok(())
    } else {
        Err(format!(
            "Another program is using port {port}, so Orca didn't start its engine there. \
             Quit that program, or set ORCA_PORT to a free port, and reopen Orca."
        ))
    }
}

pub struct Engine {
    pub port: u16,
    pub base_url: String,
    pub home: PathBuf,
    key: Mutex<String>,
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

impl Engine {
    /// Reuse an engine already listening on the port (e.g. `orca up` in a
    /// terminal) if it proves it is ours; otherwise start one.
    pub fn start() -> Result<Engine, String> {
        let port = port();
        let home = orca_home();
        std::fs::create_dir_all(&home).map_err(|e| format!("Can't create {}: {e}", home.display()))?;

        let mut child = None;
        let mut stdin = None;
        if healthy(port) {
            verify_engine(&home, port)?;
        } else {
            let log = OpenOptions::new()
                .create(true)
                .append(true)
                .open(home.join("engine.log"))
                .map_err(|e| e.to_string())?;
            let err = log.try_clone().map_err(|e| e.to_string())?;
            let log_path = home.join("engine.log");
            let log_start = std::fs::metadata(&log_path).map(|m| m.len()).unwrap_or(0);
            let mut spawned = engine_command()
                .args(["up", "--port", &port.to_string(), "--exit-with-stdin"])
                .env("ORCA_HOME", &home)
                .stdin(Stdio::piped())
                .stdout(Stdio::from(log))
                .stderr(Stdio::from(err))
                .spawn()
                .map_err(|e| format!("Couldn't start the Orca engine: {e}"))?;
            stdin = spawned.stdin.take();
            let deadline = Instant::now() + START_TIMEOUT;
            loop {
                if healthy(port) {
                    break;
                }
                if let Ok(Some(_status)) = spawned.try_wait() {
                    // The engine explains itself on its last line (a locked
                    // keychain, a port in use); show that, not just the log path.
                    let written = std::fs::read(&log_path).unwrap_or_default();
                    let start = (log_start as usize).min(written.len());
                    let new_output = String::from_utf8_lossy(&written[start..]);
                    return Err(crate::logic::startup_failure(&new_output, &log_path.display().to_string()));
                }
                if Instant::now() > deadline {
                    let _ = spawned.kill();
                    let _ = spawned.wait();
                    return Err(format!(
                        "The Orca engine didn't start within {} seconds. See {}",
                        START_TIMEOUT.as_secs(),
                        home.join("engine.log").display()
                    ));
                }
                std::thread::sleep(Duration::from_millis(250));
            }
            verify_engine(&home, port)?;
            child = Some(spawned);
        }

        let key = Self::read_key(&home)?;
        Ok(Engine {
            port,
            base_url: base_url(port),
            home,
            key: Mutex::new(key),
            child: Mutex::new(child),
            stdin: Mutex::new(stdin),
        })
    }

    fn read_key(home: &std::path::Path) -> Result<String, String> {
        // The engine writes its app key during startup; give it a moment.
        let key_path = home.join("app.key");
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            if let Ok(k) = std::fs::read_to_string(&key_path) {
                let k = k.trim().to_string();
                if !k.is_empty() {
                    return Ok(k);
                }
            }
            if Instant::now() > deadline {
                return Err(format!("The engine is running but {} is missing.", key_path.display()));
            }
            std::thread::sleep(Duration::from_millis(200));
        }
    }

    pub fn key(&self) -> String {
        self.key.lock().map(|k| k.clone()).unwrap_or_default()
    }

    /// Did an engine we started exit on its own?
    pub fn exited(&self) -> bool {
        match self.child.lock() {
            Ok(mut c) => match c.as_mut() {
                Some(child) => matches!(child.try_wait(), Ok(Some(_))),
                None => !healthy(self.port),
            },
            Err(_) => false,
        }
    }

    pub fn summary(&self) -> Result<serde_json::Value, u16> {
        let offset = crate::tz_offset_minutes();
        let call = |key: &str| {
            ureq::get(&format!("{}/v1/app/summary?tz_offset_minutes={offset}", self.base_url))
                .set("Authorization", &format!("Bearer {key}"))
                .timeout(Duration::from_secs(5))
                .call()
        };
        match call(&self.key()) {
            Ok(r) => r.into_json().map_err(|_| 0),
            Err(ureq::Error::Status(401, _)) | Err(ureq::Error::Status(403, _)) => {
                // app.key may have been re-minted; pick up the new one.
                let fresh = Self::read_key(&self.home).map_err(|_| 401u16)?;
                if let Ok(mut k) = self.key.lock() {
                    *k = fresh.clone();
                }
                call(&fresh).map_err(|_| 401u16)?.into_json().map_err(|_| 0)
            }
            Err(ureq::Error::Status(code, _)) => Err(code),
            Err(_) => Err(0),
        }
    }

    /// Close the engine's stdin (it exits on EOF), then make sure it's gone.
    pub fn stop(&self) {
        if let Ok(mut s) = self.stdin.lock() {
            s.take();
        }
        if let Some(mut child) = self.child.lock().ok().and_then(|mut c| c.take()) {
            let deadline = Instant::now() + Duration::from_secs(5);
            while Instant::now() < deadline {
                if let Ok(Some(_)) = child.try_wait() {
                    return;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}
