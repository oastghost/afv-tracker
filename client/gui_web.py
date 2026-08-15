"""
AFV Tracker - Web MainWindow
Frameless PyQt6 window that hosts the modern web UI (client/web) inside a
QWebEngineView and wires it to the existing Python backend through a
QWebChannel Bridge.

All flight-tracking, phpVMS ACARS/PIREP, gate, Discord and networking logic
is reused from the same worker modules the legacy PyQt UI used — only the
presentation layer changed. See web_bridge.py for the JS <-> Python protocol.
"""

import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebChannel import QWebChannel

import config
import sounds
from simbrief import OFP
from simconnect_client import SimConnectWorker, Telemetry
from flight_tracker import FlightTracker, FlightPhase
from gate_manager import GateManager, GateAssignment
from network_client import NetworkClient
from discord_presence import DiscordPresenceWorker
from phpvms_sync_worker import PhpVmsSyncWorker
from phpvms_integration import PhpVmsClient
import phpvms_auth
from web_bridge import Bridge

# Reuse the airport coordinate table and the small fetch workers from the
# legacy GUI module (importing it only defines classes/constants — it does not
# create any windows).
from gui import _AIRPORT_COORDS, SimBriefFetchWorker, GateFetchWorker

log = logging.getLogger(__name__)

LBS_TO_KG = 0.453592


