"""
AFV Tracker - Compiled Entry Point
Unified launcher that combines the system tray watcher and the main tracker window.

Single exe behaviour:
  - Starts as a system tray icon
  - Watches for MSFS 2020 / 2024 every 5 seconds
  - Auto-opens the tracker window when MSFS is detected
  - Closing the tracker window hides it back to tray (doesn't exit)
  - Right-click tray for options

Run directly for development:  python launcher.py
Compiled exe entry point:      pyinstaller --name "AFV Tracker" launcher.py
"""

import sys
import os
import socket
import subprocess
import threading
import time
import winreg
import logging
from pathlib import Path

# ── Ensure client/ is on the path when running compiled ──────────────────────
_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import psutil

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PyQt6.QtCore    import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtGui     import QIcon, QPixmap, QPainter, QColor, QBrush, QRadialGradient

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-8s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MSFS_EXE        = "FlightSimulator.exe"
POLL_MS         = 5_000          # check every 5 seconds
STARTUP_KEY     = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME    = "AFVTrackerLauncher"
PYTHON_EXE      = sys.executable
LAUNCHER_PATH   = Path(__file__).resolve()


# ── Embedded server (uvicorn in a daemon thread) ──────────────────────────────

def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _server_dir() -> Path:
    """
    Locate the server/ package.
    - Frozen one-file exe: PyInstaller extracts datas to sys._MEIPASS
    - Running from source: server/ is a sibling of client/
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "server"
    return (_HERE / ".." / "server").resolve()


# ── Server mode (frozen exe only) ────────────────────────────────────────────

def _load_dotenv(sdir: Path) -> None:
    """
    Load environment variables from server/.env before any server imports.
    Parses the file manually — no python-dotenv dependency needed.
    """
    env_file = sdir / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def run_server_mode():
    """
    Called when the exe is launched with --server-mode.
    Runs uvicorn synchronously — this is the entire process in server mode.
    """
    sdir = _server_dir()
    sdir_str = str(sdir)
    if sdir_str not in sys.path:
        sys.path.insert(0, sdir_str)

    # Must happen BEFORE importing database.py (it reads DATABASE_URL at import time)
    _load_dotenv(sdir)

    import uvicorn
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "afv_server_main", sdir / "main.py"
    )
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)

    uvicorn.run(server_module.app, host="127.0.0.1", port=8000, log_level="warning")


# ── Server lifecycle (GUI mode) ───────────────────────────────────────────────

def start_server() -> "subprocess.Popen | None":
    """
    Spawn the server as a subprocess so it is completely isolated from the GUI.

    Frozen exe  → spawns itself with --server-mode (exe is both client & server)
    From source → spawns uvicorn directly against the server/ directory
    """
    if _port_in_use(8000):
        log.info("Port 8000 already in use — skipping server start.")
        return None

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--server-mode"]
    else:
        sdir = str(_server_dir())
        cmd = [sys.executable, "-m", "uvicorn", "main:app",
               "--host", "127.0.0.1", "--port", "8000"]

    kwargs: dict = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if getattr(sys, "frozen", False):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["cwd"] = str(_server_dir())

    try:
        # Write server output to a log file so errors are visible
        log_path = Path.home() / "afv_server.log"
        log_file = open(log_path, "w")
        kwargs["stdout"] = log_file
        kwargs["stderr"] = log_file
        proc = subprocess.Popen(cmd, **kwargs)
        log.info("Server subprocess started (PID %d). Log: %s", proc.pid, log_path)
        return proc
    except Exception as exc:
        log.error("Could not start server: %s", exc)
        return None


def stop_server(proc) -> None:
    """Terminate the server subprocess."""
    if proc is None:
        return
    try:
        if proc.poll() is None:   # still running
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.info("Server stopped.")
    except Exception as exc:
        log.warning("Error stopping server: %s", exc)


def stop_server(server) -> None:
    """Signal uvicorn to stop and wait briefly for it to shut down."""
    if server is None:
        return
    try:
        server.should_exit = True
        log.info("Server shutdown requested.")
    except Exception as exc:
        log.warning("Error stopping server: %s", exc)


# ── Icon painter (no image file needed) ──────────────────────────────────────

def _make_pixmap(size: int = 64, active: bool = False) -> QPixmap:
    """Draw the AFV 'A' icon in Qt — red when MSFS detected, grey when idle."""
    pm  = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p   = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    pad = max(2, size // 16)
    color = QColor("#C41E3A") if active else QColor("#505050")
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(pad, pad, size - 2 * pad, size - 2 * pad)

    cx, cy = size // 2, size // 2
    s  = size * 0.28
    lw = max(2, size // 14)

    pen = p.pen()
    pen.setColor(QColor("white"))
    pen.setWidth(lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)

    top_x, top_y = cx,           int(cy - s * 0.85)
    bl_x,  bl_y  = int(cx - s * 0.72), int(cy + s * 0.75)
    br_x,  br_y  = int(cx + s * 0.72), int(cy + s * 0.75)
    ml_x,  ml_y  = int(cx - s * 0.38), int(cy + s * 0.10)
    mr_x,  mr_y  = int(cx + s * 0.38), int(cy + s * 0.10)

    p.drawLine(top_x, top_y, bl_x, bl_y)
    p.drawLine(top_x, top_y, br_x, br_y)
    pen.setWidth(max(1, lw - 1))
    p.setPen(pen)
    p.drawLine(ml_x, ml_y, mr_x, mr_y)

    p.end()
    return pm


def _make_icon(active: bool = False) -> QIcon:
    return QIcon(_make_pixmap(64, active))


# ── Startup registry ──────────────────────────────────────────────────────────

def _startup_cmd() -> str:
    if getattr(sys, "frozen", False):
        # Running as compiled exe
        return f'"{sys.executable}"'
    else:
        return f'"{PYTHON_EXE}" "{LAUNCHER_PATH}"'


def is_in_startup() -> bool:
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY)
        winreg.QueryValueEx(k, STARTUP_NAME)
        winreg.CloseKey(k)
        return True
    except FileNotFoundError:
        return False


def add_to_startup():
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0,
                       winreg.KEY_SET_VALUE)
    winreg.SetValueEx(k, STARTUP_NAME, 0, winreg.REG_SZ, _startup_cmd())
    winreg.CloseKey(k)


def remove_from_startup():
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0,
                           winreg.KEY_SET_VALUE)
        winreg.DeleteValue(k, STARTUP_NAME)
        winreg.CloseKey(k)
    except FileNotFoundError:
        pass


# ── MSFS detection ────────────────────────────────────────────────────────────

def find_msfs() -> tuple[bool, str]:
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            if proc.info["name"] == MSFS_EXE:
                path = (proc.info.get("exe") or "").lower()
                ver  = "MSFS 2024" if "2024" in path else "MSFS 2020"
                return True, ver
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False, ""


# ── Watcher signal bridge ─────────────────────────────────────────────────────

class _Bridge(QObject):
    msfs_started = pyqtSignal(str)   # version string
    msfs_stopped = pyqtSignal()


# ── Main application ──────────────────────────────────────────────────────────

class AFVLauncher:
    def __init__(self, app: QApplication, server=None):
        self.app          = app
        self._server      = server   # uvicorn.Server instance (or None)
        self.main_window  = None
        self.auto_launch  = True
        self._msfs_was_running = False
        self._bridge      = _Bridge()

        # Tray icon
        self.tray = QSystemTrayIcon(_make_icon(active=False), app)
        self.tray.setToolTip("AFV Tracker — Waiting for MSFS…")
        self.tray.activated.connect(self._on_tray_activated)

        self._build_menu()
        self.tray.show()

        # Wire signals (bridge runs on Qt thread)
        self._bridge.msfs_started.connect(self._on_msfs_started)
        self._bridge.msfs_stopped.connect(self._on_msfs_stopped)

        # Poll timer (Qt timer = runs on main thread, safe)
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

        # Run one poll immediately in case MSFS is already open
        QTimer.singleShot(500, self._poll)

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _poll(self):
        running, version = find_msfs()

        if running and not self._msfs_was_running:
            self._msfs_was_running = True
            self._bridge.msfs_started.emit(version)

        elif not running and self._msfs_was_running:
            self._msfs_was_running = False
            self._bridge.msfs_stopped.emit()

    # ------------------------------------------------------------------
    # MSFS events (Qt thread)
    # ------------------------------------------------------------------

    def _on_msfs_started(self, version: str):
        log.info("Detected: %s", version)
        self.tray.setIcon(_make_icon(active=True))
        self.tray.setToolTip(f"AFV Tracker — {version} detected")
        self._build_menu()

        if self.auto_launch:
            self._show_tracker()
            self.tray.showMessage(
                "AFV Tracker",
                f"{version} detected — tracker opened.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def _on_msfs_stopped(self):
        log.info("MSFS closed.")
        self.tray.setIcon(_make_icon(active=False))
        self.tray.setToolTip("AFV Tracker — Waiting for MSFS…")
        self._build_menu()

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def _show_tracker(self):
        if self.main_window is None:
            from gui import MainWindow
            self.main_window = MainWindow()
            # Override close to hide-to-tray instead of quit
            self.main_window.closeEvent = self._on_window_close

        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()
        self._build_menu()

    def _hide_tracker(self):
        if self.main_window and self.main_window.isVisible():
            self.main_window.hide()
        self._build_menu()

    def _on_window_close(self, event):
        """Intercept close → hide to tray instead of quitting."""
        event.ignore()
        self._hide_tracker()
        self.tray.showMessage(
            "AFV Tracker",
            "Still running in the system tray.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.main_window and self.main_window.isVisible():
                self._hide_tracker()
            else:
                self._show_tracker()

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background: #1A1A1A;
                color: #FFFFFF;
                border: 1px solid #2A2A2A;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item { padding: 6px 20px; border-radius: 3px; }
            QMenu::item:selected { background: #C41E3A; }
            QMenu::item:disabled { color: #606060; }
            QMenu::separator { background: #2A2A2A; height: 1px; margin: 4px 8px; }
        """)

        # Status (non-clickable)
        running, ver = find_msfs()
        status = menu.addAction(f"● {ver}" if running else "○ Waiting for MSFS…")
        status.setEnabled(False)

        win_open = self.main_window and self.main_window.isVisible()
        wstatus  = menu.addAction("Tracker: open" if win_open else "Tracker: hidden")
        wstatus.setEnabled(False)

        menu.addSeparator()

        # Show / hide
        show_lbl = "Hide tracker" if win_open else "Open tracker"
        menu.addAction(show_lbl).triggered.connect(
            self._hide_tracker if win_open else self._show_tracker
        )

        # Auto-launch toggle
        al_lbl = f"Auto-launch: {'ON  ✓' if self.auto_launch else 'OFF'}"
        menu.addAction(al_lbl).triggered.connect(self._toggle_auto)

        menu.addSeparator()

        # Startup toggle
        su_lbl = "Remove from startup" if is_in_startup() else "Run at Windows startup"
        menu.addAction(su_lbl).triggered.connect(self._toggle_startup)

        menu.addSeparator()
        menu.addAction("Exit").triggered.connect(self._quit)

        self.tray.setContextMenu(menu)

    def _toggle_auto(self):
        self.auto_launch = not self.auto_launch
        self._build_menu()

    def _toggle_startup(self):
        if is_in_startup():
            remove_from_startup()
        else:
            add_to_startup()
        self._build_menu()

    def _quit(self):
        if self.main_window:
            # Properly stop workers
            try:
                self.main_window._stop_tracking()
                if self.main_window._net_client:
                    self.main_window._net_client.stop()
                    self.main_window._net_client.wait(1000)
            except Exception:
                pass
        self.tray.hide()
        stop_server(self._server)
        self.app.quit()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    # ── Server-mode: frozen exe spawned with --server-mode ────────────────
    if "--server-mode" in sys.argv:
        run_server_mode()
        return   # never reaches Qt

    # Windows: hide the console window when running compiled
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(
            ctypes.windll.kernel32.GetConsoleWindow(), 0
        )

    # Start the server subprocess before building the GUI
    _server = start_server()
    # Give it a moment to bind the port before the client tries to connect
    time.sleep(1.5)

    app = QApplication(sys.argv)
    app.setApplicationName("AFV Tracker")
    app.setOrganizationName("Africana Virtual Airways")
    app.setQuitOnLastWindowClosed(False)   # stay alive in tray

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "AFV Tracker",
                             "System tray is not available on this system.")
        stop_server(_server)
        sys.exit(1)

    launcher = AFVLauncher(app, _server)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
