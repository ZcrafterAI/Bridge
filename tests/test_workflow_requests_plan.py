import pytest
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager

@pytest.fixture
def manager(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    yield RequestManager(store)
    store.close()

def _to_spec_approved(manager, raw="a"):
    request_id = manager.start_request(raw)["request_id"]
    manager.draft_spec(request_id, "# Spec v1")
    manager.approve_spec(request_id)
    return request_id

def test_draft_plan_requires_approved_spec(manager):
    request_id = manager.start_request("a")["request_id"]
    with pytest.raises(ValueError, match="spec"):
        manager.draft_plan(request_id, "# Plan v1")

def test_draft_plan_advances_from_spec_approved(manager):
    request_id = _to_spec_approved(manager)
    result = manager.draft_plan(request_id, "# Plan v1")
    assert result["phase"] == "PLAN_DRAFT"
    assert result["version"] == 1

def test_approve_plan_requires_plan_draft(manager):
    request_id = _to_spec_approved(manager)
    with pytest.raises(ValueError, match="PLAN_DRAFT"):
        manager.approve_plan(request_id)

def test_approve_plan_succeeds_from_plan_draft(manager):
    request_id = _to_spec_approved(manager)
    manager.draft_plan(request_id, "# Plan v1")
    result = manager.approve_plan(request_id)
    assert result["phase"] == "PLAN_APPROVED"

def test_editing_approved_plan_resets_to_plan_draft(manager):
    request_id = _to_spec_approved(manager)
    manager.draft_plan(request_id, "# Plan v1")
    manager.approve_plan(request_id)

    result = manager.draft_plan(request_id, "# Plan v2")

    assert result["phase"] == "PLAN_DRAFT"
    status = manager.get_request_status(request_id)
    assert status["plan_approved_version"] is None
    # The spec approval is untouched by a plan edit.
    assert status["spec_approved_version"] == 1

def test_mark_executing_transitions_from_plan_approved(manager):
    request_id = _to_spec_approved(manager)
    manager.draft_plan(request_id, "# Plan v1")
    manager.approve_plan(request_id)

    manager.mark_executing(request_id)

    assert manager.get_request(request_id)["phase"] == "EXECUTING"

def test_mark_executing_is_idempotent_when_already_executing(manager):
    request_id = _to_spec_approved(manager)
    manager.draft_plan(request_id, "# Plan v1")
    manager.approve_plan(request_id)
    manager.mark_executing(request_id)

    manager.mark_executing(request_id)  # should not raise

    assert manager.get_request(request_id)["phase"] == "EXECUTING"

def test_draft_plan_while_executing_resets_to_plan_draft(manager):
    request_id = _to_spec_approved(manager)
    manager.draft_plan(request_id, "# Plan v1")
    manager.approve_plan(request_id)
    manager.mark_executing(request_id)

    result = manager.draft_plan(request_id, "# Plan v2 - revised mid-execution")

    assert result["phase"] == "PLAN_DRAFT"
