"""A person's yes: the approval broker, its page, and the terminal path."""
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest
from mainframe_workflow_mcp.approval import ApprovalBroker, approval_subject, approval_text
from mainframe_workflow_mcp.db import RequestStore
from mainframe_workflow_mcp.requests import RequestManager

STEPS = [
    {"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "PAYCALC"}},
    {"tool": "dataset.delete", "args": {"dataset": "HLQ.OLD"}},
]


@pytest.fixture
def store(tmp_path):
    store = RequestStore(tmp_path / "state.db")
    yield store
    store.close()


def _plan_draft(store, steps=STEPS):
    manager = RequestManager(store)
    request_id = manager.start_request("Fix <PAYCALC> & tidy up")["request_id"]
    manager.draft_spec(request_id, "Fix the S0C7 in PAYCALC.")
    manager.approve_spec(request_id)
    version = manager.draft_plan(request_id, "Rewrite PAYCALC, delete HLQ.OLD.", steps)["version"]
    return manager, request_id, version


def _broker(store, opened, **kwargs):
    return ApprovalBroker(
        store, open_browser=opened.append, log=lambda line: None, poll_seconds=0.02, **kwargs,
    )


def _get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.read().decode()


def _post(url, token, decision):
    data = urllib.parse.urlencode({"t": token, "decision": decision}).encode()
    with urllib.request.urlopen(urllib.request.Request(url.split("?")[0], data=data)) as response:
        return response.status, response.read().decode()


@pytest.mark.anyio
async def test_with_no_client_prompt_the_person_approves_on_a_page(store):
    manager, request_id, version = _plan_draft(store)
    opened: list[str] = []
    broker = _broker(store, opened, mode="browser", wait_seconds=0.1)

    first = await broker.ask(None, request_id, "plan", version)
    assert first.status == "waiting"
    assert len(opened) == 1
    url = opened[0]
    token = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["t"][0]
    # Nothing the agent is told carries the page's address or its token.
    assert token not in first.detail and "127.0.0.1" not in first.detail

    status, page = _get(url)
    assert status == 200
    assert "Approve this plan?" in page
    assert "HLQ.SRC(PAYCALC)" in page and "HLQ.OLD" in page
    assert "The exact content is not fixed by this plan." in page
    assert "Fix &lt;PAYCALC&gt; &amp; tidy up" in page  # what was asked is shown as text, not markup

    status, done = _post(url, token, "approve")
    assert status == 200 and "Approved" in done

    second = await broker.ask(None, request_id, "plan", version)
    assert second.status == "approved" and second.via == "the approval page"
    assert len(opened) == 1  # the page is opened once, not on every ask
    broker.close()


@pytest.mark.anyio
async def test_the_page_needs_its_token(store):
    _, request_id, version = _plan_draft(store)
    opened: list[str] = []
    broker = _broker(store, opened, mode="browser", wait_seconds=0.05)
    await broker.ask(None, request_id, "plan", version)
    base = opened[0].split("?")[0]

    for bad in (base, base + "?t=wrong"):
        with pytest.raises(urllib.error.HTTPError) as error:
            _get(bad)
        assert error.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as error:
        _post(base, "wrong", "approve")
    assert error.value.code == 404
    assert (await broker.ask(None, request_id, "plan", version)).status == "waiting"
    broker.close()


@pytest.mark.anyio
async def test_the_page_answers_only_to_this_machine(store):
    _, request_id, version = _plan_draft(store)
    opened: list[str] = []
    broker = _broker(store, opened, mode="browser", wait_seconds=0.05)
    await broker.ask(None, request_id, "plan", version)
    request = urllib.request.Request(opened[0], headers={"Host": "evil.example:80"})
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 403
    broker.close()


@pytest.mark.anyio
async def test_a_rejection_stands_for_that_revision(store):
    manager, request_id, version = _plan_draft(store)
    opened: list[str] = []
    broker = _broker(store, opened, mode="browser", wait_seconds=0.05)
    await broker.ask(None, request_id, "plan", version)
    token = urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query)["t"][0]
    _post(opened[0], token, "reject")

    assert (await broker.ask(None, request_id, "plan", version)).status == "rejected"
    assert len(opened) == 1  # asking again does not reopen the question
    # A new revision is a new question.
    new_version = manager.draft_plan(request_id, "A smaller plan.", STEPS[:1])["version"]
    assert (await broker.ask(None, request_id, "plan", new_version)).status == "waiting"
    assert len(opened) == 2
    broker.close()


@pytest.mark.anyio
async def test_a_page_answered_twice_keeps_the_first_answer(store):
    _, request_id, version = _plan_draft(store)
    opened: list[str] = []
    broker = _broker(store, opened, mode="browser", wait_seconds=0.05)
    await broker.ask(None, request_id, "plan", version)
    token = urllib.parse.parse_qs(urllib.parse.urlparse(opened[0]).query)["t"][0]
    _post(opened[0], token, "reject")
    _, again = _post(opened[0], token, "approve")
    assert "answered before" in again
    assert (await broker.ask(None, request_id, "plan", version)).status == "rejected"
    broker.close()


@pytest.mark.anyio
async def test_terminal_mode_opens_nothing_and_takes_the_answer_from_the_store(store):
    _, request_id, version = _plan_draft(store)
    opened: list[str] = []
    broker = _broker(store, opened, mode="terminal", wait_seconds=0.05)
    assert (await broker.ask(None, request_id, "plan", version)).status == "waiting"
    assert opened == []

    pending = store.list_pending_approvals()
    assert [(row["request_id"], row["kind"], row["version"]) for row in pending] == [(request_id, "plan", version)]
    # What `python -m mainframe_workflow_mcp.approve` does once the person types y.
    assert store.decide_approval(pending[0]["id"], "APPROVED", "the terminal", now="2026-01-01T00:00:00+00:00")

    decision = await broker.ask(None, request_id, "plan", version)
    assert (decision.status, decision.via) == ("approved", "the terminal")


def test_the_terminal_command_refuses_to_run_without_a_person(monkeypatch, capsys):
    import io
    from mainframe_workflow_mcp import approve

    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))  # a pipe, as an agent's shell would give it
    assert approve.main() == 2
    assert "by a person" in capsys.readouterr().err


@pytest.mark.anyio
async def test_unsafe_agent_mode_is_the_only_one_that_asks_nobody(store):
    _, request_id, version = _plan_draft(store)
    opened: list[str] = []
    decision = await _broker(store, opened, mode="unsafe-agent").ask(None, request_id, "plan", version)
    assert decision.status == "approved" and "nobody was asked" in decision.via
    assert opened == []
    with pytest.raises(ValueError, match="Unknown approval mode"):
        ApprovalBroker(store, mode="trust-me")


def test_what_the_person_reads(store):
    _, request_id, version = _plan_draft(store, [
        {"tool": "tso.command", "args": {"command": "DELETE 'HLQ.OLD'"}},
        {"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "A", "content": "NEW LINE\n"}},
    ])
    text = approval_text(approval_subject(store, request_id, "plan", version))
    assert "Approve this plan" in text
    assert "Rewrite PAYCALC, delete HLQ.OLD." in text
    assert "1. tso.command  DELETE 'HLQ.OLD'" in text
    assert "content: fixed by this plan" in text
    assert re.search(r"Changes this plan allows, and nothing else", text)
