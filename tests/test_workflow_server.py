import pytest
from fastmcp import Client
from types import SimpleNamespace
import mainframe_workflow_mcp.server as server
from mainframe_workflow_mcp.clients.zowe_sdk import ZoweSdkMainframeClient
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager

class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, call):
        self.calls.append(call)
        return {"status": "ok", "data": {"echo": call["input"]}}

@pytest.mark.anyio
async def test_state_tools_are_registered_and_reachable_through_real_client(tmp_path, monkeypatch):
    store = RequestStore(tmp_path / "state.db")
    monkeypatch.setattr(server, "_store", store)
    monkeypatch.setattr(server, "_request_manager", RequestManager(store))

    async with Client(server.mcp) as client:
        started = await client.call_tool("start_request", {"raw_request": "add a field to CUSTREC"})
        request_id = started.data["request_id"]

        spec_result = await client.call_tool("draft_spec", {"request_id": request_id, "content": "# Spec"})
        assert spec_result.data["phase"] == "SPEC_DRAFT"

        await client.call_tool("approve_spec", {"request_id": request_id})
        await client.call_tool("draft_plan", {"request_id": request_id, "content": "# Plan"})
        await client.call_tool("approve_plan", {"request_id": request_id})

        status = await client.call_tool("get_request_status", {"request_id": request_id})
        assert status.data["phase"] == "PLAN_APPROVED"

    store.close()

@pytest.mark.anyio
async def test_zcrafter_tools_are_registered_once_register_is_called(tmp_path, monkeypatch):
    store = RequestStore(tmp_path / "state.db")
    monkeypatch.setattr(server, "_store", store)
    monkeypatch.setattr(server, "_request_manager", RequestManager(store))
    server.register_zcrafter_tools(server.mcp, server._request_manager, RecordingExecutor())

    async with Client(server.mcp) as client:
        tools = {t.name for t in await client.list_tools()}

    assert "dataset.read" in tools
    assert "member.patch" in tools
    store.close()

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
            reject_unauthorized=False,
            base_path=None,
        ),
    )
    executor = server.build_executor()
    assert isinstance(executor.client, ZoweSdkMainframeClient)
    assert executor.client.profile_name == "myprofile"
