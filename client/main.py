"""
AFV Tracker - Client Entry Point
Starts the local AFV Tracker server on launch and shuts it down on exit.
"""

import os
import sys
import socket
import logging
import subprocess
from typing import Optional

from PyQt6.QtWidgets import QApplication

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger(__name__)


# ── Server lifecycle ────────────────────────────────────────────────────────────

def _port_in_use(port: int) -> bool:
    """Return True if something is already listening on localhost:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _server_dir() -> str:
    """Absolute path to the server package, works from source or frozen exe."""
    if getattr(sys, "frozen", False):
        # PyInstaller: server/ folder is placed next to the exe
        return os.path.join(os.path.dirname(sys.executable), "server")
    # Running from source: client/ and server/ are siblings
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server")
    )


SERVER_PORT = 8765   # must match launcher.py SERVER_PORT


def _start_server() -> Optional[subprocess.Popen]:
    """
    Spawn the FastAPI/uvicorn server as a hidden subprocess.
    Returns the Popen handle, or None if the port is already occupied.
    """
    if _port_in_use(SERVER_PORT):
        log.info("Port %d already in use — skipping server start.", SERVER_PORT)
        return None

    sdir = _server_dir()
    cmd  = [sys.executable, "-m", "uvicorn", "main:app",
            "--host", "127.0.0.1", "--port", str(SERVER_PORT)]

    kwargs: dict = dict(
        cwd    = sdir,
        stdout = subprocess.DEVNULL,
        stderr = subprocess.DEVNULL,
    )
    if sys.platform == "win32":
        # Don't pop a console window behind the GUI
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(cmd, **kwargs)
    log.info("Server started (PID %d) from %s", proc.pid, sdir)
    return proc


def _stop_server(proc: Optional[subprocess.Popen]) -> None:
    """Gracefully terminate the server subprocess."""
    if proc is None or proc.poll() is not None:
        return   # wasn't started by us, or already dead
    log.info("Stopping server (PID %d)…", proc.pid)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.info("Server stopped.")


# ── Windows startup registry ────────────────────────────────────────────────────

def _register_windows_startup():
    """Add AFV Tracker to the Windows startup registry (frozen exe only)."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "AFV Tracker", 0, winreg.REG_SZ,
                          f'"{sys.executable}"')
        winreg.CloseKey(key)
        log.info("Registered AFV Tracker in Windows startup.")
    except Exception as exc:
        log.warning("Could not register startup: %s", exc)


# ── Entry point ─────────────────────────────────────────────────────────────────

def main():
    # 1. Start the server before the GUI so it's ready when the window appears
    server_proc = _start_server()

    app = QApplication(sys.argv)
    app.setApplicationName("AFV Tracker")
    app.setOrganizationName("Africana Virtual Airways")

    # Keep the process alive even when the main window is hidden to tray
    app.setQuitOnLastWindowClosed(False)

    # Register in Windows startup so it auto-launches next boot
    _register_windows_startup()

    from gui import MainWindow
    window = MainWindow()

    # Start hidden — the MSFS watcher will show the window when MSFS launches.
    window.show()

    # 2. Run the event loop
    exit_code = app.exec()

    # 3. Kill the server when the app exits
    _stop_server(server_proc)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
