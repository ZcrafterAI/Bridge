"""Demo mode: the real z/OSMF client, over HTTP, against the pretend mainframe. And the
zcrafter-bridge command."""
import io
import os

import pytest
from mainframe_workflow_mcp import cli
from mainframe_workflow_mcp.clients.zowe_sdk import ZoweSdkMainframeClient
from mainframe_workflow_mcp.demo import start_demo_mainframe


@pytest.fixture
def client():
    server, port = start_demo_mainframe()
    yield ZoweSdkMainframeClient(
        "default",
        {"host_url": f"127.0.0.1:{port}", "user": "IBMUSER", "password": "demo",
         "ssl_verification": False, "protocol": "http"},
        timeout_seconds=10,
    )
    server.shutdown()
    server.server_close()


@pytest.mark.anyio
async def test_reading_the_pretend_mainframe(client):
    assert (await client.verify_connection({}))["zosVersion"] == "04.29.00"
    names = [d["name"] for d in (await client.list_datasets({"pattern": "IBMUSER.DEMO.**"}))["dataSets"]]
    assert names == ["IBMUSER.DEMO.COBOL", "IBMUSER.DEMO.JCL", "IBMUSER.DEMO.TIMECARD"]
    members = (await client.list_members({"dataset": "IBMUSER.DEMO.COBOL"}))["members"]
    assert [m["name"] for m in members] == ["HELLO", "PAYCALC"]
    source = await client.read_member({"dataset": "IBMUSER.DEMO.COBOL", "member": "PAYCALC"})
    assert "COMPUTE WS-PAY" in source["content"]
    found = await client.search_members({"dataset": "IBMUSER.DEMO.COBOL", "searchString": "TC-HOURS"})
    assert found["matches"][0]["member"] == "PAYCALC"
    assert (await client.list_systems({}))["systems"][0]["sysplex"] == "DEMOPLEX"
    log = await client.read_uss({"path": "/u/ibmuser/payroll.log", "searchText": "S0C7"})
    assert "ERROR S0C7 in step CALC" in log["content"]
    assert [e["name"] for e in (await client.list_uss({"path": "/u/ibmuser"}))["entries"]] == ["notes.txt", "payroll.log"]
    assert "IBMUSER.DEMO.COBOL" in (await client.tso_query({"command": "LISTCAT LEVEL('IBMUSER')"}))["content"]
    assert (await client.console_command({"command": "D A,L"}))["content"].startswith("IEE114I")


@pytest.mark.anyio
async def test_the_demo_story_find_the_abend_fix_it_run_it_again(client):
    failed = (await client.list_failed_jobs({}))["failed"]
    assert [(j["jobName"], j["returnCode"]) for j in failed] == [("PAYRUN", "ABEND S0C7")]
    job = {"jobId": failed[0]["jobId"]}
    steps = await client.get_job_steps(job)
    assert steps["steps"] == [{"number": 1, "step": "CALC", "program": "PAYCALC", "completion": "ABEND S0C7"}]
    output = await client.get_job_output({**job, "searchText": "COMPLETION CODE"})
    assert "0C7" in output["content"]
    assert "PGM=PAYCALC" in (await client.get_job_jcl(job))["content"]

    # Submitting again without a fix abends again.
    again = await client.submit_job({"dataset": "IBMUSER.DEMO.JCL(PAYRUN)"})
    assert (await client.get_job_status({"jobId": again["jobId"]}))["returnCode"] == "ABEND S0C7"

    source = (await client.read_member({"dataset": "IBMUSER.DEMO.COBOL", "member": "PAYCALC"}))["content"]
    fixed = source.replace(
        "           COMPUTE WS-PAY", "           IF WS-HOURS NOT NUMERIC MOVE ZERO TO WS-HOURS.\n           COMPUTE WS-PAY",
    )
    await client.write_member({"dataset": "IBMUSER.DEMO.COBOL", "member": "PAYCALC", "content": fixed})
    rerun = await client.submit_job({"dataset": "IBMUSER.DEMO.JCL(PAYRUN)"})
    status = await client.wait_for_job({"jobId": rerun["jobId"], "attempts": 2, "delayMs": 10})
    assert status["returnCode"] == "CC 0000"


@pytest.mark.anyio
async def test_changes_on_the_pretend_mainframe(client):
    await client.write_uss({"path": "/u/ibmuser/new.txt", "content": "hello\n"})
    assert (await client.read_uss({"path": "/u/ibmuser/new.txt"}))["content"] == "hello\n"
    await client.rename_uss({"path": "/u/ibmuser/new.txt", "newPath": "/u/ibmuser/kept.txt"})
    await client.delete_uss({"path": "/u/ibmuser/kept.txt"})
    assert "kept.txt" not in [e["name"] for e in (await client.list_uss({"path": "/u/ibmuser"}))["entries"]]

    await client.create_dataset({"dataset": "IBMUSER.DEMO.NEW"})
    await client.copy_dataset({"sourceDataset": "IBMUSER.DEMO.COBOL", "sourceMember": "HELLO",
                               "targetDataset": "IBMUSER.DEMO.NEW", "targetMember": "HELLO"})
    assert "HELLO FROM THE DEMO" in (await client.read_member({"dataset": "IBMUSER.DEMO.NEW", "member": "HELLO"}))["content"]
    await client.delete_dataset({"dataset": "IBMUSER.DEMO.NEW"})
    assert (await client.list_datasets({"pattern": "IBMUSER.DEMO.NEW"}))["dataSets"] == []
    job = (await client.list_jobs({"prefix": "PAY*"}))["jobs"][0]
    assert await client.hold_job({"jobId": job["jobId"], "jobName": job["jobName"]}) == {"held": True}
    await client.purge_job({"jobId": job["jobId"], "jobName": job["jobName"]})
    assert (await client.list_jobs({}))["jobs"] == []


def test_version_and_help(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.startswith("zcrafter-bridge ")


def test_install_skill_copies_the_agent_skill(tmp_path):
    assert cli.install_skill(tmp_path) == 0
    text = (tmp_path / "mainframe-workflow" / "SKILL.md").read_text()
    assert "name: mainframe-workflow" in text and "approve_plan" in text


def test_approve_needs_a_person_at_a_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    assert cli.main(["approve"]) == 2


def test_demo_mode_points_at_the_pretend_mainframe_and_a_store_of_its_own(monkeypatch, capsys):
    monkeypatch.delenv("MAINFRAME_WORKFLOW_DB_PATH")
    monkeypatch.delenv("MAINFRAME_WORKFLOW_ARCHIVE_DIR")
    cli._start_demo()
    assert os.environ["ZOWE_OPT_HOST"] == "127.0.0.1" and os.environ["ZOWE_OPT_PROTOCOL"] == "http"
    assert "zcrafter-bridge-demo-" in os.environ["MAINFRAME_WORKFLOW_DB_PATH"]
    assert "No real mainframe is contacted" in capsys.readouterr().err
    for name in ("MAINFRAME_WORKFLOW_DB_PATH", "MAINFRAME_WORKFLOW_ARCHIVE_DIR", "ZOWE_OPT_HOST", "ZOWE_OPT_PORT",
                 "ZOWE_OPT_USER", "ZOWE_OPT_PASSWORD", "ZOWE_OPT_PROTOCOL", "ZOWE_OPT_REJECT_UNAUTHORIZED"):
        monkeypatch.delenv(name, raising=False)  # do not leak into other tests
