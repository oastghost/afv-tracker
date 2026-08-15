"""
AFV Tracker - Sound Cues
Short audible cues for key flight events (takeoff, landing, gate assignment,
errors). Built on winsound (stdlib, Windows-only — this app already assumes
Windows via winreg/pystray elsewhere) so no audio asset files are needed.
Every cue runs in a daemon thread since winsound.Beep blocks for its duration.
"""

import logging
import threading

import config

log = logging.getLogger(__name__)

# Each cue is a list of (frequency_hz, duration_ms) notes played in sequence.
_CUES = {
    "flight_start":  [(523, 90), (659, 90), (784, 140)],   # ascending: C5 E5 G5
    "landing":       [(784, 90), (659, 90), (523, 140)],   # descending: G5 E5 C5
    "gate_assigned": [(659, 100), (880, 160)],
    "error":         [(220, 220)],
}


def _enabled() -> bool:
    return bool(config.get("sound_enabled", True))


def _beep_sequence(notes):
    try:
        import winsound
        for freq, dur in notes:
            winsound.Beep(freq, dur)
    except Exception as exc:
        log.debug("Sound cue failed: %s", exc)


def play(cue: str) -> None:
    """Play a named cue asynchronously. No-ops quietly if disabled or unknown."""
    if not _enabled():
        return
    notes = _CUES.get(cue)
    if not notes:
        log.debug("Unknown sound cue: %s", cue)
        return
    threading.Thread(target=_beep_sequence, args=(notes,), daemon=True).start()
