// itkFlow desktop shell.
//
// The shell starts the packaged backend, waits until it answers HTTP, and
// then points the window at it. Backend and frontend share one localhost
// origin; the only native UI is the startup/failure surface.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::env;
use std::ffi::{OsStr, OsString};
use std::fs::{self, OpenOptions};
use std::io::{self, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use chrono::{SecondsFormat, Utc};
use tauri::{AppHandle, Manager, RunEvent, Url};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const HOST: &str = "127.0.0.1";
/// A cold first start unpacks the bundle and creates the database; generous.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(120);
const POLL_INTERVAL: Duration = Duration::from_millis(250);
const IO_TIMEOUT: Duration = Duration::from_millis(750);
const DESKTOP_LOG_MAX_BYTES: u64 = 1024 * 1024;
const DESKTOP_LOG_BACKUPS: usize = 3;

// Raw string: the path is full of backslashes and every one of them is data.
const LOG_HINT: &str = concat!(
    "Close and reopen itkFlow. Your local data is preserved. Logs: ",
    r"%LOCALAPPDATA%\itkflow\logs\server.log and ",
    r"%LOCALAPPDATA%\itkflow\logs\desktop.log"
);

#[derive(Clone)]
struct HostLogger {
    inner: Arc<HostLoggerInner>,
}

struct HostLoggerInner {
    path: Option<PathBuf>,
    write_lock: Mutex<()>,
}

impl HostLogger {
    fn new(data_dir: Option<&Path>) -> Self {
        let path = data_dir.and_then(|directory| {
            let log_dir = directory.join("logs");
            if fs::create_dir_all(&log_dir).is_err() {
                return None;
            }
            let log_file = log_dir.join("desktop.log");
            // Rotation is best effort. A locked backup must not stop the app
            // or discard the only crash trail we still have.
            let _ = rotate_log(
                &log_file,
                DESKTOP_LOG_MAX_BYTES,
                DESKTOP_LOG_BACKUPS,
            );
            Some(log_file)
        });
        Self {
            inner: Arc::new(HostLoggerInner {
                path,
                write_lock: Mutex::new(()),
            }),
        }
    }

    fn event(&self, level: &str, event: &str, fields: &[(&str, String)]) {
        let Ok(_guard) = self.inner.write_lock.lock() else {
            return;
        };
        let Some(path) = self.inner.path.as_ref() else {
            return;
        };
        let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) else {
            return;
        };
        let mut line = format!(
            "{} level={} event={}",
            Utc::now().to_rfc3339_opts(SecondsFormat::Millis, true),
            safe_log_value(level),
            safe_log_value(event),
        );
        for (key, value) in fields {
            line.push(' ');
            line.push_str(&safe_log_value(key));
            line.push('=');
            line.push_str(&safe_log_value(value));
        }
        let _ = writeln!(file, "{line}");
    }
}

fn safe_log_value(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric()
                || matches!(character, '.' | '_' | '-' | ':' | '+')
            {
                character
            } else {
                '_'
            }
        })
        .collect()
}

fn backup_path(log_file: &Path, index: usize) -> PathBuf {
    let mut name = log_file
        .file_name()
        .unwrap_or_else(|| OsStr::new("desktop.log"))
        .to_os_string();
    name.push(format!(".{index}"));
    log_file.with_file_name(name)
}

fn remove_file_if_present(path: &Path) -> io::Result<()> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

fn rotate_log(log_file: &Path, max_bytes: u64, backups: usize) -> io::Result<()> {
    if max_bytes == 0 || backups == 0 {
        return Ok(());
    }
    let metadata = match fs::metadata(log_file) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };
    if metadata.len() < max_bytes {
        return Ok(());
    }

    remove_file_if_present(&backup_path(log_file, backups))?;
    for index in (1..backups).rev() {
        let source = backup_path(log_file, index);
        if !source.exists() {
            continue;
        }
        let target = backup_path(log_file, index + 1);
        remove_file_if_present(&target)?;
        fs::rename(source, target)?;
    }
    let first = backup_path(log_file, 1);
    remove_file_if_present(&first)?;
    fs::rename(log_file, first)
}

