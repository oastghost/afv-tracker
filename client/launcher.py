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
from PyQt6.QtCore    import Qt, QTimer, QObject, pyqtSignal, QSharedMemory
from PyQt6.QtGui     import QIcon, QPixmap, QPainter, QColor, QBrush, QRadialGradient

_LOG_PATH = Path.home() / ".afv_tracker" / "afv_tracker.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def _excepthook(exc_type, exc_value, exc_tb):
    """Log unhandled exceptions to file instead of silently aborting."""
    import traceback
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log.critical("UNHANDLED EXCEPTION:\n%s", msg)


sys.excepthook = _excepthook

# ── Constants ─────────────────────────────────────────────────────────────────

MSFS_EXE        = "FlightSimulator.exe"
POLL_MS         = 5_000          # check every 5 seconds
STARTUP_KEY     = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_NAME    = "AFVTrackerLauncher"
PYTHON_EXE      = sys.executable
LAUNCHER_PATH   = Path(__file__).resolve()
SERVER_PORT     = 8765           # avoid port 8000 which is commonly used by other services


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

    # A windowed (no-console) PyInstaller exe has sys.stdout/stderr = None.
    # uvicorn's default logging config calls sys.stdout.isatty() while building
    # its formatters, which raises AttributeError on None and aborts the server
    # before it can bind. Give it real streams and disable its own dictConfig
    # (log_config=None) so it never touches isatty.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    spec = importlib.util.spec_from_file_location(
        "afv_server_main", sdir / "main.py"
    )
    server_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server_module)

    uvicorn.run(server_module.app, host="127.0.0.1", port=SERVER_PORT,
                log_level="warning", log_config=None)


# ── Server lifecycle (GUI mode) ───────────────────────────────────────────────

def start_server() -> "subprocess.Popen | None":
    """
    Spawn the server as a subprocess so it is completely isolated from the GUI.

    Frozen exe  → spawns itself with --server-mode (exe is both client & server)
    From source → spawns uvicorn directly against the server/ directory
    """
    if _port_in_use(SERVER_PORT):
        log.info("Port %d already in use — skipping server start.", SERVER_PORT)
        return None

    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--server-mode"]
    else:
        sdir = str(_server_dir())
        cmd = [sys.executable, "-m", "uvicorn", "main:app",
               "--host", "127.0.0.1", "--port", str(SERVER_PORT)]

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


