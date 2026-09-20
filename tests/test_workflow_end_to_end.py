import sqlite3
import pytest
from fastmcp import Client, FastMCP
from mainframe_workflow_mcp.db import ActionLogStore
from mainframe_workflow_mcp.proxy import register_zcrafter_tools
from mainframe_workflow_mcp.action_log_sink import ActionLogSink

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
async def test_mutating_call_reaches_executor_and_is_persisted_to_the_real_sqlite_file(tmp_path):
    db_path = tmp_path / "state.db"
    store = ActionLogStore(db_path)
    mcp = FastMCP("e2e")
    executor = RecordingExecutor(ActionLogSink(store))
    register_zcrafter_tools(mcp, executor)

    # No request/spec/plan workflow anymore: a mutating call goes straight
    # through, the same as a read-only one -- backend is expected to have
    # already gated it before ever calling bridge.
    async with Client(mcp) as client:
        result = await client.call_tool(
            "member.patch",
            {
                "profileName": "default",
                "dataset": "IBMUSER.COBOL.COPY",
                "member": "CUSTREC",
                "unifiedDiff": "--- a\n+++ b\n@@\n+       05 MIDDLE-NAME PIC X(20).\n",
            },
        )
    assert result.data["status"] == "ok"
    store.close()

    # --- The actual "open the database and look" check, done independently ---
    raw_conn = sqlite3.connect(str(db_path))
    raw_conn.row_factory = sqlite3.Row
    try:
        action_rows = raw_conn.execute(
            "SELECT tool, status, input_json FROM action_log"
        ).fetchall()
        assert len(action_rows) == 1
        assert action_rows[0]["tool"] == "member.patch"
        assert action_rows[0]["status"] == "ok"
        # unifiedDiff is hashed, never persisted in the clear.
        assert "MIDDLE-NAME" not in action_rows[0]["input_json"]

        tables = {
            row["name"]
            for row in raw_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } - {"sqlite_sequence"}  # sqlite's own internal AUTOINCREMENT bookkeeping table
        assert tables == {"action_log"}, (
            "bridge's local store should hold only the action log now -- "
            "no requests/spec_revisions/plan_revisions/clarifications tables"
        )
    finally:
        raw_conn.close()
