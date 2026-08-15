"""
AFV Tracker - Discord Rich Presence
Shows the pilot's current flight on their Discord profile over the local
Discord IPC pipe (pypresence). Everything runs on a background QThread via
a job queue so a missing or slow Discord client never touches the GUI thread.
"""

import logging
import queue

from PyQt6.QtCore import QThread

log = logging.getLogger(__name__)


class DiscordPresenceWorker(QThread):
    """
    Owns a pypresence.Presence connection on its own thread.
    update_activity() / clear_activity() / close() are safe to call from the
    GUI thread — they just push a job onto an internal queue. Connecting (and
    reconnecting after a drop) happens lazily on the worker thread.
    """

    # Asset key must match an uploaded image under the Discord application's
    # Rich Presence > Art Assets tab (developer portal), not a local file path.
    LARGE_IMAGE_KEY = "logo"
    LARGE_IMAGE_TEXT = "Africana Virtual Airways"

    def __init__(self, client_id: str, parent=None):
        super().__init__(parent)
        self._client_id = client_id
        self._jobs: queue.Queue = queue.Queue()
        self._running = False
        self._rpc = None
        self._connected = False

    # ------------------------------------------------------------------
    # Public API — thread-safe, just enqueues
    # ------------------------------------------------------------------

    def update_activity(self, details: str, state: str, start_ts: float = None):
        self._jobs.put(("update", details, state, start_ts))

    def clear_activity(self):
        self._jobs.put(("clear", None, None, None))

    def close(self):
        self._jobs.put(("stop", None, None, None))
        self.wait(2000)

    # ------------------------------------------------------------------
    # Worker thread body
    # ------------------------------------------------------------------

    def run(self):
        if not self._client_id:
            return   # RPC disabled / not configured — thread exits immediately

        self._running = True
        while self._running:
            try:
                job, details, state, start_ts = self._jobs.get(timeout=1.0)
            except queue.Empty:
                continue

            if job == "stop":
                break
            if not self._ensure_connected():
                continue   # Discord unreachable — drop this update, retry on the next one

            try:
                if job == "update":
                    payload = {
                        "details": details, "state": state,
                        "large_image": self.LARGE_IMAGE_KEY,
                        "large_text": self.LARGE_IMAGE_TEXT,
                    }
                    if start_ts:
                        payload["start"] = int(start_ts)
                    self._rpc.update(**payload)
                elif job == "clear":
                    self._rpc.clear()
            except Exception as exc:
                log.debug("Discord RPC update failed: %s", exc)
                self._connected = False   # force a reconnect attempt next time

        if self._rpc is not None:
            try:
                self._rpc.close()
            except Exception:
                pass

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True
        try:
            from pypresence import Presence
            self._rpc = Presence(self._client_id)
            self._rpc.connect()
            self._connected = True
            log.info("Discord Rich Presence connected.")
            return True
        except Exception as exc:
            log.debug("Discord RPC not available: %s", exc)
            self._rpc = None
            return False
