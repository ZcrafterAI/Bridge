import pytest
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager

@pytest.fixture
def manager(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    yield RequestManager(store)
    store.close()

def test_draft_spec_advances_from_clarifying(manager):
    started = manager.start_request("a")
    result = manager.draft_spec(started["request_id"], "# Spec v1")
    assert result["phase"] == "SPEC_DRAFT"
    assert result["version"] == 1

def test_draft_spec_again_stays_spec_draft_and_bumps_version(manager):
    started = manager.start_request("a")
    manager.draft_spec(started["request_id"], "# Spec v1")
    result = manager.draft_spec(started["request_id"], "# Spec v2")
    assert result["phase"] == "SPEC_DRAFT"
    assert result["version"] == 2

def test_approve_spec_requires_spec_draft(manager):
    started = manager.start_request("a")
    with pytest.raises(ValueError, match="SPEC_DRAFT"):
        manager.approve_spec(started["request_id"])

def test_approve_spec_succeeds_from_spec_draft(manager):
    started = manager.start_request("a")
    manager.draft_spec(started["request_id"], "# Spec v1")
    result = manager.approve_spec(started["request_id"])
    assert result["phase"] == "SPEC_APPROVED"
    status = manager.get_request_status(started["request_id"])
    assert status["spec_approved_version"] == 1

def test_editing_approved_spec_resets_to_spec_draft_and_clears_approval(manager):
    request_id = manager.start_request("a")["request_id"]
    manager.draft_spec(request_id, "# Spec v1")
    manager.approve_spec(request_id)

    result = manager.draft_spec(request_id, "# Spec v2")

    assert result["phase"] == "SPEC_DRAFT"
    status = manager.get_request_status(request_id)
    assert status["spec_approved_version"] is None
    assert status["latest_spec"]["content"] == "# Spec v2"

def test_editing_approved_spec_after_plan_approval_also_clears_plan_approval(manager):
    request_id = manager.start_request("a")["request_id"]
    manager.draft_spec(request_id, "# Spec v1")
    manager.approve_spec(request_id)
    manager.draft_plan(request_id, "# Plan v1")
    manager.approve_plan(request_id)

    manager.draft_spec(request_id, "# Spec v2 - scope changed")

    status = manager.get_request_status(request_id)
    assert status["phase"] == "SPEC_DRAFT"
    assert status["spec_approved_version"] is None
    assert status["plan_approved_version"] is None
