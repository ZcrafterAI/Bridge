import json
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.action_log_sink import ActionLogSink, current_request_id

def test_log_persists_entry_tagged_with_current_request_id(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    store.create_request("req-1", "a", now="2026-08-19T00:00:00+00:00")
    sink = ActionLogSink(store)

    token = current_request_id.set("req-1")
    try:
        sink.log({
            "id": "call-1", "tool": "dataset.read", "target": "HLQ.SRC(PROG1)",
            "status": "ok", "timestamp": "2026-08-19T00:05:00+00:00",
            "summary": "dataset.read completed.",
            "input": {"dataset": "HLQ.SRC", "member": "PROG1"},
        })
    finally:
        current_request_id.reset(token)

    rows = store.list_action_log("req-1")
    assert len(rows) == 1
    assert rows[0]["tool"] == "dataset.read"
    assert rows[0]["target"] == "HLQ.SRC(PROG1)"
    assert json.loads(rows[0]["input_json"]) == {"dataset": "HLQ.SRC", "member": "PROG1"}
    store.close()

def test_log_with_no_current_request_id_persists_as_untagged(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    sink = ActionLogSink(store)

    sink.log({
        "id": "call-2", "tool": "connection.verify", "target": "connection.verify",
        "status": "ok", "timestamp": "2026-08-19T00:06:00+00:00",
        "summary": "connection.verify completed.",
    })

    # Nothing raised; there is no request to tag it to. Untagged entries
    # aren't independently queryable by list_action_log (which requires a
    # request_id) — this test only proves the insert doesn't fail.
    store.close()

def test_log_carries_diff_hash_through(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    store.create_request("req-1", "a", now="2026-08-19T00:00:00+00:00")
    sink = ActionLogSink(store)

    token = current_request_id.set("req-1")
    try:
        sink.log({
            "id": "call-3", "tool": "member.patch", "target": "HLQ.SRC(PROG1)",
            "status": "ok", "timestamp": "2026-08-19T00:07:00+00:00",
            "summary": "member.patch completed.", "diffHash": "abc123",
        })
    finally:
        current_request_id.reset(token)

    rows = store.list_action_log("req-1")
    assert rows[0]["diff_hash"] == "abc123"
    store.close()

def test_log_redacts_sensitive_input_fields_before_persisting(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    store.create_request("req-1", "a", now="2026-08-19T00:00:00+00:00")
    sink = ActionLogSink(store)

    token = current_request_id.set("req-1")
    try:
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
    finally:
        current_request_id.reset(token)

    rows = store.list_action_log("req-1")
    persisted_input = json.loads(rows[0]["input_json"])
    assert "hunter2" not in json.dumps(persisted_input)
    assert "new secret line" not in json.dumps(persisted_input)
    assert persisted_input["unifiedDiff"] == "[HASHED]"
    assert persisted_input["password"] == "[REDACTED]"
    assert persisted_input["dataset"] == "HLQ.SRC"
    store.close()
