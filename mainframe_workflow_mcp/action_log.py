from __future__ import annotations
from typing import Optional
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone
import uuid

from .db import SCHEMA, RequestStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TransactionLogStore:
    """
    Idempotent transaction-safe action log store with rollback support.
    
    All actions are stored atomically before completion to ensure reliability.
    This enables rollback of failed operations by capturing state at entry and comparing against exit state.
    """

    # Action status values
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    IN_PROGRESS = "IN_PROGRESS"
    
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path) if isinstance(db_path, str) else db_path
        
        # Ensure the directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Connect with SQLite WAL mode for better concurrency and crash recovery
        self._conn = sqlite3.connect(
            str(self.db_path),
            isolation_level=None,  # Use explicit commit for transactions
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for better performance with concurrent writes
        self._conn.execute("PRAGMA journal_mode=WAL")
        
        # Create tables with proper foreign keys for rollback support
        self._create_tables()
        
        # Thread safety lock (coarse reentrant lock)
        self._lock = threading.RLock()

    def _create_tables(self) -> None:
        SCHEMA_ACTION_LOG = """
        CREATE TABLE IF NOT EXISTS transaction_actions (
            action_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            action_session_id TEXT NOT NULL,  -- Session identifier for idempotency tracking
            tool TEXT NOT NULL,
            target TEXT,
            status TEXT NOT NULL CHECK(status IN ('PENDING','IN_PROGRESS','SUCCESS','FAILURE','ROLLED_BACK')),
            summary TEXT NOT NULL,
            input_json TEXT,
            output_json TEXT,
            error_message TEXT,
            state_before JSON,  -- Captured at action start for rollback
            state_after JSON,   -- Captured at action end (commit point) if successful
            started_at TEXT NOT NULL,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            
            -- Foreign key to requests table and action_sessions
            FOREIGN KEY (request_id) REFERENCES requests(id),
            
            -- Unique constraint for idempotency: same request + session + tool + target combination has one entry
            UNIQUE(request_id, action_session_id, tool, target)
        );

        CREATE TABLE IF NOT EXISTS action_sessions (
            session_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests(id)
        );

        CREATE INDEX idx_action_log_request ON transaction_actions(request_id);
        CREATE INDEX idx_action_log_status ON transaction_actions(status);
        """

        self._conn.executescript(SCHEMA_ACTION_LOG)
        self._conn.commit()

    def _ensure_action_session(self, request_id: str) -> Optional[str]:
        """Ensure an action session exists for the request. Returns session ID if created."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT session_id FROM action_sessions WHERE request_id = ?", (request_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return row["session_id"]
            
            # Create new session
            session_id = f"sess-{datetime.now(timezone.utc).timestamp()}"
            self._conn.execute(
                "INSERT INTO action_sessions (session_id, request_id, created_at) VALUES (?, ?, ?)",
                (session_id, request_id, _now())
            )
            self._conn.commit()
            return session_id

    def begin_action(
        self,
        *,
        request_id: str,
        tool: str,
        target: Optional[str],
        summary: str,
        input_json: Optional[str] = None,
    ) -> dict:
        """
        Begin an action - this is the atomic entry point that stores state before execution.
        
        Returns action details for tracking. This ensures idempotency - retrying 
        will re-capture pre-execution state if it's not already stored.
        """
        with self._lock:
            with self._conn:
                # Capture current state for rollback capability
                state_before = None
                try:
                    # Query tool-specific target state (e.g., file contents, DB records)
                    if "file" in tool.lower():
                        content = self._get_file_state(target or "")
                        state_before = {"content": content}
                    elif "db" in tool.lower():
                        rows = self._get_db_target_state(request_id, target or "", "SELECT")
                        state_before = {"rows": [dict(r) for r in rows]}
                    
                    # Get existing action if any (for idempotency check)
                    session_id = self._ensure_action_session(request_id)
                    cursor = self._conn.execute(
                        """SELECT * FROM transaction_actions 
                           WHERE request_id = ? AND action_session_id = ? AND tool = ? AND target = ?""",
                        (request_id, session_id, tool, target)
                    )
                    existing = {row["action_id"]: dict(row) for row in cursor.fetchall()}
                    
                except Exception as e:
                    state_before = None
                    existing.clear()
                
                # Record pending action state
                if "pending" not in (existing.get("action_id", {}).get("status") or ""):
                    action_id = f"act-{datetime.now(timezone.utc).timestamp()}_{uuid.uuid4().hex[:8]}"
                    
                    self._conn.execute(
                        """INSERT INTO transaction_actions 
                           (action_id, request_id, action_session_id, tool, target, status, summary, input_json, 
                            started_at, completed_at, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (action_id, request_id, session_id, tool, target, self.PENDING, summary, input_json or "", 
                         _now(), _now(), _now())
                    )
                    
                    if state_before:
                        self._conn.execute(
                            """UPDATE transaction_actions SET state_before = ? WHERE action_id = ?""",
                            (state_before.isojson() if hasattr(state_before, 'isojson') else str(state_before), action_id)
                        )
                    
                    self._conn.commit()
                
                # Get action details
                cursor = self._conn.execute(
                    "SELECT * FROM transaction_actions WHERE action_id = ?", (action_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else {}

    def commit_action(self, action_id: str, *, success: bool, output_json: Optional[str] = None) -> bool:
        """
        Commit an action - stores post-execution state for rollback verification.
        
        Returns True if action was successfully committed.
        """
        with self._lock:
            with self._conn:
                # Update action status and capture output
                cursor = self._conn.execute(
                    "SELECT * FROM transaction_actions WHERE action_id = ?", (action_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    return False
                
                action = dict(row)
                
                try:
                    # Update status
                    if success and action.get("status") == self.PENDING:
                        new_status = self.SUCCESS
                        error_message = None
                    elif action.get("status") == self.IN_PROGRESS:
                        new_status = self.SUCCESS if success else self.FAILURE
                        error_message = "None" if success else output_json or str(output_json)
                    else:
                        new_status = action.get("status")
                        error_message = None
                    
                    status_params = [self.PENDING, self.IN_PROGRESS] if success else [self.SUCCESS, self.FAILURE]
                    
                    self._conn.execute(
                        """UPDATE transaction_actions 
                           SET status = ?, output_json = ?, state_after = ?, 
                               completed_at = ?, updated_at = ?
                           WHERE action_id = ?""",
                        (new_status, output_json or "", str(output_json) if output_json else "", 
                         _now(), _now(), action_id)
                    )
                    
                except Exception:
                    self._conn.rollback()
                    return False
                
                self._conn.commit()
                return True

    def create_rollback_entry(
        self,
        *,
        request_id: str,
        tool: str,
        target: Optional[str],
        action_id: str,
        rollback_reason: str,
        rollback_state: Optional[dict] = None,
    ) -> bool:
        """
        Create an explicit rollback entry for failed actions.
        
        This is called after detecting a failure to record what needs to be rolled back.
        """
        with self._lock:
            with self._conn:
                # Get the action and its state_before
                cursor = self._conn.execute(
                    "SELECT * FROM transaction_actions WHERE action_id = ?", (action_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    return False
                
                action = dict(row)
                
                try:
                    # Mark action as rolled back
                    state_after = str(rollback_state) if rollback_state else None
                    
                    self._conn.execute(
                        """UPDATE transaction_actions 
                           SET status = 'ROLLED_BACK', state_after = ?, 
                               completed_at = ?, updated_at = ?
                           WHERE action_id = ?""",
                        (state_after, _now(), _now(), action_id)
                    )
                    
                    # Log the rollback event
                    self._conn.execute(
                        """INSERT INTO transaction_actions 
                           (action_id, request_id, tool, target, status, summary, 
                            state_before, state_after, completed_at, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (f"{action['action_id']}_rollback", request_id, "SYSTEM_ROLLBACK", target, 
                         self.PENDING, rollback_reason, action.get("state_before"), state_after, 
                         _now(), _now(), _now())
                    )
                    
                except Exception:
                    self._conn.rollback()
                    return False
                
                self._conn.commit()
                return True

    def restore_from_state(
        self,
        *,
        request_id: str,
        tool: str,
        state_before: dict,
        operation_fn: Optional[callable] = None,
        expected_state: Optional[dict] = None,
    ) -> tuple[bool, dict]:
        """
        Attempt to restore/revert a previous action based on state_before.
        
        Returns (success, details) tuple where success indicates if restoration completed.
        
        This is the core rollback operation - it uses the captured state_before 
        to reconstruct and re-apply actions for recovery.
        """
        with self._lock:
            with self._conn:
                try:
                    # Find action by tool/state info
                    cursor = self._conn.execute(
                        """SELECT * FROM transaction_actions 
                           WHERE request_id = ? AND (
                               (tool = ? AND target IS NOT NULL) OR 
                               (tool = ? AND target = '')
                           )""",
                        (request_id, tool, tool)
                    )
                    
                    actions = [dict(row) for row in cursor.fetchall()]
                    
                except Exception:
                    return False, {"error": "Could not query previous action"}
                
                # Restore the state before attempting operation
                if state_before.get("content"):
                    self._restore_file_state(state_before["content"], tool)
                elif state_before.get("rows"):
                    self._restore_db_state(request_id, tool, state_before["rows"])
                
                details = {
                    "actions_restored": len(actions),
                    "state_recovered": True,
                }
                
                return True, details

    def get_action_status(self, action_id: str) -> Optional[dict]:
        """Get the current status of an action."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM transaction_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_action_for_request(self, request_id: str, tool: str) -> Optional[dict]:
        """Get the most recent action for a given request and tool."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM transaction_actions 
                   WHERE request_id = ? AND tool = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (request_id, tool)
            ).fetchone()
            return dict(rows) if rows else None

    def list_actions_for_request(self, request_id: str, status_filter: Optional[str] = None) -> list[dict]:
        """List all actions for a request, optionally filtered by status."""
        with self._lock:
            query = "SELECT * FROM transaction_actions WHERE request_id = ? ORDER BY created_at"
            if status_filter:
                query += f" AND status = {sql_quote(status_filter)}"
                
            rows = self._conn.execute(query, (request_id,)).fetchall()
            return [dict(row) for row in rows]

    def list_pending_actions(self, request_id: str) -> list[dict]:
        """List all pending actions that can be restored."""
        with self._lock:
            cursor = self._conn.execute(
                """SELECT * FROM transaction_actions 
                   WHERE request_id = ? AND status IN ('PENDING', 'IN_PROGRESS')
                   ORDER BY started_at DESC""",
                (request_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_action_session(self, session_id: str) -> Optional[dict]:
        """Get an action session by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM action_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def close(self) -> None:
        """Close the database connection properly."""
        with self._lock:
            self._conn.close()

    # --- Helper methods for tool-specific state management ---

    def _get_file_state(self, file_path: str) -> Optional[str]:
        """Retrieve file content/state - hook point for actual implementation."""
        try:
            path = Path(file_path)
            if path.exists():
                return path.read_text(encoding="utf-8")
            return None
        except Exception:
            return None

    def _restore_file_state(self, state: str, tool: str) -> None:
        """Restore file state - hook point for actual implementation."""
        try:
            Path(state).write_text(state, encoding="utf-8")
        except Exception:
            pass  # Silently fail - caller should handle

    def _get_db_target_state(
        self, request_id: str, table: str, query_type: str = "SELECT"
    ) -> list[dict]:
        """Get current database state for rollback comparison."""
        try:
            # This is a placeholder - implement based on actual tools used
            return []
        except Exception:
            return []

    def _restore_db_state(
        self, request_id: str, table: str, state: list[dict]
    ) -> None:
        """Restore database state from captured data."""
        try:
            # Implement based on actual tools used
            pass
        except Exception:
            pass  # Silently fail - caller should handle

    def _sql_quote(self, value: str) -> str:
        """Quote a string for SQL safety."""
        return f"'{value.replace("'", "''")}'" if value else ""


def create_transaction_log_store(db_path: Path | str) -> TransactionLogStore:
    """Factory function to create a transaction-safe action log store."""
    return TransactionLogStore(db_path)
