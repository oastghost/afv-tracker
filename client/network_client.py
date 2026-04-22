"""
AFV Tracker - Network Client
Maintains a persistent WebSocket connection to the AFV backend server.
Runs its own asyncio event loop inside a QThread so it never blocks the GUI.

All public "send" methods are thread-safe — called from the GUI thread,
they schedule coroutines on the network thread's loop via run_coroutine_threadsafe.
"""

import asyncio
import json
import logging
import re
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)

RECONNECT_DELAY = 5    # seconds between reconnection attempts
PING_INTERVAL   = 30   # seconds between keepalive pings


def _to_ws_url(server_url: str, pilot_id: str) -> str:
    """Convert http://host:port → ws://host:port/ws/{pilot_id}"""
    base = re.sub(r"^http", "ws", server_url.rstrip("/"))
    return f"{base}/ws/{pilot_id}"


class NetworkClient(QThread):
    """
    WebSocket client thread for the AFV multi-pilot ecosystem.

    Signals (emitted from network thread → received on GUI thread)
    -------
    connected            — WebSocket link established
    disconnected         — link dropped (will retry)
    roster_received(list)— initial pilot list sent by server on connect
    pilot_update(dict)   — another pilot's telemetry update
    pilot_offline(str)   — pilot_id of a pilot who disconnected
    gate_assigned(dict)  — {airport, gate_number, terminal, pilot_id, pilot_name}
    gate_released(dict)  — {airport, gate_number}
    """

    connected       = pyqtSignal()
    disconnected    = pyqtSignal()
    roster_received = pyqtSignal(list)
    pilot_update    = pyqtSignal(dict)
    pilot_offline   = pyqtSignal(str)
    gate_assigned   = pyqtSignal(dict)
    gate_released   = pyqtSignal(dict)

    def __init__(self, server_url: str, pilot_id: str, parent=None):
        super().__init__(parent)
        self._ws_url = _to_ws_url(server_url, pilot_id)
        self._pilot_id = pilot_id
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None   # websockets connection object

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._running = True
        try:
            self._loop.run_until_complete(self._connect_loop())
        finally:
            self._loop.close()
            self._loop = None

    def stop(self):
        self._running = False
        if self._ws and self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    # ------------------------------------------------------------------
    # Async connection loop
    # ------------------------------------------------------------------

    async def _connect_loop(self):
        import websockets

        while self._running:
            try:
                log.info("Connecting to AFV network: %s", self._ws_url)
                async with websockets.connect(
                    self._ws_url,
                    ping_interval=PING_INTERVAL,
                    ping_timeout=10,
                    open_timeout=8,
                ) as ws:
                    self._ws = ws
                    self.connected.emit()
                    log.info("Network: connected")
                    await self._recv_loop(ws)

            except Exception as exc:
                log.warning("Network: connection failed — %s", exc)
            finally:
                self._ws = None
                if self._running:
                    self.disconnected.emit()
                    log.info("Network: reconnecting in %ds…", RECONNECT_DELAY)
                    await asyncio.sleep(RECONNECT_DELAY)

    async def _recv_loop(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event = msg.get("event")
            data  = msg.get("data")

            if event == "roster":
                self.roster_received.emit(data or [])
            elif event == "pilot_update":
                self.pilot_update.emit(data or {})
            elif event == "pilot_offline":
                self.pilot_offline.emit((data or {}).get("pilot_id", ""))
            elif event == "gate_assigned":
                self.gate_assigned.emit(data or {})
            elif event == "gate_released":
                self.gate_released.emit(data or {})
            elif event == "pong":
                pass  # keepalive acknowledged

    # ------------------------------------------------------------------
    # Thread-safe send helpers (called from GUI thread)
    # ------------------------------------------------------------------

    def send_pilot_update(self, data: dict) -> None:
        """Broadcast this pilot's telemetry to all others."""
        self._schedule_send({"event": "pilot_update", "data": data})

    def send_ping(self) -> None:
        self._schedule_send({"event": "ping"})

    def _schedule_send(self, message: dict) -> None:
        if self._ws is None or self._loop is None or self._loop.is_closed():
            return
        raw = json.dumps(message)
        asyncio.run_coroutine_threadsafe(self._ws.send(raw), self._loop)
