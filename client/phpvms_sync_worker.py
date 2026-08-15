"""
AFV Tracker - phpVMS Sync Worker
Serializes every phpVMS write (ACARS position, PIREP status, PIREP filing,
offline-queue retries) through a single background thread, run strictly in
the order they were submitted.

Without this, each event (phase change, ACARS tick, offline retry) spawned
its own ad-hoc thread. Under load — e.g. rapid CLIMB/DESCENT phase flips —
several requests could be in flight to the same PIREP at once with no
ordering guarantee: a slower request carrying an *older* phase could
complete *after* a faster one carrying the current phase, silently
overwriting the correct stage on phpVMS with a stale one. Routing every
write through one FIFO queue + one worker thread makes that impossible —
jobs run one at a time, in submission order, so the last one sent always
reflects the last one that actually happened.
"""

import logging
import queue

from PyQt6.QtCore import QThread

log = logging.getLogger(__name__)


class PhpVmsSyncWorker(QThread):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: queue.Queue = queue.Queue()
        self._running = False

    def submit(self, fn, *args, **kwargs) -> None:
        """Queue a callable for serialized execution on the worker thread."""
        self._jobs.put((fn, args, kwargs))

    def close(self) -> None:
        self._jobs.put(None)   # sentinel — unblocks the run() loop
        self.wait(3000)

    def run(self) -> None:
        self._running = True
        while self._running:
            job = self._jobs.get()
            if job is None:
                break
            fn, args, kwargs = job
            try:
                fn(*args, **kwargs)
            except Exception:
                log.exception("phpVMS sync job failed")