def _web_dir() -> Path:
    """Locate the bundled web/ assets (source tree or frozen exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web"
    return Path(__file__).parent / "web"


def _asset(name: str) -> str:
    """Resolve a client/assets file (source tree or frozen exe)."""
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "assets" / name)
    return str(Path(__file__).parent / "assets" / name)


def app_icon() -> QIcon:
    """The Africana Virtual Airways window/tray icon."""
    ico = _asset("icon.ico")
    icon = QIcon(ico)
    if icon.isNull():
        icon = QIcon(_asset("icon.png"))
    return icon


# phpVMS v7 PirepStatus codes — set via PUT /api/pireps/{id}.
_PIREP_STATUS_MAP = {
    FlightPhase.PRE_FLIGHT: "BST",   # BOARDING
    FlightPhase.TAXI_OUT:   "TXI",   # TAXI
    FlightPhase.TAKEOFF:    "TOF",   # TAKEOFF
    FlightPhase.CLIMB:      "ICL",   # INIT_CLIMB
    FlightPhase.CRUISE:     "ENR",   # ENROUTE
    FlightPhase.DESCENT:    "ENR",   # ENROUTE
    FlightPhase.APPROACH:   "TEN",   # APPROACH
    FlightPhase.LANDING:    "LDG",   # LANDING
    FlightPhase.TAXI_IN:    "LAN",   # LANDED
    FlightPhase.PARKED:     "ARR",   # ARRIVED
}


class MainWindow(QMainWindow):
    # Cross-thread signals — emitted from background threads, delivered on the
    # Qt main thread so bridge events are always pushed from the UI thread.
    _sig_ofp          = pyqtSignal(object)
    _sig_ofp_error    = pyqtSignal(str)
    _sig_bid          = pyqtSignal(object)
    _sig_bids         = pyqtSignal(object)
    _sig_prefile      = pyqtSignal(object)
    _sig_gate_board   = pyqtSignal(str, object)
    _sig_acars_ok     = pyqtSignal(bool)
    _sig_queue_flush  = pyqtSignal(int)
    _sig_pirep_filed  = pyqtSignal(bool)
    _sig_history      = pyqtSignal(object)
    _sig_profile      = pyqtSignal(object)
    _sig_conn_test    = pyqtSignal(bool)
    _sig_login        = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Africana Virtual Airways — Flight Tracker")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(1040, 680)
        self.resize(1360, 860)
        # Frameless with a custom web title bar; keep it a normal top-level
        # window so it still appears in the taskbar and supports system move.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )

        self._cfg = config.load_config()
        self._ofp: Optional[OFP] = None
        self._tracking = False
        self._gate_requested = False
        self._last_tel: Optional[Telemetry] = None
        self._acars_last_sent = 0.0
        self._discord_start_ts: Optional[float] = None
        self._ui_ready = False
        # Data for the last completed flight, held until the pilot submits the
        # PIREP from the completion dialog (Stratos-style manual submit).
        self._pending_pirep: Optional[dict] = None

        # ── Backend workers / managers (reused unchanged) ────────────────
        self._simconnect_worker: Optional[SimConnectWorker] = None
        self._flight_tracker: Optional[FlightTracker] = None
        self._simbrief_worker: Optional[SimBriefFetchWorker] = None
        self._gate_worker: Optional[GateFetchWorker] = None

        self._gate_manager = GateManager(
            self._cfg.get("server_url", "http://localhost:8765"),
            pilot_id=self._cfg.get("vatsim_cid", ""),
            pilot_name=self._cfg.get("pilot_name", ""),
        )

        self._vms = PhpVmsClient()
        self._vms_sync = PhpVmsSyncWorker(self)
        self._vms_sync.start()

        self._net_client: Optional[NetworkClient] = None
        self._online_pilots: dict[str, dict] = {}

        self._discord: Optional[DiscordPresenceWorker] = None
        if self._cfg.get("discord_rpc_enabled") and self._cfg.get("discord_client_id"):
            self._discord = DiscordPresenceWorker(self._cfg["discord_client_id"], self)
            self._discord.start()

        # ── Web view + channel ───────────────────────────────────────────
        self.bridge = Bridge()
        self.bridge.command_received.connect(self._on_command)

        self._view = QWebEngineView(self)
        self.setCentralWidget(self._view)

        settings = self._view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True)

        self._channel = QWebChannel(self._view.page())
        self._channel.registerObject("bridge", self.bridge)
        self._view.page().setWebChannel(self._channel)

        index = _web_dir() / "index.html"
        self._view.load(QUrl.fromLocalFile(str(index)))

        # ── Wire cross-thread signals ────────────────────────────────────
        self._sig_ofp.connect(self._on_ofp_loaded)
        self._sig_ofp_error.connect(self._on_ofp_error)
        self._sig_bid.connect(self._on_bid_ready)
        self._sig_bids.connect(lambda b: self.bridge.emit_event("bids", b))
        self._sig_prefile.connect(self._on_prefile_result)
        self._sig_gate_board.connect(
            lambda ap, g: self.bridge.emit_event("gate:board", {"airport": ap, "gates": g}))
        self._sig_acars_ok.connect(
            lambda ok: self.bridge.emit_event("phpvms", {"connected": ok, "label": "phpVMS"}))
        self._sig_queue_flush.connect(
            lambda n: self.bridge.emit_event("toast", {"level": "info",
                       "message": f"Resent {n} queued phpVMS update(s)."}))
        self._sig_pirep_filed.connect(self._on_pirep_filed)
        self._sig_history.connect(lambda h: self.bridge.emit_event("history", h))
        self._sig_profile.connect(lambda p: self.bridge.emit_event("profile", p))
        self._sig_conn_test.connect(
            lambda ok: self.bridge.emit_event("phpvms",
                       {"connected": ok, "label": "phpVMS"}))
        self._sig_login.connect(self._on_login_result)

        # ── Timers ───────────────────────────────────────────────────────
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._retry_offline_queue)
        self._queue_timer.start(45_000)

        self._setup_tray()

    # ==================================================================
    # Command dispatch (JS → Python)
    # ==================================================================

    @pyqtSlot(str, str)
    def _on_command(self, action: str, payload_json: str):
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except (ValueError, TypeError):
            payload = {}

        handler = {
            "ready":            self._on_ui_ready,
            "track:toggle":     self._toggle_tracking,
            "track:start":      lambda p: self._start_tracking(),
            "track:stop":       lambda p: self._stop_tracking(),
            "simbrief:fetch":   lambda p: self._fetch_simbrief_manual(),
            "bids:refresh":     lambda p: self._refresh_bids(),
            "bid:select":       self._select_bid,
            "history:refresh":  lambda p: self._refresh_history(),
            "profile:refresh":  lambda p: self._refresh_profile(),
            "settings:get":     lambda p: self._push_settings(),
            "settings:save":    self._save_settings,
            "login:submit":     self._do_login,
            "logout":           lambda p: self._logout(),
            "connection:test":  lambda p: self._test_connection(),
            "pirep:submit":     lambda p: self._submit_pirep(),
            "open:external":    self._open_external,
            "window:move":      lambda p: self._start_move(),
            "window:min":       lambda p: self.showMinimized(),
            "window:max":       lambda p: self._toggle_maximize(),
            "window:close":     lambda p: self.close(),
            "window:pin":       self._set_pin,
        }.get(action)

        if handler is None:
            log.warning("Unknown UI command: %s", action)
            return
        try:
            handler(payload)
        except Exception:
            log.exception("Command handler failed for %s", action)

    # ==================================================================
    # UI lifecycle
    # ==================================================================

    def _on_ui_ready(self, _payload=None):
        self._ui_ready = True
        self._push_settings()
        self.bridge.emit_event("tracking", {"active": self._tracking})
        self._tick_clock()
        # Kick off initial data loads if credentials exist.
        if self._cfg.get("simbrief_id"):
            QTimer.singleShot(300, self._auto_fetch)
        if self._cfg.get("vatsim_cid"):
            QTimer.singleShot(600, self._start_network_client)
        if self._vms.api_key:
            QTimer.singleShot(400, self._refresh_bids)
            QTimer.singleShot(700, self._refresh_profile)
            QTimer.singleShot(1000, self._refresh_history)

    # ==================================================================
    # Window chrome
    # ==================================================================

    def _start_move(self):
        wh = self.windowHandle()
        if wh is not None:
            wh.startSystemMove()

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _set_pin(self, payload):
        on = bool(payload.get("on"))
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def _open_external(self, payload):
        url = payload.get("url", "")
        if url:
            import webbrowser
            webbrowser.open(url)

    # ==================================================================
    # Settings
    # ==================================================================

    def _push_settings(self, _payload=None):
        cfg = config.load_config()
        # Never leak nothing sensitive that the UI can't already see — the UI
        # is local, so we send the API key so the field can be pre-filled.
        self.bridge.emit_event("settings", cfg)

    def _save_settings(self, payload):
        cfg = config.load_config()
        for key in ("vatsim_cid", "simbrief_id", "pilot_name", "discord",
                    "VA_URL", "Pilot_Key", "weight_unit", "theme",
                    "sound_enabled", "discord_rpc_enabled", "discord_client_id",
                    "simconnect_poll_interval", "server_url"):
            if key in payload:
                cfg[key] = payload[key]
        config.save_config(cfg)
        self._cfg = cfg
        self._vms.refresh_credentials()
        # sounds.play() reads sound_enabled from config live — nothing to toggle.
        self.bridge.emit_event("toast", {"level": "success",
                                          "message": "Settings saved."})
        self._push_settings()
        # Re-run initial loads with the new credentials.
        if cfg.get("simbrief_id"):
            self._auto_fetch()
        if cfg.get("vatsim_cid"):
            self._start_network_client()
        if self._vms.api_key:
            self._refresh_bids()
            self._refresh_profile()

    # ==================================================================
    # Login (Stratos-style: email + password → API key behind the scenes)
    # ==================================================================

    def _do_login(self, payload):
        email = (payload.get("email") or "").strip()
        password = payload.get("password") or ""
        api_key = (payload.get("api_key") or "").strip()
        base_url = config.get("VA_URL", "https://africanava.ddns.net")

        def _run():
            if api_key:
                result = phpvms_auth.validate_key(base_url, api_key)
            else:
                result = phpvms_auth.login(base_url, email, password)
            self._sig_login.emit(result)
        threading.Thread(target=_run, daemon=True).start()

    def _on_login_result(self, result: dict):
        if not result.get("success"):
            self.bridge.emit_event("login:result", {
                "success": False,
                "error": result.get("error", "Sign-in failed."),
            })
            return

        user = result.get("user", {}) or {}
        cfg = config.load_config()
        cfg["Pilot_Key"] = result["api_key"]
        if user.get("name") and not cfg.get("pilot_name"):
            cfg["pilot_name"] = user["name"]
        config.save_config(cfg)
        self._cfg = cfg
        self._vms.refresh_credentials()

        self.bridge.emit_event("login:result", {
            "success": True, "name": user.get("name", ""),
        })
        self._push_settings()
        self.bridge.emit_event("phpvms", {"connected": True, "label": "phpVMS"})
        self._refresh_bids()
        self._refresh_profile()
        self._refresh_history()

    def _logout(self):
        cfg = config.load_config()
        cfg["Pilot_Key"] = ""
        config.save_config(cfg)
        self._cfg = cfg
        self._vms.refresh_credentials()
        self.bridge.emit_event("phpvms", {"connected": False, "label": "phpVMS (no key)"})
        # Pushing settings with an empty key makes the UI show the login gate.
        self._push_settings()

    def _test_connection(self):
        def _run():
            ok = self._vms.test_connection()
            self._sig_conn_test.emit(ok)
        threading.Thread(target=_run, daemon=True).start()

    # ==================================================================
    # Clock
    # ==================================================================

    def _tick_clock(self):
        if not self._ui_ready:
            return
        now = datetime.now(timezone.utc)
        self.bridge.emit_event("clock", {"utc": now.strftime("%H:%M:%S")})

    # ==================================================================
    # SimBrief
    # ==================================================================

    def _auto_fetch(self):
        sb = config.get("simbrief_id", "")
        if sb:
            self._fetch_simbrief(sb)

    def _fetch_simbrief_manual(self):
        sb = config.get("simbrief_id", "")
        if not sb:
            self.bridge.emit_event("toast", {"level": "warn",
                "message": "Set your SimBrief ID in Settings first."})
            return
        self._fetch_simbrief(sb)

    def _fetch_simbrief(self, pilot_id: str):
        if self._simbrief_worker and self._simbrief_worker.isRunning():
            return
        self.bridge.emit_event("simbrief", {"connected": False, "loading": True})
        self._simbrief_worker = SimBriefFetchWorker(pilot_id, self)
        self._simbrief_worker.success.connect(self._on_ofp_loaded)
        self._simbrief_worker.failure.connect(self._on_ofp_error)
        self._simbrief_worker.start()

    def _on_ofp_loaded(self, ofp: OFP):
        self._ofp = ofp
        self.bridge.emit_event("simbrief", {"connected": True})
        self.bridge.emit_event("ofp", self._ofp_to_dict(ofp))

        dest_coords = _AIRPORT_COORDS.get(ofp.destination_icao)
        if self._flight_tracker and dest_coords:
            self._flight_tracker.set_destination(*dest_coords)

        # Gate board for destination (background).
        def _fetch_board():
            gates = self._gate_manager.fetch_gate_board(ofp.destination_icao)
            if gates:
                self._sig_gate_board.emit(ofp.destination_icao, gates)
        threading.Thread(target=_fetch_board, daemon=True).start()

        # Match a phpVMS bid to this OFP (background).
        if not self._vms.api_key:
            self.bridge.emit_event("phpvms", {"connected": False, "label": "phpVMS (no key)"})
        else:
            flight_number = ofp.flight_number

            def _fetch_bid():
                bids = self._vms.get_bids()
                self._sig_bids.emit(self._bids_to_list(bids))
                if not bids:
                    self._sig_bid.emit(None)
                    return
                match = next(
                    (b for b in bids
                     if str(b.get('flight', {}).get('flight_number', '')) in str(flight_number)),
                    bids[0],
                )
                self._sig_bid.emit(match)
            threading.Thread(target=_fetch_bid, daemon=True).start()

    def _on_ofp_error(self, msg: str):
        self.bridge.emit_event("simbrief", {"connected": False})
        self.bridge.emit_event("ofp:error", {"message": msg})
        self.bridge.emit_event("toast", {"level": "error", "message": f"SimBrief: {msg}"})

    # ==================================================================
    # phpVMS bids / prefile / history / profile
    # ==================================================================

    def _refresh_bids(self):
        if not self._vms.api_key:
            return

        def _run():
            bids = self._vms.get_bids()
            self._sig_bids.emit(self._bids_to_list(bids))
        threading.Thread(target=_run, daemon=True).start()

    def _select_bid(self, payload):
        bid_id = payload.get("bid_id")
        if bid_id is None or not self._vms.api_key:
            return

        def _run():
            bids = self._vms.get_bids()
            match = next((b for b in bids if str(b.get("id")) == str(bid_id)), None)
            if match:
                self._sig_bid.emit(match)
        threading.Thread(target=_run, daemon=True).start()

    def _on_bid_ready(self, bid):
        if bid is None:
            self.bridge.emit_event("phpvms", {"connected": True, "label": "phpVMS"})
            self.bridge.emit_event("toast", {"level": "warn",
                "message": "No phpVMS bids — book a flight on the website first."})
            return
        self.bridge.emit_event("phpvms", {"connected": True, "label": "phpVMS"})
        self.bridge.emit_event("bid", self._bid_to_dict(bid))

        # Prefile a PIREP from this bid, using the loaded OFP for fuel/level/route.
        if self._ofp:
            planned_fuel = self._ofp.fuel.total_lbs
            flight_level = self._ofp.cruise_altitude
            route = self._ofp.route or ""

            def _prefile():
                pirep_id = self._vms.prefile_pirep(
                    bid_data=bid, planned_fuel=planned_fuel,
                    flight_level=flight_level, route=route)
                self._sig_prefile.emit(pirep_id)
            self._vms_sync.submit(_prefile)

    def _on_prefile_result(self, pirep_id):
        if pirep_id:
            self.bridge.emit_event("prefile", {"pirep_id": pirep_id})
            self.bridge.emit_event("toast", {"level": "success",
                "message": f"PIREP prefiled (ID {pirep_id}) — ready to fly."})
            if self._flight_tracker:
                status = _PIREP_STATUS_MAP.get(self._flight_tracker.phase)
                if status:
                    self._vms_sync.submit(lambda: self._vms.update_pirep_status(status))
        else:
            self.bridge.emit_event("toast", {"level": "error",
                "message": "Bid matched but prefile failed — check logs."})

    def _refresh_history(self):
        if not self._vms.api_key:
            return

        def _run():
            pireps = self._vms.get_pireps(limit=40)
            self._sig_history.emit([self._pirep_to_dict(p) for p in pireps])
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_profile(self):
        if not self._vms.api_key:
            return

        def _run():
            user = self._vms.get_user()
            self._sig_profile.emit(self._user_to_dict(user))
        threading.Thread(target=_run, daemon=True).start()

    # ==================================================================
    # Tracking
    # ==================================================================

    def _toggle_tracking(self, _payload=None):
        if not self._tracking:
            self._start_tracking()
        else:
            self._stop_tracking()

    def _start_tracking(self):
        dest_lat, dest_lon = 0.0, 0.0
        if self._ofp:
            dest_lat, dest_lon = _AIRPORT_COORDS.get(self._ofp.destination_icao, (0.0, 0.0))

        self._flight_tracker = FlightTracker(dest_lat, dest_lon, self)
        self._flight_tracker.phase_changed.connect(self._on_phase_changed)
        self._flight_tracker.approach_reached.connect(self._on_approach)
        self._flight_tracker.flight_complete.connect(self._on_flight_complete)

        self._discord_start_ts = time.time()
        if self._discord:
            self._push_discord_presence(FlightPhase.PRE_FLIGHT)

        interval = self._cfg.get("simconnect_poll_interval", 5)
        self._simconnect_worker = SimConnectWorker(interval, self)
        self._simconnect_worker.telemetry_update.connect(self._on_telemetry)
        self._simconnect_worker.connected.connect(self._on_sim_connected)
        self._simconnect_worker.disconnected.connect(self._on_sim_disconnected)
        self._simconnect_worker.error.connect(self._on_sim_error)
        self._simconnect_worker.start()

        self._pirep_health_timer = QTimer(self)
        self._pirep_health_timer.timeout.connect(self._check_pirep_health)
        self._pirep_health_timer.start(60_000)

        self._tracking = True
        self._gate_requested = False
        self.bridge.emit_event("tracking", {"active": True})
        self.bridge.emit_event("gate", None)   # clear any stale gate banner
        self.bridge.emit_event("toast", {"level": "info", "message": "Connecting to MSFS…"})

    def _stop_tracking(self):
        if self._simconnect_worker:
            self._simconnect_worker.stop()
            self._simconnect_worker = None
        if hasattr(self, "_pirep_health_timer"):
            self._pirep_health_timer.stop()
        if self._discord:
            self._discord.clear_activity()

        self._tracking = False
        self.bridge.emit_event("tracking", {"active": False})
        self.bridge.emit_event("sim", {"connected": False})
        self.bridge.emit_event("toast", {"level": "info", "message": "Tracking stopped."})

    @pyqtSlot(object)
    def _on_telemetry(self, tel: Telemetry):
        self._last_tel = tel
        if not self._flight_tracker:
            return
        self._flight_tracker.update(tel)
        dist = self._flight_tracker.distance_to_dest_nm
        elapsed = self._flight_tracker.elapsed_seconds
        phase = self._flight_tracker.phase

        self.bridge.emit_event("telemetry", self._telemetry_to_dict(tel, phase, elapsed, dist))

        # Throttled live ACARS push to phpVMS (off the main thread via sync worker).
        acars_interval = 15 if phase in (
            FlightPhase.APPROACH, FlightPhase.LANDING, FlightPhase.TAXI_IN) else 30
        now = time.monotonic()
        if self._vms.current_pirep_id and now - self._acars_last_sent >= acars_interval:
            self._acars_last_sent = now
            _lat, _lon, _alt = tel.latitude, tel.longitude, tel.altitude_ft
            _gs = tel.groundspeed_kts
            _hdg = getattr(tel, "heading_true", tel.heading_mag)
            _state = phase.vms_code
            _dist_flown = self._flight_tracker.distance_flown_nm
            _ft_min = elapsed / 60.0
            _status = _PIREP_STATUS_MAP.get(phase)
            _vs = int(getattr(tel, "vertical_speed_fpm", 0) or 0)

            def _send_acars():
                ok = self._vms.update_acars(
                    lat=_lat, lon=_lon, alt=_alt, gs=_gs, heading=_hdg,
                    state=_state, vs=_vs, distance_nm=_dist_flown)
                if _status:
                    self._vms.update_pirep_status(
                        _status, flight_time_min=_ft_min, distance_nm=_dist_flown)
                self._sig_acars_ok.emit(ok)
            self._vms_sync.submit(_send_acars)

        self._broadcast_own_telemetry(tel)

    @pyqtSlot(object)
    def _on_phase_changed(self, phase: FlightPhase):
        self.bridge.emit_event("phase", {"phase": phase.value})
        self._push_discord_presence(phase)
        if phase == FlightPhase.TAKEOFF:
            sounds.play("flight_start")
        elif phase == FlightPhase.LANDING:
            sounds.play("landing")
        if phase == FlightPhase.APPROACH:
            self._acars_last_sent = 0.0

        status_code = _PIREP_STATUS_MAP.get(phase)
        if status_code and self._vms.current_pirep_id:
            _elapsed_min = self._flight_tracker.elapsed_seconds / 60.0
            _dist = self._flight_tracker.distance_flown_nm
            self._vms_sync.submit(
                lambda: self._vms.update_pirep_status(
                    status_code, flight_time_min=_elapsed_min, distance_nm=_dist))

        if phase in (FlightPhase.APPROACH, FlightPhase.LANDING,
                     FlightPhase.TAXI_IN, FlightPhase.PARKED):
            if not self._gate_requested and self._ofp:
                self._on_approach(self._flight_tracker.distance_to_dest_nm)

        if phase == FlightPhase.PARKED:
            assignment = self._gate_manager.current_assignment
            if assignment and not assignment.fallback:
                threading.Thread(
                    target=self._gate_manager.release_gate,
                    args=(assignment.airport_icao, assignment.gate_number),
                    daemon=True).start()

    def _on_approach(self, dist_nm: float):
        if self._gate_requested or not self._ofp:
            return
        self._gate_requested = True
        self._gate_worker = GateFetchWorker(
            self._gate_manager, self._ofp.destination_icao,
            self._ofp.aircraft_icao, self._ofp.registration or "", self)
        self._gate_worker.success.connect(self._on_gate_assigned)
        self._gate_worker.failure.connect(
            lambda m: self.bridge.emit_event("toast", {"level": "warn", "message": f"Gate: {m}"}))
        self._gate_worker.start()

    def _on_gate_assigned(self, assignment: GateAssignment):
        self.bridge.emit_event("gate", {
            "gate_number": assignment.gate_number,
            "airport": assignment.airport_icao,
            "terminal": getattr(assignment, "terminal", ""),
            "fallback": assignment.fallback,
        })
        sounds.play("gate_assigned")

    @pyqtSlot(str)
    def _on_sim_connected(self, version: str):
        self.bridge.emit_event("sim", {"connected": True, "version": version})
        self.bridge.emit_event("toast", {"level": "success", "message": f"Connected to {version}."})

    @pyqtSlot()
    def _on_sim_disconnected(self):
        self.bridge.emit_event("sim", {"connected": False, "retrying": True})

    @pyqtSlot(str)
    def _on_sim_error(self, msg: str):
        self.bridge.emit_event("sim", {"connected": False, "error": True})
        self.bridge.emit_event("toast", {"level": "error", "message": f"SimConnect: {msg}"})
        sounds.play("error")
        self._stop_tracking()

    @pyqtSlot(dict)
    def _on_flight_complete(self, data: dict):
        if not self._ofp:
            return
        cfg = config.load_config()
        payload = {
            "vatsim_cid":    cfg.get("vatsim_cid", ""),
            "pilot_name":    cfg.get("pilot_name", ""),
            "callsign":      self._ofp.callsign,
            "flight_number": self._ofp.flight_number,
            "origin":        self._ofp.origin_icao,
            "destination":   self._ofp.destination_icao,
            "aircraft_type": self._ofp.aircraft_icao,
            **data,
        }
        self._post_flight_log(payload)

        secs = int(data.get("flight_time_sec", 0))
        flight_time_mins = secs // 60
        fuel_used = data.get("fuel_used_lbs", 0) or 0
        distance_nm = data.get("distance_flown_nm", 0) or 0
        landing_rate = data.get("landing_rate_fpm") or 0
        log_text = (
            f"Filed by Africana Tracker.\n"
            f"Block time: {flight_time_mins // 60:02d}:{flight_time_mins % 60:02d}\n"
            f"Distance flown: {distance_nm:.1f} nm\n"
            f"Fuel used: {fuel_used:.0f} lbs\n"
            f"Landing rate: {landing_rate:.0f} fpm")

        # Hold the PIREP data — the pilot files it explicitly from the
        # completion dialog (Submit PIREP button), Stratos-style.
        self._pending_pirep = dict(
            flight_time_min=flight_time_mins, fuel_used=fuel_used,
            distance_nm=distance_nm, landing_rate=landing_rate, log_text=log_text)

        self.bridge.emit_event("flightComplete", {
            "flight_number": self._ofp.flight_number,
            "origin": self._ofp.origin_icao,
            "destination": self._ofp.destination_icao,
            "flight_time": f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}",
            "landing_rate": data.get("landing_rate_fpm"),
            "fuel_used_lbs": data.get("fuel_used_lbs"),
            "distance_flown_nm": data.get("distance_flown_nm"),
            "has_pirep": bool(self._vms.current_pirep_id),
        })

    def _submit_pirep(self):
        """File the held PIREP to phpVMS on the pilot's explicit request."""
        data = self._pending_pirep
        if not data:
            self.bridge.emit_event("pirepResult",
                {"success": False, "message": "No completed flight to submit."})
            return
        if not self._vms.current_pirep_id:
            self.bridge.emit_event("pirepResult", {"success": False,
                "message": "No active PIREP on phpVMS — the prefile did not succeed. "
                           "Check that your bid's aircraft is available, then re-fly."})
            return

        def _file():
            ok = self._vms.file_pirep(**data)
            self._sig_pirep_filed.emit(ok)
        self._vms_sync.submit(_file)

    def _on_pirep_filed(self, success: bool):
        self.bridge.emit_event("pirepResult", {
            "success": success,
            "message": "PIREP filed on phpVMS." if success
                       else "PIREP filing failed — it was queued for retry.",
        })
        if success:
            self._pending_pirep = None
            self.bridge.emit_event("toast", {"level": "success", "message": "PIREP filed on phpVMS."})
            QTimer.singleShot(1500, self._refresh_history)
            QTimer.singleShot(2000, self._refresh_profile)
        else:
            self.bridge.emit_event("toast", {"level": "error", "message": "PIREP filing failed — see logs."})

    def _post_flight_log(self, payload: dict):
        import requests as req
        server = config.get("server_url", "http://localhost:8765")

        def _post():
            try:
                req.post(f"{server}/api/flights/complete", json=payload, timeout=10)
            except Exception as e:
                log.warning("Failed to post flight log: %s", e)
        threading.Thread(target=_post, daemon=True).start()

    def _check_pirep_health(self):
        if not self._vms.current_pirep_id:
            return

        def _health():
            active = self._vms.is_pirep_active()
            self._sig_acars_ok.emit(active)
        threading.Thread(target=_health, daemon=True).start()

    def _retry_offline_queue(self):
        def _retry():
            sent = self._vms.retry_pending()
            if sent:
                self._sig_queue_flush.emit(sent)
        self._vms_sync.submit(_retry)

    def _push_discord_presence(self, phase: FlightPhase):
        if not self._discord:
            return
        origin = self._ofp.origin_icao if self._ofp else "????"
        dest = self._ofp.destination_icao if self._ofp else "????"
        callsign = self._ofp.callsign if self._ofp else ""
        state = f"{phase.value} · {callsign}" if callsign else phase.value
        self._discord.update_activity(
            details=f"{origin} → {dest}", state=state,
            start_ts=self._discord_start_ts)

    # ==================================================================
    # Network (multi-pilot roster)
    # ==================================================================

    def _start_network_client(self):
        pid = config.get("vatsim_cid", "")
        if not pid:
            return
        if self._net_client and self._net_client.isRunning():
            self._net_client.stop()
            self._net_client.wait(2000)
        server = config.get("server_url", "http://localhost:8765")
        self._net_client = NetworkClient(server_url=server, pilot_id=pid, parent=self)
        self._net_client.connected.connect(
            lambda: self.bridge.emit_event("network", {"connected": True}))
        self._net_client.disconnected.connect(
            lambda: self.bridge.emit_event("network", {"connected": False}))
        self._net_client.roster_received.connect(self._on_roster_received)
        self._net_client.pilot_update.connect(
            lambda d: self.bridge.emit_event("pilot", d))
        self._net_client.pilot_offline.connect(
            lambda pid: self.bridge.emit_event("pilot:offline", {"pilot_id": pid}))
        self._net_client.gate_assigned.connect(
            lambda d: self.bridge.emit_event("gate:remote_assigned", d))
        self._net_client.gate_released.connect(
            lambda d: self.bridge.emit_event("gate:remote_released", d))
        self._net_client.start()

    def _on_roster_received(self, pilots: list):
        own = config.get("vatsim_cid", "")
        self._online_pilots = {p.get("pilot_id", ""): p for p in pilots}
        self.bridge.emit_event("roster", [p for p in pilots if p.get("pilot_id") != own])

    def _broadcast_own_telemetry(self, tel: Telemetry):
        if not self._net_client or not self._net_client.isRunning() or not self._ofp:
            return
        phase_str = self._flight_tracker.phase.value if self._flight_tracker else "UNKNOWN"
        self._net_client.send_pilot_update({
            "pilot_id":      config.get("vatsim_cid", ""),
            "name":          config.get("pilot_name", ""),
            "phase":         phase_str,
            "lat":           tel.latitude,
            "lon":           tel.longitude,
            "alt":           tel.altitude_ft,
            "gs":            tel.groundspeed_kts,
            "origin":        self._ofp.origin_icao,
            "destination":   self._ofp.destination_icao,
            "flight_number": self._ofp.flight_number,
        })

    # ==================================================================
    # Serialisers (Python objects → JSON-ready dicts)
    # ==================================================================

    def _ofp_to_dict(self, ofp: OFP) -> dict:
        origin_c = _AIRPORT_COORDS.get(ofp.origin_icao)
        dest_c = _AIRPORT_COORDS.get(ofp.destination_icao)
        return {
            "airline": ofp.airline,
            "flight_number": ofp.flight_number,
            "callsign": ofp.callsign,
            "origin_icao": ofp.origin_icao,
            "origin_name": ofp.origin_name,
            "destination_icao": ofp.destination_icao,
            "destination_name": ofp.destination_name,
            "alternate_icao": ofp.alternate_icao,
            "route": ofp.route,
            "aircraft_icao": ofp.aircraft_icao,
            "aircraft_name": ofp.aircraft_name,
            "registration": ofp.registration,
            "cruise_altitude": ofp.cruise_altitude,
            "est_flight_time_min": ofp.est_flight_time_min,
            "distance_nm": ofp.distance_nm,
            "fuel_lbs": ofp.fuel.total_lbs,
            "atd_utc": ofp.atd_utc,
            "eta_utc": ofp.eta_utc,
            "zfw_lbs": ofp.zfw_lbs,
            "tow_lbs": ofp.tow_lbs,
            "origin_coords": list(origin_c) if origin_c else None,
            "dest_coords": list(dest_c) if dest_c else None,
        }

    def _telemetry_to_dict(self, tel: Telemetry, phase: FlightPhase,
                           elapsed: float, dist_to_dest: float) -> dict:
        return {
            "lat": tel.latitude, "lon": tel.longitude,
            "altitude_ft": round(tel.altitude_ft),
            "heading": round(getattr(tel, "heading_true", tel.heading_mag)),
            "ias_kts": round(tel.ias_kts), "tas_kts": round(tel.tas_kts),
            "gs_kts": round(tel.groundspeed_kts),
            "mach": round(tel.mach, 3),
            "vs_fpm": round(tel.vertical_speed_fpm),
            "fuel_lbs": round(tel.fuel_lbs),
            "on_ground": tel.on_ground,
            "gear_down": tel.gear_down,
            "flaps_pct": round(tel.flaps_pct),
            "parking_brake": tel.parking_brake,
            "transponder": tel.transponder,
            "phase": phase.value,
            "elapsed_sec": round(elapsed),
            "dist_to_dest_nm": (round(dist_to_dest, 1)
                                if dist_to_dest != float("inf") else None),
            "dist_flown_nm": round(self._flight_tracker.distance_flown_nm, 1)
                             if self._flight_tracker else 0,
            "wind_dir": round(tel.wind_dir_deg),
            "wind_kts": round(tel.wind_speed_kts),
            "oat_c": round(tel.oat_celsius),
        }

    @staticmethod
    def _bid_to_dict(bid: dict) -> dict:
        flight = bid.get("flight", {}) or {}
        return {
            "id": bid.get("id"),
            "flight_number": flight.get("flight_number", ""),
            "airline_icao": (flight.get("airline", {}) or {}).get("icao", ""),
            "dpt_airport": flight.get("dpt_airport_id", ""),
            "arr_airport": flight.get("arr_airport_id", ""),
            "aircraft": (bid.get("aircraft", {}) or {}).get("name", "")
                        or (flight.get("aircraft", {}) or {}).get("name", ""),
            "distance": flight.get("distance"),
            "flight_time": flight.get("flight_time"),
            "route": flight.get("route", ""),
        }

    def _bids_to_list(self, bids: list) -> list:
        return [self._bid_to_dict(b) for b in (bids or [])]

    @staticmethod
    def _pirep_to_dict(p: dict) -> dict:
        return {
            "id": p.get("id"),
            "flight_number": p.get("flight_number") or p.get("ident", ""),
            "dpt_airport": (p.get("dpt_airport", {}) or {}).get("icao")
                           or p.get("dpt_airport_id", ""),
            "arr_airport": (p.get("arr_airport", {}) or {}).get("icao")
                           or p.get("arr_airport_id", ""),
            "aircraft": (p.get("aircraft", {}) or {}).get("name", ""),
            "flight_time": p.get("flight_time"),
            "distance": p.get("distance"),
            "fuel_used": p.get("fuel_used"),
            "landing_rate": p.get("landing_rate"),
            "status": p.get("status", ""),
            "state": p.get("state"),
            "submitted_at": p.get("submitted_at") or p.get("created_at", ""),
        }

    @staticmethod
    def _user_to_dict(user: dict) -> dict:
        rank = user.get("rank", {}) or {}
        ft = user.get("flight_time", 0) or 0
        return {
            "name": user.get("name", ""),
            "pilot_id": user.get("pilot_id") or user.get("ident", ""),
            "rank": rank.get("name", "") if isinstance(rank, dict) else str(rank),
            "flights": user.get("flights", 0),
            "flight_time_min": ft,
            "flight_time_str": f"{ft // 60}h {ft % 60:02d}m",
            "airline": (user.get("airline", {}) or {}).get("name", ""),
            "avatar": user.get("avatar") or user.get("gravatar", ""),
            "current_airport": user.get("curr_airport_id") or user.get("current_airport_id", ""),
        }

    # ==================================================================
    # Tray + lifecycle
    # ==================================================================

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(app_icon(), self)
        self._tray.setToolTip("Africana Tracker")
        self._tray.activated.connect(self._on_tray_activated)
        menu = QMenu()
        menu.addAction("Open Tracker").triggered.connect(self._show_from_tray)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self._quit_app)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def closeEvent(self, event):
        # Closing the window quits the app — no hide-to-tray.
        self._quit_app()
        event.accept()

    def _quit_app(self):
        self._stop_tracking()
        if self._net_client:
            self._net_client.stop()
            self._net_client.wait(2000)
        if self._discord:
            self._discord.close()
        self._vms_sync.close()
        self._tray.hide()
        QApplication.instance().quit()