fn nonempty_env(name: &str) -> Option<OsString> {
    env::var_os(name).filter(|value| !value.is_empty())
}

/// Resolve exactly the directory used by `backend/app/desktop_server.py`.
///
/// Tauri's `app_log_dir` uses the bundle identifier (`org.itkflow.desktop`)
/// and is therefore intentionally not used: the backend and host logs must be
/// beside the same database and survive an upgrade together.
fn application_data_dir() -> Result<PathBuf, String> {
    if let Some(override_dir) = nonempty_env("ITKFLOW_DATA_DIR") {
        return Ok(PathBuf::from(override_dir));
    }

    #[cfg(target_os = "windows")]
    {
        return nonempty_env("LOCALAPPDATA")
            .or_else(|| nonempty_env("APPDATA"))
            .map(|base| PathBuf::from(base).join("itkflow"))
            .ok_or_else(|| "Windows did not provide LOCALAPPDATA.".to_string());
    }

    #[cfg(target_os = "macos")]
    {
        return nonempty_env("HOME")
            .map(|home| {
                PathBuf::from(home)
                    .join("Library")
                    .join("Application Support")
                    .join("itkflow")
            })
            .ok_or_else(|| "macOS did not provide HOME.".to_string());
    }

    #[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
    {
        if let Some(base) = nonempty_env("XDG_DATA_HOME") {
            return Ok(PathBuf::from(base).join("itkflow"));
        }
        nonempty_env("HOME")
            .map(|home| {
                PathBuf::from(home)
                    .join(".local")
                    .join("share")
                    .join("itkflow")
            })
            .ok_or_else(|| "The operating system did not provide a data directory.".to_string())
    }
}

/// Holds the sidecar and lifecycle flags shared by the poller/event threads.
struct ServerHandle {
    child: Mutex<Option<CommandChild>>,
    intentional_stop: AtomicBool,
    terminated: AtomicBool,
    ready: AtomicBool,
    logger: HostLogger,
}

impl ServerHandle {
    fn new(logger: HostLogger) -> Self {
        Self {
            child: Mutex::new(None),
            intentional_stop: AtomicBool::new(false),
            terminated: AtomicBool::new(false),
            ready: AtomicBool::new(false),
            logger,
        }
    }
}

/// Ask the OS for a free port, then release it for the sidecar to claim.
fn pick_free_port() -> io::Result<u16> {
    let listener = TcpListener::bind((HOST, 0))?;
    listener.local_addr().map(|address| address.port())
}

/// True once the backend answers `GET /health` with 200.
fn health_ok(port: u16) -> bool {
    let Ok(address) = format!("{HOST}:{port}").parse::<SocketAddr>() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, IO_TIMEOUT) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(IO_TIMEOUT));
    let _ = stream.set_write_timeout(Some(IO_TIMEOUT));

    let request =
        format!("GET /health HTTP/1.1\r\nHost: {HOST}:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }

    let mut buffer = [0u8; 256];
    let Ok(read) = stream.read(&mut buffer) else {
        return false;
    };
    String::from_utf8_lossy(&buffer[..read]).starts_with("HTTP/1.1 200")
}

