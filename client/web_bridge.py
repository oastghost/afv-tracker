"""
AFV Tracker - Web Bridge
Thin QWebChannel object that connects the Python backend to the web UI.

Protocol (deliberately generic so new UI features need no new slots/signals):

    Python  →  JS :  bridge.event(type: str, payloadJson: str)
    JS      →  Python:  bridge.send(action: str, payloadJson: str)

The MainWindow connects to `command_received` and dispatches on `action`;
it pushes UI updates by calling `emit_event(type, dict)`.
"""

import json
import logging

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)


class Bridge(QObject):
    # Python → JS. A single generic channel keyed by `type`.
    event = pyqtSignal(str, str)

    # Emitted on the Qt main thread whenever the UI calls bridge.send(...).
    command_received = pyqtSignal(str, str)   # (action, payloadJson)

    def emit_event(self, event_type: str, payload=None) -> None:
        """Push an event to the web UI. `payload` is any JSON-serialisable value."""
        try:
            data = json.dumps(payload if payload is not None else {}, default=str)
        except (TypeError, ValueError):
            log.exception("Bridge: failed to serialise %s payload", event_type)
            data = "{}"
        self.event.emit(event_type, data)

    @pyqtSlot(str, str)
    def send(self, action: str, payload_json: str) -> None:
        """Called from JavaScript. Re-emits on the Qt side for the window to handle."""
        self.command_received.emit(action, payload_json or "{}")
