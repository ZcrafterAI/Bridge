import pytest
from fastmcp import FastMCP, Client
from mainframe_workflow_mcp._toolbox import list_tool_definitions
import mainframe_workflow_mcp.proxy as proxy_module
from mainframe_workflow_mcp.proxy import register_zcrafter_tools

class FakeExecutor:
    """Stands in for zcrafter's LocalToolExecutor so these tests don't need a
    real Zowe CLI / mainframe connection — same boundary zcrafter's own test
    suite mocks (client/executor), per their wiki's 'How To Add A New Tool'."""
    def __init__(self):
        self.calls = []

    async def execute(self, call):
        self.calls.append(call)
        return {"status": "ok", "data": {"echo": call["input"]}}

@pytest.mark.anyio
async def test_every_read_only_zcrafter_tool_gets_registered_with_matching_required_fields():
    mcp = FastMCP("test")
    executor = FakeExecutor()
    register_zcrafter_tools(mcp, executor)

    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}

    for definition in list_tool_definitions():
        if definition["approval"] == "required":
            continue
        assert definition["name"] in tools, f"{definition['name']} was not registered"
        exposed_required = set(tools[definition["name"]].inputSchema.get("required", []))
        assert exposed_required == set(definition["inputSchema"].get("required", []))

@pytest.mark.anyio
async def test_read_only_tool_call_reaches_executor():
    mcp = FastMCP("test")
    executor = FakeExecutor()
    register_zcrafter_tools(mcp, executor)

    call_input = {"profileName": "default", "pattern": "IBMUSER.**"}
    async with Client(mcp) as client:
        result = await client.call_tool("dataset.list", call_input)

    assert result.data["status"] == "ok"
    echoed = result.data["data"]["echo"]
    assert echoed["profileName"] == "default"
    assert echoed["pattern"] == "IBMUSER.**"
    assert executor.calls[0]["name"] == "dataset.list"

@pytest.mark.anyio
async def test_catalog_tool_zowe_tools_search_is_registered():
    mcp = FastMCP("test")
    executor = FakeExecutor()
    register_zcrafter_tools(mcp, executor)

    async with Client(mcp) as client:
        tools = {t.name for t in await client.list_tools()}

    assert "zowe.tools.search" in tools
    assert "zowe.capabilities.list" in tools

def test_register_zcrafter_tools_raises_on_unknown_approval_value(monkeypatch):
    fake_definition = {
        "name": "fake.tool",
        "description": "fake",
        "approval": "something_else",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    }
    monkeypatch.setattr(proxy_module, "list_tool_definitions", lambda: [fake_definition])

    mcp = FastMCP("test")
    executor = FakeExecutor()
    with pytest.raises(ValueError, match="Unknown approval value"):
        register_zcrafter_tools(mcp, executor)

@pytest.mark.anyio
async def test_integer_argument_for_number_typed_schema_stays_int(monkeypatch):
    fake_definition = {
        "name": "fake.number.tool",
        "description": "fake",
        "approval": "never",
        "inputSchema": {
            "type": "object",
            "properties": {"spoolId": {"type": "number"}},
            "required": ["spoolId"],
        },
    }
    monkeypatch.setattr(proxy_module, "list_tool_definitions", lambda: [fake_definition])

    mcp = FastMCP("test")
    executor = FakeExecutor()
    register_zcrafter_tools(mcp, executor)

    async with Client(mcp) as client:
        await client.call_tool("fake.number.tool", {"spoolId": 2})

    received = executor.calls[0]["input"]["spoolId"]
    assert received == 2
    assert type(received) is int