fn failure_script(message: &str, hint: &str) -> Option<String> {
    let message = serde_json::to_string(message).ok()?;
    let hint = serde_json::to_string(hint).ok()?;
    Some(format!(
        r##"(() => {{
          const message = {message};
          const hint = {hint};
          if (typeof window.itkflowFailed === "function") {{
            window.itkflowFailed(message, hint);
            return;
          }}
          const body = document.body;
          if (!body) return;
          Object.assign(body.style, {{
            margin: "0", minHeight: "100vh", display: "grid", placeItems: "center",
            background: "#0b1220", color: "#e2e8f0",
            font: "400 15px/1.6 Segoe UI, system-ui, sans-serif"
          }});
          const panel = document.createElement("main");
          Object.assign(panel.style, {{ width: "min(520px, 90vw)", textAlign: "center" }});
          const title = document.createElement("h1");
          title.textContent = "itkFlow needs attention";
          title.style.fontSize = "26px";
          const status = document.createElement("p");
          status.textContent = message;
          status.style.color = "#fda4af";
          const detail = document.createElement("p");
          detail.textContent = hint;
          detail.style.color = "#94a3b8";
          detail.style.wordBreak = "break-word";
          panel.append(title, status, detail);
          body.replaceChildren(panel);
        }})()"##
    ))
}

fn show_failure(app: &AppHandle, message: &str) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    if let Some(script) = failure_script(message, LOG_HINT) {
        let _ = window.eval(&script);
    }
}

/// Poll until the backend is live, then hand the window over to it.
fn open_when_ready(app: AppHandle, port: u16) {
    let deadline = Instant::now() + STARTUP_TIMEOUT;
    while Instant::now() < deadline {
        if app
            .state::<ServerHandle>()
            .terminated
            .load(Ordering::SeqCst)
        {
            // The event receiver has already logged and rendered the failure.
            return;
        }
        if health_ok(port) {
            let state = app.state::<ServerHandle>();
            state.ready.store(true, Ordering::SeqCst);
            state.logger.event(
                "INFO",
                "backend_ready",
                &[("port", port.to_string())],
            );
            drop(state);

            let Some(window) = app.get_webview_window("main") else {
                return;
            };
            match format!("http://{HOST}:{port}/").parse::<Url>() {
                Ok(url) => {
                    if let Err(error) = window.navigate(url) {
                        app.state::<ServerHandle>().logger.event(
                            "ERROR",
                            "navigation_failed",
                            &[],
                        );
                        show_failure(&app, &format!("Could not open itkFlow: {error}"));
                    }
                }
                Err(error) => {
                    app.state::<ServerHandle>().logger.event(
                        "ERROR",
                        "server_address_invalid",
                        &[],
                    );
                    show_failure(&app, &format!("Invalid server address: {error}"));
                }
            }
            return;
        }
        thread::sleep(POLL_INTERVAL);
    }
    app.state::<ServerHandle>().logger.event(
        "ERROR",
        "backend_start_timeout",
        &[("port", port.to_string())],
    );
    show_failure(&app, "The itkFlow server did not start in time.");
}

