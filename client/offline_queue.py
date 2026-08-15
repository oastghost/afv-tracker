"""
AFV Tracker - Offline Request Queue
Persists outbound HTTP requests that failed to send (e.g. phpVMS ACARS
positions or PIREP updates while the VA server or the pilot's internet
connection is briefly down) so they can be retried instead of silently
dropping flight data.

Storage-only — callers own the actual HTTP replay (see
PhpVmsClient.retry_pending in phpvms_integration.py).
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

log = logging.getLogger(__name__)

DB_PATH = Path(os.path.expanduser("~")) / ".afv_tracker" / "outbox.db"
MAX_ATTEMPTS = 20   # drop a row after this many failed retries — avoids unbounded growth


class OfflineQueue:
    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind        TEXT NOT NULL,
                    method      TEXT NOT NULL,
                    url         TEXT NOT NULL,
                    headers     TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    created_at  REAL NOT NULL,
                    attempts    INTEGER NOT NULL DEFAULT 0,
                    last_error  TEXT
                )
            """)

    def enqueue(self, kind: str, method: str, url: str, headers: dict, payload: dict) -> None:
        """Persist a failed request so retry_pending() can resend it later."""
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO outbox (kind, method, url, headers, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (kind, method, url, json.dumps(headers), json.dumps(payload), time.time()),
                )
            log.info("Queued %s %s for retry (send failed).", kind, method)
        except Exception:
            log.exception("Failed to persist offline queue entry — data lost: %s %s", kind, url)

    def enqueue_latest_only(self, kind: str, method: str, url: str, headers: dict, payload: dict) -> None:
        """
        Like enqueue(), but first drops any other pending rows of the same
        kind. Use this for state where only the newest value matters (e.g.
        PIREP status) — replaying a stale queued update after a fresher one
        already succeeded live would incorrectly revert the displayed stage.
        """
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM outbox WHERE kind = ?", (kind,))
                conn.execute(
                    "INSERT INTO outbox (kind, method, url, headers, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (kind, method, url, json.dumps(headers), json.dumps(payload), time.time()),
                )
            log.info("Queued %s for retry (replacing any earlier pending entry).", kind)
        except Exception:
            log.exception("Failed to persist offline queue entry — data lost: %s %s", kind, url)

    def clear_kind(self, kind: str) -> None:
        """Drop all pending rows of this kind — e.g. once a fresher live update has landed."""
        with self._connect() as conn:
            conn.execute("DELETE FROM outbox WHERE kind = ?", (kind,))

    def list_pending(self) -> list:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM outbox ORDER BY created_at ASC").fetchall()

    def remove(self, row_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM outbox WHERE id = ?", (row_id,))

    def mark_attempt(self, row_id: int, error: str) -> None:
        """Record a failed retry; drops the row once MAX_ATTEMPTS is reached."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM outbox WHERE id = ?", (row_id,)
            ).fetchone()
            if row is None:
                return
            attempts = row["attempts"] + 1
            if attempts >= MAX_ATTEMPTS:
                conn.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
                log.warning("Dropping queued request %d after %d failed attempts.", row_id, attempts)
            else:
                conn.execute(
                    "UPDATE outbox SET attempts = ?, last_error = ? WHERE id = ?",
                    (attempts, error, row_id),
                )

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
