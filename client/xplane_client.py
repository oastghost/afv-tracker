"""
AFV Tracker - X-Plane Client
Polls X-Plane 11/12 over its native UDP protocol (BECN beacon discovery +
RREF dataref subscription) and emits telemetry data.
Runs in a background QThread so it never blocks the GUI. Mirrors the public
signal contract of SimConnectWorker (simconnect_client.py) so gui_web.py can
use either backend interchangeably — see sim_factory.py.

Independent from simconnect_client.py on purpose: this module must never be
the reason the existing MSFS/SimConnect path breaks, so it shares no code
with it beyond the sim-agnostic Telemetry dataclass.

Protocol notes: dataref paths come from X-Plane's own Resources/plugins/
DataRefs.txt (shipped with every install); the BECN/RREF UDP packet layouts
follow the widely-published reference format for those messages. This was
written without a live X-Plane instance available to test against — if
telemetry doesn't come through, capture UDP traffic (e.g. Wireshark) against
a real session and check offsets/dataref names first.

XP12 note: its new weather engine kept the classic sim/weather/* datarefs
below as legacy/global passthroughs, so wind/OAT/QNH should still populate,
but may be less precise than on XP11. Position/attitude/speed/engine/gear
datarefs are unaffected and stable across both versions.
"""

import socket
import struct
import time
import logging
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from simconnect_client import Telemetry

log = logging.getLogger(__name__)

BEACON_MCAST_GRP = "239.255.1.1"
BEACON_PORT = 49707
DEFAULT_RREF_PORT = 49000
_NO_DATA_TIMEOUT = 15  # seconds without a packet before we treat the link as dead

_MPS_TO_KTS = 1.9438445
_M_TO_FT = 3.2808399
_KG_TO_LBS = 2.2046226
_INHG_TO_MB = 33.8638866


def _identity(v: float):
    return v


def _bool(v: float) -> bool:
    return v > 0.5


def _pct(v: float) -> float:
    return v * 100.0


# (dataref, Telemetry attribute, raw-float -> value transform)
_DATAREFS = [
    ("sim/flightmodel/position/latitude",           "latitude",           _identity),
    ("sim/flightmodel/position/longitude",          "longitude",          _identity),
    ("sim/flightmodel/position/elevation",          "altitude_ft",        lambda v: v * _M_TO_FT),
    ("sim/flightmodel/position/magpsi",             "heading_mag",        _identity),
    ("sim/flightmodel/position/psi",                "heading_true",       _identity),
    ("sim/flightmodel/position/theta",              "pitch_deg",          _identity),
    ("sim/flightmodel/position/phi",                "bank_deg",           _identity),
    ("sim/flightmodel/position/groundspeed",        "groundspeed_kts",    lambda v: v * _MPS_TO_KTS),
    ("sim/flightmodel/position/indicated_airspeed", "ias_kts",            _identity),
    ("sim/flightmodel/position/true_airspeed",      "tas_kts",            lambda v: v * _MPS_TO_KTS),
    ("sim/flightmodel/misc/machno",                 "mach",               _identity),
    ("sim/flightmodel/position/vh_ind_fpm",         "vertical_speed_fpm", _identity),
    ("sim/flightmodel/weight/m_fuel_total",         "fuel_lbs",           lambda v: v * _KG_TO_LBS),
    ("sim/flightmodel/failures/onground_any",       "on_ground",          _bool),
    ("sim/flightmodel/controls/parkbrake",          "parking_brake",      _bool),
    ("sim/cockpit2/controls/gear_handle_down",      "gear_down",          _bool),
    ("sim/cockpit2/controls/flap_ratio",            "flaps_pct",          _pct),
    ("sim/cockpit/radios/transponder_code",         "transponder",        lambda v: int(round(v))),
    ("sim/cockpit2/switches/strobe_lights_on",      "lights_strobe",      _bool),
    ("sim/cockpit2/switches/landing_lights_on",     "lights_landing",     _bool),
    ("sim/weather/wind_speed_kt",                   "wind_speed_kts",     _identity),
    ("sim/weather/wind_direction_degt",              "wind_dir_deg",       _identity),
    ("sim/weather/temperature_ambient_c",           "oat_celsius",        _identity),
    ("sim/weather/barometer_sealevel_inhg",         "qnh_mb",             lambda v: v * _INHG_TO_MB),
]

# Per-engine arrays (indices 0-3 -> engine 1-4). Requested as individual
# array-element datarefs since RREF subscribes to one value per index.
_ENGINE_RUN_DATAREF = "sim/flightmodel/engine/ENGN_running"
_ENGINE_N1_DATAREF = "sim/flightmodel/engine/ENGN_N1_"
_ENGINE_RUN_ATTRS = ["engine_on", "eng2_on", "eng3_on", "eng4_on"]
_ENGINE_N1_ATTRS = ["eng1_n1", "eng2_n1", "eng3_n1", "eng4_n1"]


def detect_sim_version(xplane_version: int) -> str:
    """Map the BECN beacon's integer version field to a display label."""
    if xplane_version >= 120000:
        return "X-Plane 12"
    if xplane_version >= 110000:
        return "X-Plane 11"
    return "X-Plane"


