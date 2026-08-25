import pytest
from fastmcp import FastMCP, Client
from mainframe_workflow_mcp._toolbox import list_tool_definitions
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager
from mainframe_workflow_mcp.proxy import register_zcrafter_tools

class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, call):
        self.calls.append(call)
        return {"status": "ok", "data": {"echo": call["input"]}}

@pytest.fixture
def manager(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    yield RequestManager(store)
    store.close()

def _to_plan_approved(manager, raw="a"):
    request_id = manager.start_request(raw)["request_id"]
    manager.draft_spec(request_id, "spec")
    manager.approve_spec(request_id)
    manager.draft_plan(request_id, "plan")
    manager.approve_plan(request_id)
    return request_id

@pytest.mark.anyio
async def test_mutating_tool_requires_request_id_in_schema(manager):
    mcp = FastMCP("test")
    register_zcrafter_tools(mcp, manager, RecordingExecutor())

    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}

    assert "request_id" in tools["member.patch"].inputSchema["properties"]
    assert "request_id" in tools["member.patch"].inputSchema["required"]

@pytest.mark.anyio
async def test_mutating_tool_blocked_before_plan_approved(manager):
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = manager.start_request("a")["request_id"]

    async with Client(mcp) as client:
        result = await client.call_tool(
            "dataset.delete", {"profileName": "default", "dataset": "HLQ.OLD", "request_id": request_id}
        )

    assert result.data["status"] == "error"
    assert result.data["error"]["code"] == "PLAN_NOT_APPROVED"
    assert executor.calls == []

@pytest.mark.anyio
async def test_mutating_tool_blocked_for_unknown_request_id(manager):
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "dataset.delete", {"profileName": "default", "dataset": "HLQ.OLD", "request_id": "does-not-exist"}
        )

    assert result.data["status"] == "error"
    assert result.data["error"]["code"] == "REQUEST_NOT_FOUND"
    assert executor.calls == []

@pytest.mark.anyio
async def test_mutating_tool_succeeds_after_plan_approved_and_flips_to_executing(manager):
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _to_plan_approved(manager)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "member.patch",
            {
                "profileName": "default",
                "dataset": "HLQ.SRC",
                "member": "PROG1",
                "unifiedDiff": "...",
                "request_id": request_id,
            },
        )

    assert result.data["status"] == "ok"
    assert manager.get_request(request_id)["phase"] == "EXECUTING"
    # request_id must never reach zcrafter's executor as tool input.
    assert "request_id" not in executor.calls[0]["input"]

@pytest.mark.anyio
async def test_approved_flag_is_always_server_derived_not_model_controlled(manager):
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _to_plan_approved(manager)

    async with Client(mcp) as client:
        await client.call_tool(
            "member.patch",
            {
                "profileName": "default",
                "dataset": "HLQ.SRC",
                "member": "PROG1",
                "unifiedDiff": "...",
                "request_id": request_id,
            },
        )

    # There is no "approved" property in member.patch's exposed schema at
    # all, so the model has no field to set it through in the first place;
    # this asserts the server sent approved=True itself.
    assert executor.calls[0]["approved"] is True

@pytest.mark.anyio
async def test_mutating_tool_blocked_when_request_is_completed(manager):
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _to_plan_approved(manager)
    manager.complete_request(request_id)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "dataset.delete", {"profileName": "default", "dataset": "HLQ.OLD", "request_id": request_id}
        )

    assert result.data["status"] == "error"
    assert result.data["error"]["code"] == "REQUEST_NOT_ACTIVE"
    assert executor.calls == []

@pytest.mark.anyio
async def test_mutating_tool_blocked_when_request_is_abandoned(manager):
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = manager.start_request("a")["request_id"]
    manager.cancel_request(request_id, "no longer needed")

    async with Client(mcp) as client:
        result = await client.call_tool(
            "dataset.delete", {"profileName": "default", "dataset": "HLQ.OLD", "request_id": request_id}
        )

    assert result.data["status"] == "error"
    assert result.data["error"]["code"] == "REQUEST_NOT_ACTIVE"
    assert executor.calls == []

@pytest.mark.anyio
async def test_every_mutating_zcrafter_tool_is_registered_and_gated_with_request_id(manager):
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)

    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}

    for definition in list_tool_definitions():
        if definition["approval"] != "required":
            continue
        assert definition["name"] in tools, f"{definition['name']} was not registered"
        schema = tools[definition["name"]].inputSchema
        assert "request_id" in schema.get("properties", {}), (
            f"{definition['name']} is missing request_id in its exposed schema properties"
        )
        assert "request_id" in schema.get("required", []), (
            f"{definition['name']} does not require request_id"
        )
