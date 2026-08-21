import pytest
from mainframe_workflow_mcp.db import RequestStore

@pytest.fixture
def store(tmp_path):
    s = RequestStore(tmp_path / "state.db")
    yield s
    s.close()

def test_create_and_get_request(store):
    store.create_request("req-1", "add a new field to CUSTREC", now="2026-08-19T00:00:00+00:00")
    row = store.get_request("req-1")
    assert row["id"] == "req-1"
    assert row["raw_request"] == "add a new field to CUSTREC"
    assert row["phase"] == "CLARIFYING"
    assert row["status"] == "ACTIVE"
    assert row["spec_approved_version"] is None
    assert row["spec_approved_at"] is None
    assert row["plan_approved_version"] is None
    assert row["plan_approved_at"] is None

def test_get_request_missing_returns_none(store):
    assert store.get_request("nope") is None

def test_list_requests_filters_by_status(store):
    store.create_request("req-1", "a", now="2026-08-19T00:00:00+00:00")
    store.create_request("req-2", "b", now="2026-08-19T00:00:00+00:00")
    store.update_phase_status("req-2", status="ABANDONED", now="2026-08-19T01:00:00+00:00")

    active = store.list_requests("ACTIVE")
    abandoned = store.list_requests("ABANDONED")
    assert [r["id"] for r in active] == ["req-1"]
    assert [r["id"] for r in abandoned] == ["req-2"]

def test_update_phase_status_updates_fields_and_timestamp(store):
    store.create_request("req-1", "a", now="2026-08-19T00:00:00+00:00")
    store.update_phase_status("req-1", phase="SPEC_DRAFT", now="2026-08-19T02:00:00+00:00")
    row = store.get_request("req-1")
    assert row["phase"] == "SPEC_DRAFT"
    assert row["updated_at"] == "2026-08-19T02:00:00+00:00"

def test_update_phase_status_can_clear_approvals(store):
    store.create_request("req-1", "a", now="2026-08-19T00:00:00+00:00")
    store.update_phase_status(
        "req-1", spec_approved_version=1, spec_approved_at="2026-08-19T01:00:00+00:00",
        plan_approved_version=1, plan_approved_at="2026-08-19T01:30:00+00:00",
        now="2026-08-19T01:00:00+00:00",
    )
    row = store.get_request("req-1")
    assert row["spec_approved_at"] == "2026-08-19T01:00:00+00:00"
    assert row["plan_approved_at"] == "2026-08-19T01:30:00+00:00"

    store.update_phase_status("req-1", clear_spec_approval=True, clear_plan_approval=True, now="2026-08-19T02:00:00+00:00")
    row = store.get_request("req-1")
    assert row["spec_approved_version"] is None
    assert row["spec_approved_at"] is None
    assert row["plan_approved_version"] is None
    assert row["plan_approved_at"] is None

def test_add_and_list_clarifications(store):
    store.create_request("req-1", "a", now="2026-08-19T00:00:00+00:00")
    store.add_clarification("req-1", "which dataset?", "IBMUSER.COBOL.SRC", now="2026-08-19T00:01:00+00:00")
    store.add_clarification("req-1", "which member?", "PROG1", now="2026-08-19T00:02:00+00:00")
    rows = store.list_clarifications("req-1")
    assert [(r["question"], r["answer"]) for r in rows] == [
        ("which dataset?", "IBMUSER.COBOL.SRC"),
        ("which member?", "PROG1"),
    ]
