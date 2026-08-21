import pytest
from mainframe_workflow_mcp.db import RequestStore

@pytest.fixture
def store(tmp_path):
    s = RequestStore(tmp_path / "state.db")
    s.create_request("req-1", "raw ask", now="2026-08-19T00:00:00+00:00")
    yield s
    s.close()

def test_add_and_list_action_log(store):
    store.add_action_log(
        request_id="req-1", tool="dataset.read", target="HLQ.SRC(PROG1)",
        status="ok", summary="dataset.read completed.", input_json='{"dataset": "HLQ.SRC"}',
        diff_hash=None, now="2026-08-19T00:05:00+00:00",
    )
    rows = store.list_action_log("req-1")
    assert len(rows) == 1
    assert rows[0]["tool"] == "dataset.read"
    assert rows[0]["status"] == "ok"

def test_action_log_allows_null_request_id_for_untagged_reads(store):
    store.add_action_log(
        request_id=None, tool="connection.verify", target=None,
        status="ok", summary="connection.verify completed.", input_json="{}",
        diff_hash=None, now="2026-08-19T00:06:00+00:00",
    )
    # Untagged entries aren't visible via list_action_log(request_id=...); this
    # just proves the insert doesn't violate a NOT NULL constraint.

def test_delete_request_cascade_removes_all_related_rows(store):
    store.add_spec_revision("req-1", 1, "spec", now="2026-08-19T00:01:00+00:00")
    store.add_plan_revision("req-1", 1, "plan", now="2026-08-19T00:02:00+00:00")
    store.add_clarification("req-1", "q", "a", now="2026-08-19T00:03:00+00:00")
    store.add_action_log(
        request_id="req-1", tool="dataset.read", target=None, status="ok",
        summary="ok", input_json="{}", diff_hash=None, now="2026-08-19T00:04:00+00:00",
    )

    store.delete_request_cascade("req-1")

    assert store.get_request("req-1") is None
    assert store.list_clarifications("req-1") == []
    assert store.latest_spec_revision("req-1") is None
    assert store.latest_plan_revision("req-1") is None
    assert store.list_action_log("req-1") == []

def test_vacuum_does_not_raise(store):
    store.vacuum()
