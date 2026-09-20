import pytest
from fastmcp import FastMCP, Client
from mainframe_workflow_mcp._toolbox import list_tool_definitions
from mainframe_workflow_mcp.proxy import register_zcrafter_tools

class RecordingExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, call):
        self.calls.append(call)
        return {"status": "ok", "data": {"echo": call["input"]}}

@pytest.mark.anyio
async def test_mutating_tool_schema_has_no_request_id():
    mcp = FastMCP("test")
    register_zcrafter_tools(mcp, RecordingExecutor())

    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}

    assert "request_id" not in tools["member.patch"].input_schema.get("properties", {})
    assert "request_id" not in tools["member.patch"].input_schema.get("required", [])

@pytest.mark.anyio
async def test_mutating_tool_is_not_marked_read_only():
    # This is what backend's tool dispatch actually keys off of to decide
    # whether to hit the approval gate -- not the "request_id" schema shape.
    mcp = FastMCP("test")
    register_zcrafter_tools(mcp, RecordingExecutor())

    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}

    assert tools["member.patch"].annotations.read_only_hint is False
    assert tools["member.patch"].annotations.destructive_hint is True

@pytest.mark.anyio
async def test_mutating_tool_call_reaches_executor_directly():
    # Approval gating is backend's job, one hop up (see docs/architecture.md);
    # bridge no longer has a request/spec/plan gate in front of mutating tools.
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, executor)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "dataset.delete", {"profileName": "default", "dataset": "HLQ.OLD"}
        )

    assert result.data["status"] == "ok"
    assert executor.calls[0]["name"] == "dataset.delete"

@pytest.mark.anyio
async def test_approved_flag_is_always_server_derived_not_model_controlled():
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, executor)

    async with Client(mcp) as client:
        await client.call_tool(
            "member.patch",
            {
                "profileName": "default",
                "dataset": "HLQ.SRC",
                "member": "PROG1",
                "unifiedDiff": "...",
            },
        )

    # There is no "approved" property in member.patch's exposed schema at
    # all, so the model has no field to set it through in the first place;
    # this asserts the server sent approved=True itself.
    assert executor.calls[0]["approved"] is True
    assert "approved" not in executor.calls[0]["input"]

@pytest.mark.anyio
async def test_every_mutating_zcrafter_tool_is_registered_with_no_request_id():
    mcp = FastMCP("test")
    executor = RecordingExecutor()
    register_zcrafter_tools(mcp, executor)

    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}

    for definition in list_tool_definitions():
        if definition["approval"] != "required":
            continue
        assert definition["name"] in tools, f"{definition['name']} was not registered"
        schema = tools[definition["name"]].input_schema
        assert "request_id" not in schema.get("properties", {}), (
            f"{definition['name']} should not require request_id anymore"
        )