fn start_server(app: &AppHandle, data_dir: &Path) -> Result<(), String> {
    let port = pick_free_port().map_err(|_| "Could not reserve a local server port.")?;
    {
        let state = app.state::<ServerHandle>();
        state.intentional_stop.store(false, Ordering::SeqCst);
        state.terminated.store(false, Ordering::SeqCst);
        state.ready.store(false, Ordering::SeqCst);
        state.logger.event(
            "INFO",
            "port_reserved",
            &[("port", port.to_string())],
        );
    }

    let port_arg = port.to_string();
    let (mut events, child) = app
        .shell()
        .sidecar("itkflow-server")
        .map_err(|error| format!("Could not prepare the local server: {error}"))?
        .env("ITKFLOW_DATA_DIR", data_dir.as_os_str())
        .args(["--host", HOST, "--port", &port_arg])
        .spawn()
        .map_err(|error| format!("Could not start the local server: {error}"))?;
    let child_pid = child.pid();
    match app.state::<ServerHandle>().child.lock() {
        Ok(mut guard) => *guard = Some(child),
        Err(_) => {
            let _ = child.kill();
            return Err("Could not retain the local server process.".to_string());
        }
    }
    app.state::<ServerHandle>().logger.event(
        "INFO",
        "sidecar_spawned",
        &[
            ("pid", child_pid.to_string()),
            ("port", port.to_string()),
        ],
    );

    let event_handle = app.clone();
    thread::spawn(move || {
        while let Some(event) = events.blocking_recv() {
            match event {
                CommandEvent::Stdout(_) | CommandEvent::Stderr(_) => {
                    // The packaged Python process owns server.log. Copying raw
                    // output here would duplicate data and widen log exposure.
                }
                CommandEvent::Error(error) => {
                    event_handle.state::<ServerHandle>().logger.event(
                        "ERROR",
                        "sidecar_command_error",
                        &[("message_bytes", error.len().to_string())],
                    );
                }
                CommandEvent::Terminated(payload) => {
                    let unexpected = {
                        let state = event_handle.state::<ServerHandle>();
                        state.terminated.store(true, Ordering::SeqCst);
                        let intentional = state.intentional_stop.load(Ordering::SeqCst);
                        let ready = state.ready.load(Ordering::SeqCst);
                        state.logger.event(
                            if intentional { "INFO" } else { "ERROR" },
                            "sidecar_terminated",
                            &[
                                ("pid", child_pid.to_string()),
                                (
                                    "code",
                                    payload
                                        .code
                                        .map_or_else(|| "none".to_string(), |code| code.to_string()),
                                ),
                                (
                                    "signal",
                                    payload.signal.map_or_else(
                                        || "none".to_string(),
                                        |signal| signal.to_string(),
                                    ),
                                ),
                                ("intentional", intentional.to_string()),
                                ("ready", ready.to_string()),
                            ],
                        );
                        if let Ok(mut guard) = state.child.lock() {
                            guard.take();
                        }
                        !intentional
                    };
                    if unexpected {
                        show_failure(
                            &event_handle,
                            "The local itkFlow server stopped unexpectedly.",
                        );
                    }
                    return;
                }
                _ => {}
            }
        }
        let state = event_handle.state::<ServerHandle>();
        if !state.intentional_stop.load(Ordering::SeqCst)
            && !state.terminated.load(Ordering::SeqCst)
        {
            state
                .logger
                .event("WARN", "sidecar_event_channel_closed", &[]);
        }
    });

    let ready_handle = app.clone();
    thread::spawn(move || open_when_ready(ready_handle, port));
    Ok(())
}

fn stop_server(app: &AppHandle) {
    let state = app.state::<ServerHandle>();
    state.intentional_stop.store(true, Ordering::SeqCst);
    state.logger.event("INFO", "sidecar_stop_requested", &[]);
    let logger = state.logger.clone();
    let child = state.child.lock().ok().and_then(|mut guard| guard.take());
    drop(state);

    if let Some(child) = child {
        let child_pid = child.pid();
        // PyInstaller onefile uses a bootstrap/server process tree. Killing
        // only the bootstrap leaves a headless server holding the DB and port.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            let tree_killed = std::process::Command::new("taskkill")
                .args(["/PID", &child_pid.to_string(), "/T", "/F"])
                .creation_flags(CREATE_NO_WINDOW)
                .status()
                .map(|status| status.success())
                .unwrap_or(false);
            if tree_killed {
                logger.event(
                    "INFO",
                    "sidecar_stop_signal",
                    &[
                        ("pid", child_pid.to_string()),
                        ("method", "taskkill".to_string()),
                    ],
                );
            } else {
                let fallback_killed = child.kill().is_ok();
                logger.event(
                    if fallback_killed { "WARN" } else { "ERROR" },
                    "sidecar_stop_signal",
                    &[
                        ("pid", child_pid.to_string()),
                        ("method", "child_kill".to_string()),
                        ("success", fallback_killed.to_string()),
                    ],
                );
            }
        }
        #[cfg(not(windows))]
        {
            let killed = child.kill().is_ok();
            logger.event(
                if killed { "INFO" } else { "ERROR" },
                "sidecar_stop_signal",
                &[
                    ("pid", child_pid.to_string()),
                    ("method", "child_kill".to_string()),
                    ("success", killed.to_string()),
                ],
            );
        }
    }
}

