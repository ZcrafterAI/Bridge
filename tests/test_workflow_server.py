import pytest
from fastmcp import Client
from types import SimpleNamespace
import mainframe_workflow_mcp.server as server
from mainframe_workflow_mcp.clients.zowe_sdk import ZoweSdkMainframeClient
from mainframe_workflow_mcp.db import ActionLogStore

class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, call):
        self.calls.append(call)
        return {"status": "ok", "data": {"echo": call["input"]}}

@pytest.mark.anyio
async def test_zcrafter_tools_are_registered_once_register_is_called(tmp_path, monkeypatch):
    store = ActionLogStore(tmp_path / "state.db")
    monkeypatch.setattr(server, "_store", store)
    server.register_zcrafter_tools(server.mcp, lambda: RecordingExecutor())

    async with Client(server.mcp) as client:
        tools = {t.name for t in await client.list_tools()}

    assert "dataset.read" in tools
    assert "member.patch" in tools
    store.close()

def _fake_creds(**overrides):
    base = dict(
        host="xplore.example.com", port=10443, user="IBMUSER", password="secret",
        protocol="https", reject_unauthorized=False, base_path=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _clear_connection_cache():
    server._connection_cache.clear()
    yield
    server._connection_cache.clear()


def test_get_executor_for_request_reuses_cached_executor_for_same_connection(monkeypatch):
    monkeypatch.setattr(server, "resolve_from_request_headers", lambda: ("conn-1", _fake_creds()))
    first = server.get_executor_for_request()
    second = server.get_executor_for_request()
    assert first is second


def test_get_executor_for_request_builds_distinct_executors_per_connection(monkeypatch):
    calls = {"conn-a": _fake_creds(host="a.example.com"), "conn-b": _fake_creds(host="b.example.com")}
    current = {"id": "conn-a"}
    monkeypatch.setattr(server, "resolve_from_request_headers", lambda: (current["id"], calls[current["id"]]))

    exec_a = server.get_executor_for_request()
    current["id"] = "conn-b"
    exec_b = server.get_executor_for_request()

    assert exec_a is not exec_b
    assert isinstance(exec_a.client, ZoweSdkMainframeClient)
    assert isinstance(exec_b.client, ZoweSdkMainframeClient)


def test_get_executor_for_request_evicts_least_recently_used_beyond_cache_limit(monkeypatch):
    creds_by_id = {}
    current = {"id": None}
    monkeypatch.setattr(server, "resolve_from_request_headers", lambda: (current["id"], creds_by_id[current["id"]]))
    monkeypatch.setattr(server, "_MAX_CACHED_CONNECTIONS", 2)

    for conn_id in ("conn-1", "conn-2", "conn-3"):
        creds_by_id[conn_id] = _fake_creds(host=f"{conn_id}.example.com")
        current["id"] = conn_id
        server.get_executor_for_request()

    assert "conn-1" not in server._connection_cache  # evicted first, over the limit of 2
    assert "conn-2" in server._connection_cache
    assert "conn-3" in server._connection_cache


def test_build_executor_uses_configured_zowe_profile(monkeypatch):
    monkeypatch.setattr(server.config, "ZOWE_PROFILE", "myprofile")
    monkeypatch.setattr(server.config, "HTTP_TIMEOUT_SECONDS", 30.0)
    monkeypatch.setattr(server.config, "APIML_BASE_PATH", "")
    monkeypatch.setattr(
        server,
        "resolve_credentials",
        lambda profile=None: SimpleNamespace(
            host="example.com",
            port=10443,
            user="IBMUSER",
            password="secret",
            protocol="https",
            reject_unauthorized=False,
            base_path=None,
        ),
    )
    executor = server.build_executor()
    assert isinstance(executor.client, ZoweSdkMainframeClient)
    assert executor.client.profile_name == "myprofile"
