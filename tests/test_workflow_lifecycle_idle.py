from datetime import datetime, timedelta, timezone
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.lifecycle import idle_sweep

def test_idle_sweep_abandons_untouched_active_requests(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    old_touch = (now - timedelta(days=20)).isoformat()
    store.create_request("req-old", "a", now=old_touch)

    abandoned = idle_sweep(store, idle_days=14, now=now)

    assert abandoned == ["req-old"]
    row = store.get_request("req-old")
    assert row["status"] == "ABANDONED"
    assert row["cancel_reason"] == "idle timeout"
    store.close()

def test_idle_sweep_leaves_recently_touched_requests_alone(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    recent_touch = (now - timedelta(days=2)).isoformat()
    store.create_request("req-recent", "a", now=recent_touch)

    abandoned = idle_sweep(store, idle_days=14, now=now)

    assert abandoned == []
    assert store.get_request("req-recent")["status"] == "ACTIVE"
    store.close()

def test_idle_sweep_ignores_already_terminal_requests(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    old_touch = (now - timedelta(days=100)).isoformat()
    store.create_request("req-done", "a", now=old_touch)
    store.update_phase_status("req-done", status="COMPLETED", now=old_touch)

    abandoned = idle_sweep(store, idle_days=14, now=now)

    assert abandoned == []
    store.close()