def _logo_path() -> Path:
    """Resolve client/assets/icon.png in source or frozen mode."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets" / "icon.png"
    return _HERE / "assets" / "icon.png"


def _make_icon(active: bool = False) -> QIcon:
    """Africana logo tray icon — full colour when MSFS is up, dimmed when idle.
    Falls back to the drawn 'A' mark if the logo asset is missing."""
    logo = _logo_path()
    if logo.exists():
        src = QPixmap(str(logo))
        if not src.isNull():
            if active:
                return QIcon(src)
            # Dim the logo when idle
            dim = QPixmap(src.size())
            dim.fill(Qt.GlobalColor.transparent)
            p = QPainter(dim)
            p.setOpacity(0.45)
            p.drawPixmap(0, 0, src)
            p.end()
            return QIcon(dim)
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
    msfs_started   = pyqtSignal(str)          # version string
    msfs_stopped   = pyqtSignal()
    update_checked = pyqtSignal(object, bool) # (release_info dict or None, manual)


# ── Main application ──────────────────────────────────────────────────────────

class AFVLauncher:
    def __init__(self, app: QApplication, server=None):
        self.app          = app
        self._server      = server   # uvicorn.Server instance (or None)
        self.main_window  = None
        self.auto_launch  = True
        self._msfs_was_running = False
        self._bridge      = _Bridge()
        self._pending_update = None   # release info dict once an update is found

        # Tray icon
        self.tray = QSystemTrayIcon(_make_icon(active=False), app)
        self.tray.setToolTip("AFV Tracker — Waiting for MSFS…")
        self.tray.activated.connect(self._on_tray_activated)

        self._build_menu()
        self.tray.show()

        # Wire signals (bridge runs on Qt thread)
        self._bridge.msfs_started.connect(self._on_msfs_started)
        self._bridge.msfs_stopped.connect(self._on_msfs_stopped)
        self._bridge.update_checked.connect(self._on_update_checked)

        # Poll timer (Qt timer = runs on main thread, safe)
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

        # Open the tracker window right away — the app should be visible
        # as soon as the exe is launched, not sit silently in the tray.
        self._show_tracker()

        # Run one poll immediately in case MSFS is already open
        QTimer.singleShot(500, self._poll)

        # Check for a newer release shortly after startup — quiet unless one is found
        QTimer.singleShot(8_000, self._check_for_updates)

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
    # Update checking
    # ------------------------------------------------------------------

    def _check_for_updates(self, manual: bool = False):
        def _run():
            from updater import check_latest_release
            info = check_latest_release()
            self._bridge.update_checked.emit(info, manual)
        threading.Thread(target=_run, daemon=True).start()

    def _on_update_checked(self, info, manual: bool):
        if info:
            self._pending_update = info
            self._build_menu()
            self.tray.showMessage(
                "AFV Tracker update available",
                f"Version {info['version']} is available. "
                f"Open the tray menu to download it.",
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )
        elif manual:
            QMessageBox.information(None, "AFV Tracker",
                                     "You're running the latest version.")

    def _open_update_page(self):
        if self._pending_update:
            import webbrowser
            webbrowser.open(self._pending_update["url"])

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def _show_tracker(self):
        if self.main_window is None:
            from gui_web import MainWindow
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
        """Closing the window exits the app entirely — no hide-to-tray."""
        event.accept()
        self._quit()

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

        if self._pending_update:
            upd_lbl = f"⬆  Update to v{self._pending_update['version']} available"
            menu.addAction(upd_lbl).triggered.connect(self._open_update_page)
        else:
            menu.addAction("Check for Updates…").triggered.connect(
                lambda: self._check_for_updates(manual=True)
            )

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
        self.tray.hide()
        stop_server(self._server)
        if self.main_window:
            # _quit_app stops tracking/net/discord/sync workers, hides the
            # window's tray icon and calls QApplication.quit() itself.
            try:
                self.main_window._quit_app()
                return
            except Exception:
                pass
        self.app.quit()


# ── Single-instance lock ──────────────────────────────────────────────────────
# Closing the tracker window hides it to the tray instead of exiting, so
# launching the exe again later (shortcut, taskbar, startup) would otherwise
# spawn a second independent GUI process with its own DiscordPresenceWorker,
# SimConnect poller, etc. racing the first. QSharedMemory.create() fails if
# the segment already exists, which on Windows is reliably released by the
# OS when the owning process exits (even on a crash), so no manual cleanup
# of a stale lock is needed.
_instance_lock = QSharedMemory("AFVTracker-SingleInstance-v1")


def _acquire_single_instance() -> bool:
    return _instance_lock.create(1)


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

    # QtWebEngine (web UI in gui_web) needs shared OpenGL contexts enabled
    # before the QApplication exists, or the later QWebEngineWidgets import fails.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setApplicationName("AFV Tracker")
    app.setOrganizationName("Africana Virtual Airways")
    app.setQuitOnLastWindowClosed(False)   # stay alive in tray

    if not _acquire_single_instance():
        log.warning("AFV Tracker is already running — exiting this instance.")
        QMessageBox.information(None, "AFV Tracker",
                                 "AFV Tracker is already running.\n"
                                 "Check your system tray for the icon.")
        sys.exit(0)

    # Start the server subprocess before building the GUI
    _server = start_server()
    # Give it a moment to bind the port before the client tries to connect
    time.sleep(1.5)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "AFV Tracker",
                             "System tray is not available on this system.")
        stop_server(_server)
        sys.exit(1)

    launcher = AFVLauncher(app, _server)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
