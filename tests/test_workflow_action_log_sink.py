import json
from mainframe_workflow_mcp.db import ActionLogStore
from mainframe_workflow_mcp.action_log_sink import ActionLogSink

def test_log_persists_entry(tmp_path):
    store = ActionLogStore(tmp_path / "state.db")
    sink = ActionLogSink(store)

    sink.log({
        "id": "call-1", "tool": "dataset.read", "target": "HLQ.SRC(PROG1)",
        "status": "ok", "timestamp": "2026-08-19T00:05:00+00:00",
        "summary": "dataset.read completed.",
        "input": {"dataset": "HLQ.SRC", "member": "PROG1"},
    })

    rows = store.list_recent_action_log()
    assert len(rows) == 1
    assert rows[0]["tool"] == "dataset.read"
    assert rows[0]["target"] == "HLQ.SRC(PROG1)"
    assert json.loads(rows[0]["input_json"]) == {"dataset": "HLQ.SRC", "member": "PROG1"}
    store.close()

def test_log_with_no_input_persists_null_input_json(tmp_path):
    store = ActionLogStore(tmp_path / "state.db")
    sink = ActionLogSink(store)

    sink.log({
        "id": "call-2", "tool": "connection.verify", "target": "connection.verify",
        "status": "ok", "timestamp": "2026-08-19T00:06:00+00:00",
        "summary": "connection.verify completed.",
    })

    rows = store.list_recent_action_log()
    assert rows[0]["input_json"] is None
    store.close()

def test_log_carries_diff_hash_through(tmp_path):
    store = ActionLogStore(tmp_path / "state.db")
    sink = ActionLogSink(store)

    sink.log({
        "id": "call-3", "tool": "member.patch", "target": "HLQ.SRC(PROG1)",
        "status": "ok", "timestamp": "2026-08-19T00:07:00+00:00",
        "summary": "member.patch completed.", "diffHash": "abc123",
    })

    rows = store.list_recent_action_log()
    assert rows[0]["diff_hash"] == "abc123"
    store.close()

def test_log_redacts_sensitive_input_fields_before_persisting(tmp_path):
    store = ActionLogStore(tmp_path / "state.db")
    sink = ActionLogSink(store)

    sink.log({
        "id": "call-4", "tool": "member.patch", "target": "HLQ.SRC(PROG1)",
        "status": "ok", "timestamp": "2026-08-19T00:08:00+00:00",
        "summary": "member.patch completed.",
        "input": {
            "dataset": "HLQ.SRC",
            "member": "PROG1",
            "unifiedDiff": "--- a\n+++ b\n-old\n+new secret line",
            "password": "hunter2",
        },
    })

    rows = store.list_recent_action_log()
    persisted_input = json.loads(rows[0]["input_json"])
    assert "hunter2" not in json.dumps(persisted_input)
    assert "new secret line" not in json.dumps(persisted_input)
    assert persisted_input["unifiedDiff"] == "[HASHED]"
    assert persisted_input["password"] == "[REDACTED]"
    assert persisted_input["dataset"] == "HLQ.SRC"
    store.close()
