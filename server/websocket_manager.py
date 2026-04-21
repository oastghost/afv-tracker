"""
AFV Tracker - WebSocket Connection Manager
Tracks all active pilot WebSocket connections and the live in-memory roster.
Provides thread-safe broadcast helpers so synchronous HTTP route handlers
can push events to all connected clients.
"""

import asyncio
import logging
from typing import Optional
from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # pilot_id → live WebSocket
        self._connections: dict[str, WebSocket] = {}
        # pilot_id → last pilot_update payload (in-memory roster)
        self._roster: dict[str, dict] = {}
        # Set at server startup so sync routes can schedule coroutines
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, pilot_id: str, ws: WebSocket) -> None:
        # If this pilot is already connected (reconnect / duplicate tab), close old socket
        if pilot_id in self._connections:
            try:
                await self._connections[pilot_id].close()
            except Exception:
                pass

        await ws.accept()
        self._connections[pilot_id] = ws
        log.info("Pilot connected: %s  (total: %d)", pilot_id, len(self._connections))

        # Send the current roster snapshot to the newly connected client
        await ws.send_json({
            "event": "roster",
            "data": list(self._roster.values()),
        })

    async def disconnect(self, pilot_id: str) -> None:
        self._connections.pop(pilot_id, None)
        self._roster.pop(pilot_id, None)
        log.info("Pilot disconnected: %s  (total: %d)", pilot_id, len(self._connections))

    # ------------------------------------------------------------------
    # Broadcast helpers
    # ------------------------------------------------------------------

    async def broadcast(self, message: dict, exclude: Optional[str] = None) -> None:
        """Send a message to every connected pilot except `exclude`."""
        dead: list[str] = []
        for pid, ws in list(self._connections.items()):
            if pid == exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(pid)

        for pid in dead:
            await self.disconnect(pid)

    async def send_to(self, pilot_id: str, message: dict) -> None:
        """Send a message to one specific pilot."""
        ws = self._connections.get(pilot_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                await self.disconnect(pilot_id)

    # ------------------------------------------------------------------
    # Roster management
    # ------------------------------------------------------------------

    def update_roster(self, pilot_id: str, data: dict) -> None:
        """Called synchronously; just updates the in-memory snapshot."""
        self._roster[pilot_id] = data

    def get_online_pilots(self) -> list[dict]:
        return list(self._roster.values())

    def get_connection_count(self) -> int:
        return len(self._connections)


# ── Module-level singleton ─────────────────────────────────────────────────────

manager = ConnectionManager()


def broadcast_sync(message: dict, exclude: Optional[str] = None) -> None:
    """
    Thread-safe broadcast called from synchronous HTTP route handlers.
    Schedules the async broadcast on the server's running event loop.
    """
    if manager.loop and not manager.loop.is_closed():
        asyncio.run_coroutine_threadsafe(
            manager.broadcast(message, exclude=exclude),
            manager.loop,
        )
