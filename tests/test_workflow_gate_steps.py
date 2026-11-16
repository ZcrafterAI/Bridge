"""An approved plan unlocks its own steps and nothing else."""
import pytest
from fastmcp import Client, FastMCP
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.proxy import register_zcrafter_tools
from mainframe_workflow_mcp.requests import RequestManager


class RecordingExecutor:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.fail = fail

    async def execute(self, call):
        self.calls.append(call)
        if self.fail:
            return {"status": "error", "error": {"code": "TOOL_FAILED", "message": "z/OSMF said no"}}
        return {"status": "ok", "data": {}}


@pytest.fixture
def manager(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    yield RequestManager(store)
    store.close()


def _approved(manager, steps):
    request_id = manager.start_request("a")["request_id"]
    manager.draft_spec(request_id, "spec")
    manager.approve_spec(request_id)
    manager.draft_plan(request_id, "plan", steps)
    manager.approve_plan(request_id)
    return request_id


async def _call(mcp, tool, args):
    async with Client(mcp) as client:
        return (await client.call_tool(tool, args)).data


@pytest.mark.anyio
async def test_a_change_the_plan_never_listed_is_refused(manager):
    mcp, executor = FastMCP("t"), RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _approved(manager, [{"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "HELLO"}}])

    result = await _call(mcp, "dataset.delete", {"dataset": "HLQ.PROD.PAYROLL", "request_id": request_id})

    assert result["error"]["code"] == "STEP_NOT_IN_PLAN"
    assert result["error"]["stepsRemaining"] == ["member.write HLQ.SRC(HELLO)"]
    assert executor.calls == []


@pytest.mark.anyio
async def test_a_plan_with_no_steps_can_change_nothing(manager):
    mcp, executor = FastMCP("t"), RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _approved(manager, None)

    result = await _call(mcp, "member.write", {
        "dataset": "HLQ.SRC", "member": "HELLO", "content": "x", "request_id": request_id,
    })

    assert result["error"]["code"] == "STEP_NOT_IN_PLAN"
    assert executor.calls == []


@pytest.mark.anyio
async def test_a_step_runs_once_unless_the_plan_says_more(manager):
    mcp, executor = FastMCP("t"), RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _approved(manager, [
        {"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}},
        {"tool": "job.submit", "args": {"dataset": "HLQ.JCL(RUN)"}, "times": 2},
    ])
    delete = {"dataset": "HLQ.OLD", "request_id": request_id}
    submit = {"dataset": "HLQ.JCL(RUN)", "request_id": request_id}

    assert (await _call(mcp, "dataset.delete", delete))["status"] == "ok"
    assert (await _call(mcp, "dataset.delete", delete))["error"]["code"] == "STEP_NOT_IN_PLAN"
    assert (await _call(mcp, "job.submit", submit))["status"] == "ok"
    assert (await _call(mcp, "job.submit", submit))["status"] == "ok"
    assert (await _call(mcp, "job.submit", submit))["error"]["code"] == "STEP_NOT_IN_PLAN"
    assert len(executor.calls) == 3
    assert manager.get_request_status(request_id)["steps_remaining"] == []


@pytest.mark.anyio
async def test_a_failed_call_does_not_use_up_its_step(manager):
    mcp, executor = FastMCP("t"), RecordingExecutor(fail=True)
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _approved(manager, [{"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}}])
    call = {"dataset": "HLQ.OLD", "request_id": request_id}

    assert (await _call(mcp, "dataset.delete", call))["error"]["code"] == "TOOL_FAILED"
    executor.fail = False
    assert (await _call(mcp, "dataset.delete", call))["status"] == "ok"


@pytest.mark.anyio
async def test_content_the_person_approved_cannot_be_swapped(manager):
    mcp, executor = FastMCP("t"), RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _approved(manager, [
        {"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "A", "content": "SAFE\n"}},
    ])
    base = {"dataset": "HLQ.SRC", "member": "A", "request_id": request_id}

    assert (await _call(mcp, "member.write", {**base, "content": "OTHER\n"}))["error"]["code"] == "STEP_NOT_IN_PLAN"
    assert (await _call(mcp, "member.write", {**base, "content": "SAFE\n"}))["status"] == "ok"
    assert executor.calls[0]["input"]["content"] == "SAFE\n"


@pytest.mark.anyio
async def test_an_exact_command_is_what_runs(manager):
    mcp, executor = FastMCP("t"), RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    request_id = _approved(manager, [{"tool": "console.command", "args": {"command": "D A,L"}}])

    refused = await _call(mcp, "console.command", {"command": "Z EOD", "request_id": request_id})
    assert refused["error"]["code"] == "STEP_NOT_IN_PLAN"
    assert (await _call(mcp, "console.command", {"command": "D A,L", "request_id": request_id}))["status"] == "ok"


@pytest.mark.anyio
async def test_editing_the_plan_takes_the_steps_away_until_it_is_approved_again(manager):
    mcp, executor = FastMCP("t"), RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor)
    steps = [{"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}}]
    request_id = _approved(manager, steps)
    manager.draft_plan(request_id, "a wider plan", [*steps, {"tool": "dataset.delete", "args": {"dataset": "HLQ.NEW"}}])

    result = await _call(mcp, "dataset.delete", {"dataset": "HLQ.NEW", "request_id": request_id})
    assert result["error"]["code"] == "PLAN_NOT_APPROVED"
    assert executor.calls == []


@pytest.mark.anyio
async def test_a_protected_dataset_is_refused_even_with_a_matching_step(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    # A plan approved before the pattern was protected must not get through either.
    manager = RequestManager(store)
    mcp, executor = FastMCP("t"), RecordingExecutor()
    register_zcrafter_tools(mcp, manager, executor, protected=["*.PROD.**"])
    request_id = _approved(manager, [{"tool": "dataset.delete", "args": {"dataset": "PAY.PROD.MASTER"}}])

    result = await _call(mcp, "dataset.delete", {"dataset": "PAY.PROD.MASTER", "request_id": request_id})

    assert result["error"]["code"] == "PROTECTED_DATASET"
    assert executor.calls == []
    store.close()


@pytest.mark.anyio
async def test_a_read_only_server_offers_no_tool_that_changes_anything(manager):
    mcp = FastMCP("t")
    register_zcrafter_tools(mcp, manager, RecordingExecutor(), read_only=True)

    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert "member.read" in tools and "uss.read" in tools and "tso.query" in tools
    for name in ("member.write", "dataset.delete", "job.submit", "tso.command", "console.command", "uss.write"):
        assert name not in tools
    assert all(tool.annotations.read_only_hint for tool in tools.values())


@pytest.mark.anyio
async def test_tools_tell_the_client_whether_they_read_or_destroy(manager):
    mcp = FastMCP("t")
    register_zcrafter_tools(mcp, manager, RecordingExecutor())

    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert tools["dataset.list"].annotations.read_only_hint is True
    assert tools["dataset.delete"].annotations.read_only_hint is False
    assert tools["dataset.delete"].annotations.destructive_hint is True
    assert tools["dataset.create"].annotations.destructive_hint is False
    # profileName is never required: the server is bound to one profile.
    assert all("profileName" not in tool.input_schema.get("required", []) for tool in tools.values())
