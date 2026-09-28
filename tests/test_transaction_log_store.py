"""Tests for TransactionLogStore - idempotency and rollback validation."""
import pytest
from pathlib import Path
from datetime import datetime, timezone
import uuid
import sqlite3
from mainframe_workflow_mcp.action_log import (
    TransactionLogStore,
    _now,
)


@pytest.fixture
def transaction_store(tmp_path):
    """Create a fresh TransactionLogStore for each test."""
    from mainframe_workflow_mcp import db as db_module
    # Create temp db path, let TransactionLogStore handle schema initialization
    db_path = tmp_path / "action_state.db"
    store = TransactionLogStore(str(db_path))
    
    # Drop and recreate to ensure clean state for testing
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM transaction_actions")
    conn.commit()
    conn.close()
    
    yield store


def get_db_connection(db_path):
    """Helper to create database connection for tests."""
    return sqlite3.connect(str(db_path))


class TestIdempotency:
    """Test that the same action can be attempted multiple times safely."""

    def test_idempotent_action_insertion(self, transaction_store):
        """Repeated action attempts should not create duplicates due to UNIQUE constraint."""
        request_id = "req-999"
        tool = "dataset.read"
        target = "HLQ.SRC(PROG1)"
        
        # First attempt - should create new entry
        action1 = transaction_store.begin_action(
            request_id=request_id,
            tool=tool,
            target=target,
            summary="Initial dataset read",
            input_json='{"dataset": "HLQ.SRC"}',
        )
        
        # Second identical attempt - should find existing entry and update
        action2 = transaction_store.begin_action(
            request_id=request_id,
            tool=tool,
            target=target,
            summary="Initial dataset read",  # Same summary
            input_json='{"dataset": "HLQ.SRC"}',  # Same input
        )
        
        # Both should have the same action_id (idempotent)
        assert action1["action_id"] == action2["action_id"]
        
        # Query directly to verify unique constraint
        import sqlite3
        conn = get_db_connection(transaction_store.db_path)
        rows = conn.execute(
            "SELECT * FROM transaction_actions "
            "WHERE request_id = ? AND action_session_id = ?", (request_id, "session-123")
        ).fetchall()
        
        # Should only have one entry
        assert len(rows) == 1
        
        row = rows[0]
        # Status should be PENDING since we haven't committed yet
        assert row["status"] == transaction_store.PENDING
        conn.close()

    def test_idempotent_action_commit(self, transaction_store):
        """Committing the same action multiple times should update status idempotently."""
        request_id = "req-999"
        action_id = f"act-{datetime.now(timezone.utc).timestamp()}_{uuid.uuid4().hex[:8]}"
        
        # Pre-create a pending action with specific ID
        import sqlite3
        conn = sqlite3.connect(str(transaction_store._db_path))
        state_before = {"content": "test content"}
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (action_id, request_id, "dataset.read", None, 
             transaction_store.PENDING, "Test read", str(state_before), _now(), _now()),
        )
        conn.commit()
        conn.close()
        
        # First commit - should succeed
        result1 = transaction_store.commit_action(action_id, success=True)
        assert result1 is True
        
        # Second commit with same action_id - should also succeed (idempotent update)
        result2 = transaction_store.commit_action(action_id, success=True)
        assert result2 is True

    def test_status_constraints_enforced(self, transaction_store):
        """Attempting invalid status updates should fail."""
        import sqlite3
        conn = sqlite3.connect(str(transaction_store.db_path))
        
        # Create an action with valid PENDING status
        state_before = {"content": "test"}
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-test", "req-999", "dataset.read", None, 
             transaction_store.PENDING, "Test", str(state_before), _now(), _now()),
        )
        conn.commit()
        conn.close()
        
        # Try to force INSERT with invalid status (should fail due to CHECK constraint)
        import sqlite3
        conn = sqlite3.connect(str(transaction_store._db_path))
        try:
            conn.execute(
                """INSERT INTO transaction_actions 
                   (action_id, request_id, tool, target, status, summary)
                   VALUES ('act-bad', 'req-999', 'dataset.read', None, 'INVALID_STATUS', 'test')""",
            )
            assert False, "Should have raised IntegrityError"
        except sqlite3.IntegrityError as e:
            # Expected - status CHECK constraint violation
            assert "CHECK" in str(e) or "status" in str(e).lower()
        conn.close()


