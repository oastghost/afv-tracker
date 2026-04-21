"""
AFV Tracker - MSFS Watcher
Sits in the system tray and automatically launches the AFV Tracker
when Microsoft Flight Simulator 2020 or 2024 is detected running.

Right-click the tray icon for options.
"""

import sys
import os
import time
import threading
import subprocess
import winreg
from pathlib import Path

import psutil
import pystray
from PIL import Image, ImageDraw

# ── Paths ──────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent.resolve()
MAIN_PY     = SCRIPT_DIR / "main.py"
PYTHON_EXE  = sys.executable
WATCHER_PY  = Path(__file__).resolve()

STARTUP_REG_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "AFVTrackerWatcher"

MSFS_EXE = "FlightSimulator.exe"
POLL_SECS = 5


# ── State ──────────────────────────────────────────────────────────────────────

class WatcherState:
    def __init__(self):
        self.msfs_running   = False
        self.tracker_pid    = None   # PID of launched tracker process
        self.msfs_version   = "MSFS"
        self.enabled        = True   # auto-launch enabled


state = WatcherState()


# ── Process helpers ────────────────────────────────────────────────────────────

def find_msfs() -> tuple[bool, str]:
    """Returns (is_running, version_string)."""
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            if proc.info["name"] == MSFS_EXE:
                exe_path = (proc.info.get("exe") or "").lower()
                version  = "MSFS 2024" if "2024" in exe_path else "MSFS 2020"
                return True, version
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False, ""


def is_tracker_running() -> bool:
    """True if our client main.py is already running."""
    if state.tracker_pid:
        try:
            proc = psutil.Process(state.tracker_pid)
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                return True
        except psutil.NoSuchProcess:
            pass
        state.tracker_pid = None

    # Fallback: scan all python processes
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] and "python" in proc.info["name"].lower():
                cmdline = proc.info.get("cmdline") or []
                if any("main.py" in arg for arg in cmdline):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def launch_tracker():
    proc = subprocess.Popen(
        [PYTHON_EXE, str(MAIN_PY)],
        cwd=str(SCRIPT_DIR),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    state.tracker_pid = proc.pid
    return proc.pid


# ── Startup registry ───────────────────────────────────────────────────────────

def is_in_startup() -> bool:
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY)
        winreg.QueryValueEx(key, STARTUP_REG_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False


def add_to_startup():
    cmd = f'"{PYTHON_EXE}" "{WATCHER_PY}"'
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0,
                         winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, cmd)
    winreg.CloseKey(key)


def remove_from_startup():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_KEY, 0,
                             winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, STARTUP_REG_NAME)
        winreg.CloseKey(key)
    except FileNotFoundError:
        pass


# ── Tray icon drawing ──────────────────────────────────────────────────────────

def _make_icon(active: bool = False) -> Image.Image:
    """Draw a small AFV icon — red circle, white 'A'."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg_color = (196, 30, 58, 255) if active else (80, 80, 80, 255)
    draw.ellipse([4, 4, size - 4, size - 4], fill=bg_color)

    # Simple "A" shape using lines
    cx = size // 2
    draw.line([(cx, 10), (cx - 14, 50)], fill="white", width=5)
    draw.line([(cx, 10), (cx + 14, 50)], fill="white", width=5)
    draw.line([(cx - 8, 35), (cx + 8, 35)], fill="white", width=4)

    return img


# ── Watch loop ─────────────────────────────────────────────────────────────────

def watch_loop(icon: pystray.Icon):
    """Runs in a background thread. Polls for MSFS and auto-launches."""
    while True:
        time.sleep(POLL_SECS)

        running, version = find_msfs()

        if running != state.msfs_running:
            state.msfs_running  = running
            state.msfs_version  = version if running else "MSFS"
            icon.icon = _make_icon(active=running)
            _rebuild_menu(icon)

        if running and state.enabled and not is_tracker_running():
            pid = launch_tracker()
            _rebuild_menu(icon)
            try:
                icon.notify(
                    f"AFV Tracker launched for {version}",
                    "Africana Virtual Airways"
                )
            except Exception:
                pass  # notify not supported on all Windows versions


# ── Menu ───────────────────────────────────────────────────────────────────────

def _status_text() -> str:
    if state.msfs_running:
        return f"● {state.msfs_version} detected"
    return "○ Waiting for MSFS..."


def _toggle_enabled(icon, item):
    state.enabled = not state.enabled
    _rebuild_menu(icon)


def _toggle_startup(icon, item):
    if is_in_startup():
        remove_from_startup()
    else:
        add_to_startup()
    _rebuild_menu(icon)


def _launch_now(icon, item):
    if not is_tracker_running():
        launch_tracker()
        _rebuild_menu(icon)


def _quit(icon, item):
    icon.stop()


def _make_menu(icon=None) -> pystray.Menu:
    startup_label = (
        "Remove from startup" if is_in_startup() else "Run at Windows startup"
    )
    auto_label = (
        "Auto-launch: ON" if state.enabled else "Auto-launch: OFF"
    )
    tracker_label = (
        "Tracker: running" if is_tracker_running() else "Tracker: not running"
    )

    return pystray.Menu(
        pystray.MenuItem(_status_text(),    None, enabled=False),
        pystray.MenuItem(tracker_label,     None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(auto_label,        _toggle_enabled),
        pystray.MenuItem("Launch now",      _launch_now,
                         enabled=not is_tracker_running()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(startup_label,     _toggle_startup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit watcher",    _quit),
    )


def _rebuild_menu(icon: pystray.Icon):
    icon.menu = _make_menu(icon)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    icon = pystray.Icon(
        name="AFVWatcher",
        icon=_make_icon(active=False),
        title="AFV Tracker — MSFS Watcher",
        menu=_make_menu(),
    )

    # Start the watch loop in a daemon thread
    t = threading.Thread(target=watch_loop, args=(icon,), daemon=True)
    t.start()

    icon.run()


if __name__ == "__main__":
    main()