fn main() {
    let data_dir = application_data_dir();
    let logger = HostLogger::new(data_dir.as_deref().ok());
    logger.event(
        "INFO",
        "desktop_shell_started",
        &[
            ("pid", std::process::id().to_string()),
            ("version", env!("CARGO_PKG_VERSION").to_string()),
        ],
    );

    let panic_logger = logger.clone();
    std::panic::set_hook(Box::new(move |panic_info| {
        let line = panic_info
            .location()
            .map_or_else(|| "none".to_string(), |location| location.line().to_string());
        panic_logger.event("ERROR", "desktop_shell_panic", &[("line", line)]);
    }));

    let setup_data_dir = data_dir.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(ServerHandle::new(logger.clone()))
        .setup(move |app| {
            let handle = app.handle().clone();
            match setup_data_dir.as_ref() {
                Ok(directory) => {
                    if let Err(error) = start_server(&handle, directory) {
                        handle.state::<ServerHandle>().logger.event(
                            "ERROR",
                            "sidecar_start_failed",
                            &[],
                        );
                        show_failure(&handle, &error);
                    }
                }
                Err(error) => {
                    handle.state::<ServerHandle>().logger.event(
                        "ERROR",
                        "application_data_dir_unavailable",
                        &[],
                    );
                    show_failure(&handle, error);
                }
            }
            // Keep the splash alive on setup failure so the explanation stays
            // visible instead of a windowed process disappearing silently.
            Ok(())
        })
        .build(tauri::generate_context!());

    let app = match app {
        Ok(app) => app,
        Err(_) => {
            logger.event("ERROR", "desktop_shell_build_failed", &[]);
            return;
        }
    };

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit) {
            stop_server(handle);
            handle
                .state::<ServerHandle>()
                .logger
                .event("INFO", "desktop_shell_exited", &[]);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_dir(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock")
            .as_nanos();
        let directory = env::temp_dir().join(format!(
            "itkflow-desktop-{name}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&directory).expect("create isolated test directory");
        directory
    }

    fn remove_test_files(directory: &Path, names: &[&str]) {
        for name in names {
            remove_file_if_present(&directory.join(name)).expect("remove test file");
        }
        fs::remove_dir(directory).expect("remove isolated test directory");
    }

    #[test]
    fn full_log_rotates_in_backup_order() {
        let directory = test_dir("rotation");
        let log_file = directory.join("desktop.log");
        fs::write(&log_file, b"current").expect("write current log");
        fs::write(backup_path(&log_file, 1), b"previous").expect("write first backup");
        fs::write(backup_path(&log_file, 2), b"older").expect("write second backup");

        rotate_log(&log_file, 1, 3).expect("rotate log");

        assert!(!log_file.exists());
        assert_eq!(fs::read(backup_path(&log_file, 1)).unwrap(), b"current");
        assert_eq!(fs::read(backup_path(&log_file, 2)).unwrap(), b"previous");
        assert_eq!(fs::read(backup_path(&log_file, 3)).unwrap(), b"older");
        remove_test_files(
            &directory,
            &["desktop.log.1", "desktop.log.2", "desktop.log.3"],
        );
    }

    #[test]
    fn small_log_is_left_in_place() {
        let directory = test_dir("small-log");
        let log_file = directory.join("desktop.log");
        fs::write(&log_file, b"current").expect("write current log");

        rotate_log(&log_file, 100, 3).expect("inspect log");

        assert_eq!(fs::read(&log_file).unwrap(), b"current");
        assert!(!backup_path(&log_file, 1).exists());
        remove_test_files(&directory, &["desktop.log"]);
    }

    #[test]
    fn failure_script_has_a_post_navigation_fallback() {
        let script = failure_script("Stopped 'safely'", LOG_HINT).expect("serialize script");

        assert!(script.contains("typeof window.itkflowFailed"));
        assert!(script.contains("body.replaceChildren(panel)"));
        assert!(script.contains("Stopped 'safely'"));
        assert!(script.contains("desktop.log"));
    }
}