class XPlaneWorker(QThread):
    """
    Background thread that connects to X-Plane 11/12 over UDP and polls
    telemetry. Exposes the same signals as SimConnectWorker so gui_web.py
    can use either worker without caring which one it got — see
    sim_factory.build_sim_worker().

    Signals
    -------
    telemetry_update(Telemetry)  — emitted every poll cycle
    connected(str)               — emitted once the RREF link is established; carries sim version string
    disconnected()               — emitted when the link drops
    error(str)                   — emitted on unrecoverable error
    """

    telemetry_update = pyqtSignal(object)
    connected = pyqtSignal(str)
    disconnected = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, poll_interval: int = 5, parent=None, *,
                 host: str = "", port: int = DEFAULT_RREF_PORT):
        super().__init__(parent)
        self.poll_interval = max(1, poll_interval)
        self._configured_host = (host or "").strip()
        self._configured_port = port or DEFAULT_RREF_PORT
        self._running = False
        self._connected = False
        self._values: dict = {}
        self._index_map: dict = {}

    def stop(self):
        self._running = False
        self.wait(3000)

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self):
        self._running = True

        while self._running:
            sock: Optional[socket.socket] = None
            try:
                host, port, version_label = self._discover()
                if not host:
                    time.sleep(5)
                    continue

                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(2.0)
                self._values = {}
                self._subscribe_all(sock, (host, port))

                self._connected = True
                self.connected.emit(version_label)
                log.info("X-Plane UDP session established — %s (%s:%d)", version_label, host, port)

                prev_on_ground = True
                last_emit = 0.0
                last_packet = time.monotonic()

                while self._running:
                    try:
                        data, _addr = sock.recvfrom(4096)
                        last_packet = time.monotonic()
                        self._ingest_rref_packet(data)
                    except socket.timeout:
                        if time.monotonic() - last_packet > _NO_DATA_TIMEOUT:
                            log.info("X-Plane UDP: no data for %ds, reconnecting.", _NO_DATA_TIMEOUT)
                            break

                    now = time.monotonic()
                    if self._values and now - last_emit >= self.poll_interval:
                        tel = self._build_telemetry(prev_on_ground)
                        self.telemetry_update.emit(tel)
                        prev_on_ground = tel.on_ground
                        last_emit = now

            except OSError as e:
                log.debug("X-Plane UDP setup error: %s", e)
            except Exception as exc:
                log.debug("X-Plane worker error: %s", exc)
            finally:
                if self._connected:
                    self._connected = False
                    self.disconnected.emit()
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass

            if self._running:
                time.sleep(10)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(self):
        """Returns (host, port, version_label) or (None, None, None)."""
        if self._configured_host:
            return self._configured_host, self._configured_port, "X-Plane"
        beacon = self._listen_for_beacon(timeout=5.0)
        if not beacon:
            return None, None, None
        return beacon

    @staticmethod
    def _listen_for_beacon(timeout: float = 5.0):
        bsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass  # SO_REUSEPORT doesn't exist on Windows
        try:
            bsock.bind(("", BEACON_PORT))
            mreq = struct.pack("4sl", socket.inet_aton(BEACON_MCAST_GRP), socket.INADDR_ANY)
            bsock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            bsock.settimeout(timeout)
            data, addr = bsock.recvfrom(2048)
            if data[:5] != b"BECN\x00":
                return None
            _major, _minor, _host_id, xp_version, _role = struct.unpack_from("<BBiii", data, 5)
            port = struct.unpack_from("<H", data, 19)[0]
            return addr[0], port, detect_sim_version(xp_version)
        except (socket.timeout, OSError, struct.error) as e:
            log.debug("X-Plane beacon not found: %s", e)
            return None
        finally:
            bsock.close()

    # ------------------------------------------------------------------
    # RREF subscription / parsing
    # ------------------------------------------------------------------

    def _subscribe_all(self, sock: socket.socket, addr: tuple):
        freq = 1  # Hz from X-Plane; we buffer locally and emit at poll_interval
        idx = 0
        self._index_map = {}
        for dataref, attr, transform in _DATAREFS:
            self._send_rref_request(sock, addr, dataref, idx, freq)
            self._index_map[idx] = (attr, transform)
            idx += 1
        for i, attr in enumerate(_ENGINE_RUN_ATTRS):
            self._send_rref_request(sock, addr, f"{_ENGINE_RUN_DATAREF}[{i}]", idx, freq)
            self._index_map[idx] = (attr, _bool)
            idx += 1
        for i, attr in enumerate(_ENGINE_N1_ATTRS):
            self._send_rref_request(sock, addr, f"{_ENGINE_N1_DATAREF}[{i}]", idx, freq)
            self._index_map[idx] = (attr, _identity)
            idx += 1

    @staticmethod
    def _send_rref_request(sock: socket.socket, addr: tuple, dataref: str, index: int, freq: int):
        msg = struct.pack("<5sii400s", b"RREF\x00", freq, index, dataref.encode("utf-8"))
        sock.sendto(msg, addr)

    def _ingest_rref_packet(self, data: bytes):
        if data[:5] != b"RREF,":
            return
        body = data[5:]
        count = len(body) // 8
        for i in range(count):
            try:
                idx, val = struct.unpack_from("<if", body, i * 8)
            except struct.error:
                break
            if idx in self._index_map:
                self._values[idx] = val

    def _build_telemetry(self, prev_on_ground: bool) -> Telemetry:
        kwargs = {}
        for idx, (attr, transform) in self._index_map.items():
            raw = self._values.get(idx)
            if raw is None:
                continue
            try:
                kwargs[attr] = transform(raw)
            except Exception:
                continue

        tel = Telemetry(timestamp=time.time(), **kwargs)

        if prev_on_ground is False and tel.on_ground is True:
            tel.touchdown_fpm = abs(tel.vertical_speed_fpm)
            log.info("Touchdown! Rate: %.0f fpm", tel.touchdown_fpm)

        return tel
