"""The approve tools ask a person. The agent calling them approves nothing."""
import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
import mainframe_workflow_mcp.server as server
from mainframe_workflow_mcp.approval import ApprovalBroker
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager


# "auto" speaks the 2026-07-28 protocol, where the tool returns "input required" and is called
# again with the answer; "legacy" is the older handshake, where the server asks during the call.
ERAS = ["auto", "legacy"]


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """The real server tools over a throwaway store, with a broker a test can configure."""
    store = RequestStore(tmp_path / "state.db")
    monkeypatch.setattr(server, "_store", store)
    monkeypatch.setattr(server, "_request_manager", RequestManager(store))
    opened: list[str] = []

    def use(mode: str, wait_seconds: float = 0.05) -> list[str]:
        monkeypatch.setattr(server, "_broker", ApprovalBroker(
            store, mode=mode, wait_seconds=wait_seconds, open_browser=opened.append,
            log=lambda line: None, poll_seconds=0.01,
        ))
        return opened

    yield use
    store.close()


def _answer(action, decision=None):
    seen: list[str] = []

    async def handler(message, response_type, params, context):
        seen.append(message)
        return ElicitResult(action=action, content={"value": decision} if decision else None)

    return handler, seen


async def _to_plan_draft(client):
    request_id = (await client.call_tool("start_request", {"raw_request": "delete HLQ.OLD"})).data["request_id"]
    await client.call_tool("draft_spec", {"request_id": request_id, "content": "Delete HLQ.OLD."})
    return request_id


@pytest.mark.anyio
@pytest.mark.parametrize("era", ERAS)
async def test_with_no_person_answering_nothing_is_approved(wired, era):
    opened = wired("auto")
    async with Client(server.mcp, mode=era) as client:  # a client with no prompt of its own
        request_id = await _to_plan_draft(client)
        result = (await client.call_tool("approve_spec", {"request_id": request_id})).data
        status = (await client.call_tool("get_request_status", {"request_id": request_id})).data

    assert result["status"] == "WAITING_FOR_PERSON"
    assert status["phase"] == "SPEC_DRAFT" and status["spec_approved_version"] is None
    assert len(opened) == 1
    # The agent is told to wait, never where the page is.
    assert "127.0.0.1" not in str(result) and "?t=" not in str(result)


@pytest.mark.anyio
@pytest.mark.parametrize("era", ERAS)
async def test_the_persons_yes_in_the_client_prompt_approves(wired, era):
    opened = wired("auto")
    handler, seen = _answer("accept", "Approve")
    async with Client(server.mcp, elicitation_handler=handler, mode=era) as client:
        request_id = await _to_plan_draft(client)
        spec = (await client.call_tool("approve_spec", {"request_id": request_id})).data
        await client.call_tool("draft_plan", {
            "request_id": request_id, "content": "Delete it.",
            "steps": [{"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}}],
        })
        plan = (await client.call_tool("approve_plan", {"request_id": request_id})).data

    assert spec["phase"] == "SPEC_APPROVED" and spec["approved_via"] == "the AI client's prompt"
    assert plan["phase"] == "PLAN_APPROVED"
    assert opened == []  # the client asked, so no page was needed
    assert "Approve this spec" in seen[0] and "Delete HLQ.OLD." in seen[0]
    assert "1. dataset.delete  HLQ.OLD" in seen[1]


@pytest.mark.anyio
@pytest.mark.parametrize("era", ERAS)
@pytest.mark.parametrize("action, decision", [("accept", "Reject"), ("decline", None)])
async def test_the_persons_no_rejects(wired, action, decision, era):
    wired("auto")
    handler, _ = _answer(action, decision)
    async with Client(server.mcp, elicitation_handler=handler, mode=era) as client:
        request_id = await _to_plan_draft(client)
        result = (await client.call_tool("approve_spec", {"request_id": request_id})).data
        again = (await client.call_tool("approve_spec", {"request_id": request_id})).data
        status = (await client.call_tool("get_request_status", {"request_id": request_id})).data

    assert result["status"] == "REJECTED" and again["status"] == "REJECTED"
    assert status["phase"] == "SPEC_DRAFT"


@pytest.mark.anyio
@pytest.mark.parametrize("era", ERAS)
async def test_a_dismissed_prompt_is_not_a_yes(wired, era):
    opened = wired("auto")
    handler, _ = _answer("cancel")
    async with Client(server.mcp, elicitation_handler=handler, mode=era) as client:
        request_id = await _to_plan_draft(client)
        result = (await client.call_tool("approve_spec", {"request_id": request_id})).data

    assert result["status"] == "WAITING_FOR_PERSON"
    assert len(opened) == 1  # asked another way instead of guessing


@pytest.mark.anyio
async def test_bad_steps_come_back_as_an_error_the_agent_can_fix(wired):
    wired("unsafe-agent")
    async with Client(server.mcp) as client:
        request_id = await _to_plan_draft(client)
        await client.call_tool("approve_spec", {"request_id": request_id})
        result = (await client.call_tool("draft_plan", {
            "request_id": request_id, "content": "x",
            "steps": [{"tool": "dataset.delete", "args": {}}],
        })).data
        status = (await client.call_tool("get_request_status", {"request_id": request_id})).data

    assert result["error"]["code"] == "INVALID_PLAN_STEPS"
    assert "must name dataset" in result["error"]["message"]
    assert status["phase"] == "SPEC_APPROVED" and status["latest_plan"] is None


@pytest.mark.anyio
async def test_status_shows_the_plans_steps(wired):
    wired("unsafe-agent")
    steps = [{"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}}]
    async with Client(server.mcp) as client:
        request_id = await _to_plan_draft(client)
        await client.call_tool("approve_spec", {"request_id": request_id})
        await client.call_tool("draft_plan", {"request_id": request_id, "content": "x", "steps": steps})
        await client.call_tool("approve_plan", {"request_id": request_id})
        status = (await client.call_tool("get_request_status", {"request_id": request_id})).data

    assert status["latest_plan"]["steps"] == [{**steps[0], "times": 1}]
    assert status["steps_remaining"] == ["dataset.delete HLQ.OLD"]


@pytest.mark.anyio
async def test_the_server_starts_and_explains_a_missing_profile(tmp_path, monkeypatch):
    from mainframe_workflow_mcp.credentials import CredentialResolutionError

    def no_profile(profile=None):
        raise CredentialResolutionError('z/OSMF profile "default" not found')

    monkeypatch.setattr(server, "resolve_credentials", no_profile)
    store = RequestStore(tmp_path / "state.db")
    monkeypatch.setattr(server, "_store", store)
    executor = server.build_executor()  # used to raise here, before any tool could answer

    profiles = await executor.execute({"id": "1", "name": "profile.list", "input": {}})
    listing = await executor.execute({"id": "2", "name": "dataset.list", "input": {"pattern": "HLQ.**"}})

    assert profiles["status"] == "ok"
    assert listing["status"] == "error"
    assert 'profile "default" not found' in listing["error"]["message"]
    assert "zowe zosmf check status" in listing["error"]["message"]
