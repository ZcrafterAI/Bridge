from __future__ import annotations
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    raw_request TEXT NOT NULL,
    phase TEXT NOT NULL CHECK(phase IN ('CLARIFYING','SPEC_DRAFT','SPEC_APPROVED','PLAN_DRAFT','PLAN_APPROVED','EXECUTING')),
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','ABANDONED','COMPLETED')),
    spec_approved_version INTEGER,
    spec_approved_at TEXT,
    plan_approved_version INTEGER,
    plan_approved_at TEXT,
    cancel_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clarifications (
    request_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spec_revisions (
    request_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (request_id, version)
);

CREATE TABLE IF NOT EXISTS plan_revisions (
    request_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (request_id, version)
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('spec','plan')),
    version INTEGER NOT NULL,
    token_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','EXPIRED')),
    via TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS plan_step_uses (
    use_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    plan_version INTEGER NOT NULL,
    step_index INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    entry_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    tool TEXT NOT NULL,
    target TEXT,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    input_json TEXT,
    diff_hash TEXT,
    created_at TEXT NOT NULL
);
"""

_REQUEST_COLUMNS = (
    "id", "raw_request", "phase", "status",
    "spec_approved_version", "spec_approved_at",
    "plan_approved_version", "plan_approved_at",
    "cancel_reason", "created_at", "updated_at",
)


class RequestStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Same reasoning as mainframe_mcp/db.py's GraphDB: FastMCP dispatches
        # sync tool handlers to worker threads, so this connection must be
        # usable cross-thread, guarded by one coarse re-entrant lock.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Bring a store made by an earlier version up to date."""
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(plan_revisions)")}
        if "steps_json" not in columns:
            self._conn.execute("ALTER TABLE plan_revisions ADD COLUMN steps_json TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_request(self, id: str, raw_request: str, *, now: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO requests (id, raw_request, phase, status, created_at, updated_at) "
                    "VALUES (?, ?, 'CLARIFYING', 'ACTIVE', ?, ?)",
                    (id, raw_request, now, now),
                )

    def get_request(self, id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {', '.join(_REQUEST_COLUMNS)} FROM requests WHERE id = ?", (id,)
            ).fetchone()
            return dict(row) if row else None

    def list_requests(self, status: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {', '.join(_REQUEST_COLUMNS)} FROM requests WHERE status = ? ORDER BY created_at",
                (status,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_phase_status(
        self,
        id: str,
        *,
        phase: str | None = None,
        status: str | None = None,
        cancel_reason: str | None = None,
        spec_approved_version: int | None = None,
        spec_approved_at: str | None = None,
        plan_approved_version: int | None = None,
        plan_approved_at: str | None = None,
        clear_spec_approval: bool = False,
        clear_plan_approval: bool = False,
        now: str,
    ) -> None:
        sets = ["updated_at = ?"]
        params: list = [now]
        if phase is not None:
            sets.append("phase = ?")
            params.append(phase)
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if cancel_reason is not None:
            sets.append("cancel_reason = ?")
            params.append(cancel_reason)
        if spec_approved_version is not None:
            sets.append("spec_approved_version = ?")
            params.append(spec_approved_version)
        if spec_approved_at is not None:
            sets.append("spec_approved_at = ?")
            params.append(spec_approved_at)
        if clear_spec_approval:
            sets.append("spec_approved_version = NULL")
            sets.append("spec_approved_at = NULL")
        if plan_approved_version is not None:
            sets.append("plan_approved_version = ?")
            params.append(plan_approved_version)
        if plan_approved_at is not None:
            sets.append("plan_approved_at = ?")
            params.append(plan_approved_at)
        if clear_plan_approval:
            sets.append("plan_approved_version = NULL")
            sets.append("plan_approved_at = NULL")
        params.append(id)
        with self._lock:
            with self._conn:
                self._conn.execute(f"UPDATE requests SET {', '.join(sets)} WHERE id = ?", params)

    def add_clarification(self, request_id: str, question: str, answer: str, *, now: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO clarifications (request_id, question, answer, created_at) VALUES (?, ?, ?, ?)",
                    (request_id, question, answer, now),
                )

    def list_clarifications(self, request_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT question, answer, created_at FROM clarifications WHERE request_id = ? ORDER BY request_seq",
                (request_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_spec_revision(self, request_id: str, version: int, content: str, *, now: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO spec_revisions (request_id, version, content, created_at) VALUES (?, ?, ?, ?)",
                    (request_id, version, content, now),
                )

    def latest_spec_revision(self, request_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT version, content, created_at FROM spec_revisions WHERE request_id = ? ORDER BY version DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            return dict(row) if row else None

    def add_plan_revision(
        self, request_id: str, version: int, content: str, *, now: str, steps_json: str | None = None,
    ) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO plan_revisions (request_id, version, content, steps_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (request_id, version, content, steps_json, now),
                )

    def get_plan_revision(self, request_id: str, version: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT version, content, steps_json, created_at FROM plan_revisions "
                "WHERE request_id = ? AND version = ?",
                (request_id, version),
            ).fetchone()
            return dict(row) if row else None

    def add_step_use(self, request_id: str, plan_version: int, step_index: int, *, now: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO plan_step_uses (request_id, plan_version, step_index, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (request_id, plan_version, step_index, now),
                )

    def step_uses(self, request_id: str, plan_version: int) -> dict[int, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT step_index, COUNT(*) AS n FROM plan_step_uses "
                "WHERE request_id = ? AND plan_version = ? GROUP BY step_index",
                (request_id, plan_version),
            ).fetchall()
            return {int(row["step_index"]): int(row["n"]) for row in rows}

    # ---- approvals: a decision only a person can make ----

    def create_approval(
        self, id: str, request_id: str, kind: str, version: int, token_hash: str, *, now: str,
    ) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO approvals (id, request_id, kind, version, token_hash, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'PENDING', ?)",
                    (id, request_id, kind, version, token_hash, now),
                )

    def get_approval(self, id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM approvals WHERE id = ?", (id,)).fetchone()
            return dict(row) if row else None

    def find_approval(self, request_id: str, kind: str, version: int) -> dict | None:
        """The newest approval asked for this exact spec or plan version."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE request_id = ? AND kind = ? AND version = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (request_id, kind, version),
            ).fetchone()
            return dict(row) if row else None

    def list_pending_approvals(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM approvals WHERE status = 'PENDING' ORDER BY created_at"
            ).fetchall()
            return [dict(row) for row in rows]

    def decide_approval(self, id: str, status: str, via: str, *, now: str) -> bool:
        """Record a decision. False when the approval was already decided."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE approvals SET status = ?, via = ?, decided_at = ? "
                    "WHERE id = ? AND status = 'PENDING'",
                    (status, via, now, id),
                )
                return cursor.rowcount == 1

    def latest_plan_revision(self, request_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT version, content, steps_json, created_at FROM plan_revisions WHERE request_id = ? ORDER BY version DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            return dict(row) if row else None

    def add_action_log(
        self, *, request_id: str | None, tool: str, target: str | None,
        status: str, summary: str, input_json: str | None, diff_hash: str | None, now: str,
    ) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO action_log (request_id, tool, target, status, summary, input_json, diff_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (request_id, tool, target, status, summary, input_json, diff_hash, now),
                )

    def list_action_log(self, request_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tool, target, status, summary, input_json, diff_hash, created_at "
                "FROM action_log WHERE request_id = ? ORDER BY entry_seq",
                (request_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_request_cascade(self, request_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM action_log WHERE request_id = ?", (request_id,))
                self._conn.execute("DELETE FROM approvals WHERE request_id = ?", (request_id,))
                self._conn.execute("DELETE FROM plan_step_uses WHERE request_id = ?", (request_id,))
                self._conn.execute("DELETE FROM plan_revisions WHERE request_id = ?", (request_id,))
                self._conn.execute("DELETE FROM spec_revisions WHERE request_id = ?", (request_id,))
                self._conn.execute("DELETE FROM clarifications WHERE request_id = ?", (request_id,))
                self._conn.execute("DELETE FROM requests WHERE id = ?", (request_id,))

    def vacuum(self) -> None:
        with self._lock:
            self._conn.execute("VACUUM")
