import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from fastmcp import Client
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager
from mainframe_workflow_mcp.lifecycle import archive_sweep, idle_sweep
from mainframe_workflow_mcp.proxy import register_zcrafter_tools
from mainframe_workflow_mcp.action_log_sink import ActionLogSink
from fastmcp import FastMCP

class RecordingExecutor:
    """Stand-in for zcrafter's LocalToolExecutor. Since register_zcrafter_tools
    only calls executor.execute(call) and never touches the action log itself
    (the real LocalToolExecutor is the one that calls its injected logger),
    this fake replicates that one bit of real behavior -- logging the call via
    ActionLogSink -- so the raw-sqlite readback below can verify action_log
    rows exactly as the real executor would produce them."""

    def __init__(self, sink: ActionLogSink):
        self.calls = []
        self._sink = sink

    async def execute(self, call):
        self.calls.append(call)
        self._sink.log(
            {
                "tool": call["name"],
                "target": call["input"].get("dataset"),
                "status": "ok",
                "summary": f"{call['name']} completed.",
                "input": call["input"],
            }
        )
        return {"status": "ok", "data": {"patched": True}}

@pytest.mark.anyio
async def test_full_lifecycle_is_actually_persisted_to_the_real_sqlite_file(tmp_path):
    db_path = tmp_path / "state.db"
    store = RequestStore(db_path)
    manager = RequestManager(store)
    mcp = FastMCP("e2e")
    executor = RecordingExecutor(ActionLogSink(store))
    register_zcrafter_tools(mcp, manager, executor)

    # State-transition steps (start/clarify/spec/plan) are driven directly
    # through RequestManager, matching Tasks 5-8's own tests; state tools are
    # only exposed on server.mcp (Task 14), not on the throwaway `mcp` built
    # here. The mutating step below goes through a real fastmcp.Client call
    # against `mcp`, matching exactly how Task 13's gating is exercised.
    started = manager.start_request("Add a MIDDLE-NAME field to the CUSTREC copybook")
    request_id = started["request_id"]
    manager.record_clarification(request_id, "Which dataset holds CUSTREC?", "IBMUSER.COBOL.COPY")
    manager.draft_spec(request_id, "# Spec\nAdd MIDDLE-NAME PIC X(20) to CUSTREC.")
    manager.approve_spec(request_id)
    manager.draft_plan(request_id, "# Plan\n1. Patch CUSTREC via member.patch.")
    manager.approve_plan(request_id)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "member.patch",
            {
                "profileName": "default",
                "dataset": "IBMUSER.COBOL.COPY",
                "member": "CUSTREC",
                "unifiedDiff": "--- a\n+++ b\n@@\n+       05 MIDDLE-NAME PIC X(20).\n",
                "request_id": request_id,
            },
        )
    assert result.data["status"] == "ok"

    manager.complete_request(request_id)
    store.close()

    # --- The actual "open the database and look" check, done independently ---
    raw_conn = sqlite3.connect(str(db_path))
    raw_conn.row_factory = sqlite3.Row
    try:
        row = raw_conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
        assert row is not None, "the request was not written to the database"
        assert row["raw_request"] == "Add a MIDDLE-NAME field to the CUSTREC copybook"
        assert row["status"] == "COMPLETED"
        assert row["phase"] == "EXECUTING"
        assert row["spec_approved_version"] == 1
        assert row["spec_approved_at"] is not None
        assert row["plan_approved_version"] == 1
        assert row["plan_approved_at"] is not None

        clarifications = raw_conn.execute(
            "SELECT question, answer FROM clarifications WHERE request_id = ?", (request_id,)
        ).fetchall()
        assert len(clarifications) == 1
        assert clarifications[0]["answer"] == "IBMUSER.COBOL.COPY"

        spec_rows = raw_conn.execute(
            "SELECT content FROM spec_revisions WHERE request_id = ?", (request_id,)
        ).fetchall()
        assert "MIDDLE-NAME" in spec_rows[0]["content"]

        action_rows = raw_conn.execute(
            "SELECT tool, status FROM action_log WHERE request_id = ?", (request_id,)
        ).fetchall()
        assert len(action_rows) == 1
        assert action_rows[0]["tool"] == "member.patch"
        assert action_rows[0]["status"] == "ok"
    finally:
        raw_conn.close()

def test_idle_and_archive_sweeps_actually_remove_and_preserve_data_on_disk(tmp_path):
    db_path = tmp_path / "state.db"
    archive_dir = tmp_path / "archive"
    store = RequestStore(db_path)
    manager = RequestManager(store)

    old_request = manager.start_request("An old forgotten request")
    request_id = old_request["request_id"]
    manager.draft_spec(request_id, "# Old spec")
    manager.approve_spec(request_id)

    # Backdate updated_at directly through a raw connection, simulating time
    # having passed, since the sweeps compare against wall-clock "now".
    raw_conn = sqlite3.connect(str(db_path))
    old_timestamp = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    raw_conn.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (old_timestamp, request_id))
    raw_conn.commit()
    raw_conn.close()

    abandoned = idle_sweep(store, idle_days=14)
    assert abandoned == [request_id]

    raw_conn = sqlite3.connect(str(db_path))
    very_old_timestamp = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    raw_conn.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (very_old_timestamp, request_id))
    raw_conn.commit()
    raw_conn.close()

    archived = archive_sweep(store, archive_dir, retention_days=90)
    assert archived == [request_id]

    raw_conn = sqlite3.connect(str(db_path))
    row = raw_conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    raw_conn.close()
    assert row is None, "archived request should be pruned from the live table"

    archive_file = archive_dir / f"{request_id}.md"
    assert archive_file.exists(), "archived request should be exported to a markdown file"
    assert "An old forgotten request" in archive_file.read_text(encoding="utf-8")

    store.close()
