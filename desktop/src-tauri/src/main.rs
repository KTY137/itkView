// itkFlow desktop shell.
//
// The shell owns no UI of its own beyond a splash screen. It starts the
// packaged backend (a PyInstaller sidecar), waits until that backend actually
// answers HTTP, and then points the window at it. Backend and frontend are
// served from the same localhost origin, so the web app's session cookies and
// CSRF tokens work exactly as they do in a browser — the shell deliberately
// exposes no Tauri IPC to the page.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, RunEvent, Url};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

const HOST: &str = "127.0.0.1";
/// A cold first start unpacks the bundle and creates the database; generous.
const STARTUP_TIMEOUT: Duration = Duration::from_secs(120);
const POLL_INTERVAL: Duration = Duration::from_millis(250);
const IO_TIMEOUT: Duration = Duration::from_millis(750);

// Raw string: the path is full of backslashes and every one of them is data.
const LOG_HINT: &str = concat!(
    "If this keeps happening, the server log has the reason: ",
    r"%LOCALAPPDATA%\itkflow\logs\server.log"
);

/// Holds the sidecar so the app can stop it again on exit.
#[derive(Default)]
struct ServerHandle(Mutex<Option<CommandChild>>);

/// Ask the OS for a free port, then release it for the sidecar to claim.
///
/// The gap between releasing and claiming is a race in theory. It is not worth
/// a lock: the sidecar exits with a distinct status when the bind fails, which
/// surfaces as a normal startup failure rather than a silent hang.
fn pick_free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind((HOST, 0))?;
    listener.local_addr().map(|address| address.port())
}

/// True once the backend answers `GET /health` with 200.
///
/// Checking the TCP connection alone would be wrong: the sidecar binds its
/// socket before the FastAPI app is built, so a connect succeeds seconds
/// before the app can serve anything.
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

    // One read is enough: the status line arrives in the first segment.
    let mut buffer = [0u8; 256];
    let Ok(read) = stream.read(&mut buffer) else {
        return false;
    };
    String::from_utf8_lossy(&buffer[..read]).starts_with("HTTP/1.1 200")
}

fn show_failure(app: &AppHandle, message: &str) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    // Serialise rather than hand-escape: a Windows path is full of backslashes
    // and one missed escape turns the error screen into a blank page.
    let (Ok(message), Ok(hint)) = (
        serde_json::to_string(message),
        serde_json::to_string(LOG_HINT),
    ) else {
        return;
    };
    let _ = window.eval(&format!(
        "window.itkflowFailed && window.itkflowFailed({message}, {hint})"
    ));
}

/// Poll until the backend is live, then hand the window over to it.
fn open_when_ready(app: AppHandle, port: u16) {
    let deadline = Instant::now() + STARTUP_TIMEOUT;
    while Instant::now() < deadline {
        if health_ok(port) {
            let Some(window) = app.get_webview_window("main") else {
                return;
            };
            match format!("http://{HOST}:{port}/").parse::<Url>() {
                Ok(url) => {
                    if let Err(error) = window.navigate(url) {
                        show_failure(&app, &format!("Could not open itkFlow: {error}"));
                    }
                }
                Err(error) => show_failure(&app, &format!("Invalid server address: {error}")),
            }
            return;
        }
        thread::sleep(POLL_INTERVAL);
    }
    show_failure(&app, "The itkFlow server did not start in time.");
}

fn stop_server(app: &AppHandle) {
    let state = app.state::<ServerHandle>();
    let child = state.0.lock().ok().and_then(|mut guard| guard.take());
    if let Some(child) = child {
        // Without this the backend keeps running headless after the window is
        // gone, holding the database and the port.
        let _ = child.kill();
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(ServerHandle::default())
        .setup(|app| {
            let port = pick_free_port()?;
            let (mut events, child) = app
                .shell()
                .sidecar("itkflow-server")?
                .args(["--host", HOST, "--port", &port.to_string()])
                .spawn()?;

            if let Ok(mut guard) = app.state::<ServerHandle>().0.lock() {
                *guard = Some(child);
            }

            // Drain the event channel; a dropped receiver would make the
            // plugin's reader thread discard output we may want later.
            thread::spawn(move || while events.blocking_recv().is_some() {});

            let handle = app.handle().clone();
            thread::spawn(move || open_when_ready(handle, port));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to start the itkFlow desktop shell");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit) {
            stop_server(handle);
        }
    });
}
