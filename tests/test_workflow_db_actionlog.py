import pytest
from mainframe_workflow_mcp.db import ActionLogStore

@pytest.fixture
def store(tmp_path):
    s = ActionLogStore(tmp_path / "state.db")
    yield s
    s.close()

def test_add_and_list_recent_action_log(store):
    store.add_action_log(
        tool="dataset.read", target="HLQ.SRC(PROG1)",
        status="ok", summary="dataset.read completed.", input_json='{"dataset": "HLQ.SRC"}',
        diff_hash=None, now="2026-08-19T00:05:00+00:00",
    )
    rows = store.list_recent_action_log()
    assert len(rows) == 1
    assert rows[0]["tool"] == "dataset.read"
    assert rows[0]["status"] == "ok"

def test_add_action_log_allows_null_target(store):
    store.add_action_log(
        tool="connection.verify", target=None,
        status="ok", summary="connection.verify completed.", input_json="{}",
        diff_hash=None, now="2026-08-19T00:06:00+00:00",
    )
    rows = store.list_recent_action_log()
    assert rows[0]["target"] is None

def test_list_recent_action_log_orders_newest_first_and_respects_limit(store):
    for i in range(3):
        store.add_action_log(
            tool=f"tool.{i}", target=None, status="ok", summary="ok",
            input_json=None, diff_hash=None, now=f"2026-08-19T00:0{i}:00+00:00",
        )
    rows = store.list_recent_action_log(limit=2)
    assert [r["tool"] for r in rows] == ["tool.2", "tool.1"]

def test_vacuum_does_not_raise(store):
    store.vacuum()
