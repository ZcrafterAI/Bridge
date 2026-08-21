import pytest
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager

@pytest.fixture
def manager(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    yield RequestManager(store)
    store.close()

def test_start_request_returns_new_id_in_clarifying_phase(manager):
    result = manager.start_request("add a field to CUSTREC")
    assert result["phase"] == "CLARIFYING"
    assert result["status"] == "ACTIVE"
    assert result["request_id"]

def test_record_clarification_appends_to_log(manager):
    started = manager.start_request("add a field to CUSTREC")
    manager.record_clarification(started["request_id"], "which dataset?", "IBMUSER.COBOL.SRC")
    status = manager.get_request_status(started["request_id"])
    assert status["clarifications"] == [{"question": "which dataset?", "answer": "IBMUSER.COBOL.SRC"}]

def test_record_clarification_unknown_request_raises(manager):
    with pytest.raises(ValueError, match="No such request"):
        manager.record_clarification("nope", "q", "a")

def test_list_requests_defaults_to_active(manager):
    started = manager.start_request("a")
    assert [r["id"] for r in manager.list_requests()] == [started["request_id"]]
    assert manager.list_requests(status="COMPLETED") == []

def test_get_request_status_unknown_raises(manager):
    with pytest.raises(ValueError, match="No such request"):
        manager.get_request_status("nope")
