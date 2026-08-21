import pytest
from mainframe_workflow_mcp.db import RequestStore

@pytest.fixture
def store(tmp_path):
    s = RequestStore(tmp_path / "state.db")
    s.create_request("req-1", "raw ask", now="2026-08-19T00:00:00+00:00")
    yield s
    s.close()

def test_latest_spec_revision_none_when_empty(store):
    assert store.latest_spec_revision("req-1") is None

def test_add_and_get_latest_spec_revision(store):
    store.add_spec_revision("req-1", 1, "# Spec v1", now="2026-08-19T00:01:00+00:00")
    store.add_spec_revision("req-1", 2, "# Spec v2", now="2026-08-19T00:02:00+00:00")
    latest = store.latest_spec_revision("req-1")
    assert latest["version"] == 2
    assert latest["content"] == "# Spec v2"

def test_add_and_get_latest_plan_revision(store):
    store.add_plan_revision("req-1", 1, "# Plan v1", now="2026-08-19T00:03:00+00:00")
    latest = store.latest_plan_revision("req-1")
    assert latest["version"] == 1
    assert latest["content"] == "# Plan v1"

def test_plan_revision_none_when_empty(store):
    assert store.latest_plan_revision("req-1") is None
