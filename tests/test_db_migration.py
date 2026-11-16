"""A store made by an earlier version keeps working after an upgrade."""
import sqlite3

from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager

OLD_SCHEMA = """
CREATE TABLE requests (id TEXT PRIMARY KEY, raw_request TEXT NOT NULL, phase TEXT NOT NULL, status TEXT NOT NULL,
    spec_approved_version INTEGER, spec_approved_at TEXT, plan_approved_version INTEGER, plan_approved_at TEXT,
    cancel_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE plan_revisions (request_id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY (request_id, version));
INSERT INTO requests VALUES ('old-1', 'an old request', 'PLAN_APPROVED', 'ACTIVE', 1, 't', 1, 't', NULL, 't', 't');
INSERT INTO plan_revisions VALUES ('old-1', 1, 'a plan written as free text', 't');
"""


def test_an_old_store_opens_and_its_old_plans_unlock_nothing(tmp_path):
    path = tmp_path / "state.db"
    raw = sqlite3.connect(str(path))
    raw.executescript(OLD_SCHEMA)
    raw.commit()
    raw.close()

    store = RequestStore(path)
    manager = RequestManager(store)

    # A plan approved before plans had steps lists no changes, so it allows none.
    version, steps, uses = manager.approved_plan("old-1")
    assert (version, steps, uses) == (1, [], {})
    assert manager.get_request_status("old-1")["latest_plan"]["steps"] == []
    # And the upgraded store takes new plans with steps.
    manager.draft_plan("old-1", "now with steps", [{"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}}])
    assert manager.get_request_status("old-1")["latest_plan"]["steps"][0]["tool"] == "dataset.delete"
    store.close()
    RequestStore(path).close()  # opening it again changes nothing and does not fail
