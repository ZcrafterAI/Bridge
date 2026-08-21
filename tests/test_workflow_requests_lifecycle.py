import pytest
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager

@pytest.fixture
def manager(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    yield RequestManager(store)
    store.close()

def test_cancel_request_from_clarifying(manager):
    request_id = manager.start_request("a")["request_id"]
    result = manager.cancel_request(request_id, "user changed their mind")
    assert result["status"] == "ABANDONED"
    row = manager.get_request(request_id)
    assert row["status"] == "ABANDONED"
    assert row["cancel_reason"] == "user changed their mind"

def test_cancel_request_unknown_raises(manager):
    with pytest.raises(ValueError, match="No such request"):
        manager.cancel_request("nope", "reason")

def test_complete_request_requires_plan_approved_or_executing(manager):
    request_id = manager.start_request("a")["request_id"]
    with pytest.raises(ValueError, match="PLAN_APPROVED"):
        manager.complete_request(request_id)

def test_complete_request_succeeds_from_plan_approved(manager):
    request_id = manager.start_request("a")["request_id"]
    manager.draft_spec(request_id, "spec")
    manager.approve_spec(request_id)
    manager.draft_plan(request_id, "plan")
    manager.approve_plan(request_id)

    result = manager.complete_request(request_id)

    assert result["status"] == "COMPLETED"
    assert manager.get_request(request_id)["status"] == "COMPLETED"
