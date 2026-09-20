from __future__ import annotations
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS action_log (
    entry_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    target TEXT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    input_json TEXT,
    diff_hash TEXT,
    created_at TEXT NOT NULL
);
"""


class ActionLogStore:
    """Audit trail only: which tool was called, against what, and whether it
    succeeded. Approval gating and any request/spec/plan workflow live in
    backend now, not here — see docs/architecture.md. input_json is already
    sanitized (secrets redacted, diffs hashed, bulk fields truncated) by
    _sanitize_action_input before it reaches this store."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # FastMCP dispatches sync tool handlers to worker threads, so this
        # connection must be usable cross-thread, guarded by one coarse
        # re-entrant lock.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add_action_log(
        self, *, tool: str, target: str | None,
        status: str, summary: str, input_json: str | None, diff_hash: str | None, now: str,
    ) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO action_log (tool, target, status, summary, input_json, diff_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tool, target, status, summary, input_json, diff_hash, now),
                )

    def list_recent_action_log(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tool, target, status, summary, input_json, diff_hash, created_at "
                "FROM action_log ORDER BY entry_seq DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")