class TestRollback:
    """Test rollback functionality using captured state_before."""

    def test_rollback_entry_creation(self, transaction_store):
        """Creating a rollback entry should mark action as ROLLED_BACK."""
        request_id = "req-999"
        
        # Create a pending action with known state
        import sqlite3
        conn = sqlite3.connect(str(transaction_store._db_path))
        state_before = {"content": "original file content", "line_count": 10}
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-rollback-test", request_id, "dataset.update", None, 
             transaction_store.PENDING, "Test update", str(state_before), _now(), _now()),
        )
        conn.commit()
        
        rollback_entry = transaction_store.create_rollback_entry(
            request_id=request_id,
            tool="dataset.update",
            target=None,
            action_id="act-rollback-test",
            rollback_reason="Upstream failure detected",
        )
        
        assert rollback_entry is True
        
        # Verify status was updated to ROLLED_BACK
        conn = sqlite3.connect(str(transaction_store._db_path))
        row = conn.execute(
            "SELECT * FROM transaction_actions WHERE action_id = ?", ("act-rollback-test",)
        ).fetchone()
        assert row is not None
        assert row["status"] == "ROLLED_BACK"
        conn.close()

    def test_restore_from_state_basic(self, transaction_store):
        """Restore operation should return success and details."""
        request_id = "req-999"
        
        # Create action with state_before containing file content
        import sqlite3
        original_content = """def hello():
    print("world")
"""
        
        conn = sqlite3.connect(str(transaction_store._db_path))
        state_before = {"content": original_content}
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-restore-test", request_id, "dataset.write", None, 
             transaction_store.PENDING, "Test restore", str(state_before), _now(), _now()),
        )
        conn.commit()
        conn.close()
        
        # Attempt to restore from captured state
        success, details = transaction_store.restore_from_state(
            request_id=request_id,
            tool="dataset.write",
            state_before=state_before,
        )
        
        assert success is True
        assert "actions_restored" in details
        assert "state_recovered" in details

    def test_multiple_actions_per_session(self, transaction_store):
        """Multiple actions within the same request should be tracked separately."""
        request_id = "req-999"
        
        # Create two separate actions with different action_ids
        import sqlite3
        state_before1 = {"content": "first state"}
        state_before2 = {"content": "second state"}
        
        conn = sqlite3.connect(str(transaction_store._db_path))
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-first", request_id, "dataset.read", None, 
             transaction_store.PENDING, "First read", str(state_before1), _now(), _now()),
        )
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-second", request_id, "dataset.update", None, 
             transaction_store.PENDING, "Second update", str(state_before2), _now(), _now()),
        )
        conn.commit()
        conn.close()
        
        # Should retrieve both actions
        actions = transaction_store.list_actions_for_request(request_id)
        assert len(actions) >= 2
        
        action_ids = [a["action_id"] for a in actions]
        assert "act-first" in action_ids
        assert "act-second" in action_ids

    def test_action_status_filtering(self, transaction_store):
        """List actions should support optional status filtering."""
        request_id = "req-999"
        
        import sqlite3
        conn = sqlite3.connect(str(transaction_store._db_path))
        
        # Insert actions with different statuses
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-pending", request_id, "dataset.read", None, 
             transaction_store.PENDING, "Pending read", "{}", _now()),
        )
        
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("act-successful", request_id, "dataset.update", None, 
             transaction_store.SUCCESS, "Update done", "{}"),
        )
        
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("act-failed", request_id, "dataset.delete", None, 
             transaction_store.FAILURE, "Delete error", "{}"),
        )
        
        conn.commit()
        conn.close()
        
        # List all actions - should return 3
        all_actions = transaction_store.list_actions_for_request(request_id)
        assert len(all_actions) == 3
        
        # List only pending actions - should return 1
        pending = transaction_store.list_pending_actions(request_id)
        assert len(pending) == 1
        assert pending[0]["status"] == transaction_store.PENDING

    def test_get_action_for_request(self, transaction_store):
        """Get action for request should return most recent action."""
        request_id = "req-999"
        
        import sqlite3
        from datetime import timedelta
        
        conn = sqlite3.connect(str(transaction_store._db_path))
        
        # Insert two actions with different timestamps
        now1 = _now()
        now2 = str(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        
        state_before = {"content": "first"}
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-old", request_id, "dataset.read", None, 
             transaction_store.SUCCESS, "Old action", str(state_before), now1, _now()),
        )
        
        state_before = {"content": "newer"}
        conn.execute(
            """INSERT INTO transaction_actions 
               (action_id, request_id, tool, target, status, summary, 
                state_before, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("act-newer", request_id, "dataset.read", None, 
             transaction_store.SUCCESS, "Newer action", str(state_before), now2, _now()),
        )
        
        conn.commit()
        conn.close()
        
        # Get the most recent action - should be act-newer (higher timestamp)
        result = transaction_store.get_action_for_request(request_id, "dataset.read")
        assert result is not None
        assert result["action_id"] == "act-newer"


class TestIntegrationWithExistingRequests:
    """Tests that verify TransactionLogStore works with actual request data."""

    def test_transaction_log_with_real_request(self, transaction_store):
        """Create a realistic action log entry and verify retrieval."""
        request_id = "req-999"
        
        # Simulate a real workflow action
        action = transaction_store.begin_action(
            request_id=request_id,
            tool="zosmf.read",
            target="user.admin",
            summary="Read user permissions",
            input_json='{"profile": "MAINDEV"}',
        )
        
        assert action is not None
        assert action["request_id"] == request_id
        assert action["tool"] == "zosmf.read"
        assert action["target"] == "user.admin"
        assert action["status"] == transaction_store.PENDING
        
        # List actions for this request
        all_actions = transaction_store.list_actions_for_request(request_id)
        
        # Should find our action in the list
        matching_actions = [a for a in all_actions if a["tool"] == "zosmf.read"]
        assert len(matching_actions) >= 1
        
    def test_action_session_management(self, transaction_store):
        """Verify action session creation and retrieval."""
        request_id = "req-999"
        
        # Get or create action session
        session = transaction_store._ensure_action_session(request_id)
        assert session is not None
        
        # Session should exist in database
        row = transaction_store.get_action_session(session)
        assert row is not None
        assert row["session_id"] == session
