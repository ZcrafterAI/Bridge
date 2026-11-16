"""The z/OS UNIX, job-control, TSO, console and system tools: each sends the request the
z/OSMF REST API documents, and reads the answer it documents."""
import json

import pytest
import responses
from mainframe_workflow_mcp.clients import tso
from tests.test_zowe_sdk_client import make_client

FILES = "https://host:10443/zosmf/restfiles/"
JOBS = "https://host:10443/zosmf/restjobs/jobs/"
ROOT = "https://host:10443/zosmf"


def _last(client):
    return client._handler.calls[-1]


# ------------------------------------------------------------ z/OS UNIX files

@pytest.mark.anyio
async def test_uss_list_reads_a_directory():
    client = make_client()
    client._handler.payloads[("GET", FILES + "fs")] = {"items": [
        {"name": ".", "mode": "drwxr-xr-x"}, {"name": "..", "mode": "drwxr-xr-x"},
        {"name": "app.log", "mode": "-rw-r--r--", "size": 120, "user": "IBMUSER", "group": "SYS1", "mtime": "2026-01-02T03:04:05"},
    ]}
    result = await client.list_uss({"path": "/u/ibmuser"})
    assert _last(client)["args"]["params"] == {"path": "/u/ibmuser"}
    assert result == {"path": "/u/ibmuser", "entries": [
        {"name": "app.log", "mode": "-rw-r--r--", "size": 120, "owner": "IBMUSER", "group": "SYS1", "modified": "2026-01-02T03:04:05"},
    ]}


@pytest.mark.anyio
async def test_uss_read_returns_text_and_can_search_it():
    client = make_client()
    client._handler.payloads[("GET", FILES + "fs/u/ibmuser/my%20app.log")] = {"response": "ok\nERROR one\nok\n"}
    result = await client.read_uss({"path": "/u/ibmuser/my app.log", "searchText": "ERROR"})
    assert result["path"] == "/u/ibmuser/my app.log"
    assert "ERROR one" in result["content"] and "ok\nok" not in result["content"]


@pytest.mark.anyio
async def test_uss_write_sends_text():
    client = make_client()
    result = await client.write_uss({"path": "/u/ibmuser/a.txt", "content": "héllo\n"})
    call = _last(client)
    assert (call["method"], call["url"]) == ("PUT", FILES + "fs/u/ibmuser/a.txt")
    assert call["args"]["data"] == "héllo\n".encode("utf-8")
    assert call["args"]["headers"]["X-IBM-Data-Type"] == "text"
    assert result == {"written": True, "path": "/u/ibmuser/a.txt", "bytes": 7}


@pytest.mark.anyio
async def test_uss_create_delete_rename_chmod():
    client = make_client()

    await client.create_uss({"path": "/u/ibmuser/new", "type": "directory"})
    call = _last(client)
    assert (call["method"], call["url"]) == ("POST", FILES + "fs/u/ibmuser/new")
    assert call["args"]["json"] == {"type": "directory", "mode": "rwxr-xr-x"}

    await client.delete_uss({"path": "/u/ibmuser/new", "recursive": True})
    call = _last(client)
    assert (call["method"], call["url"]) == ("DELETE", FILES + "fs/u/ibmuser/new")
    assert call["args"]["headers"]["X-IBM-Option"] == "recursive"

    await client.rename_uss({"path": "/u/ibmuser/a.txt", "newPath": "/u/ibmuser/b.txt"})
    call = _last(client)
    assert (call["method"], call["url"]) == ("PUT", FILES + "fs/u/ibmuser/b.txt")
    assert call["args"]["json"] == {"request": "move", "from": "/u/ibmuser/a.txt"}

    await client.chmod_uss({"path": "/u/ibmuser/b.txt", "mode": "640"})
    assert _last(client)["args"]["json"] == {"request": "chmod", "mode": "640"}


@pytest.mark.anyio
@pytest.mark.parametrize("method, args, message", [
    ("read_uss", {"path": "u/ibmuser/x"}, "absolute"),
    ("read_uss", {"path": "/u/ibmuser/../../etc/x"}, "must not contain"),
    ("delete_uss", {"path": "/u"}, "top-level"),
    ("create_uss", {"path": "/u/ibmuser/x", "type": "socket"}, "file or directory"),
    ("chmod_uss", {"path": "/u/ibmuser/x", "mode": "rwx"}, "octal"),
])
async def test_bad_uss_requests_never_reach_the_mainframe(method, args, message):
    client = make_client()
    with pytest.raises(ValueError, match=message):
        await getattr(client, method)(args)
    assert client._handler.calls == []


# ------------------------------------------------------------ jobs

@pytest.mark.anyio
async def test_job_steps_show_which_step_failed():
    client = make_client()
    client._handler.payloads[("GET", JOBS + "PAYRUN/JOB00042")] = {
        "jobname": "PAYRUN", "jobid": "JOB00042", "status": "OUTPUT", "retcode": "ABEND S0C7",
        "step-data": [
            {"step-number": 1, "step-name": "COMPILE", "program-name": "IGYCRCTL", "completion": "CC 0000"},
            {"step-number": 2, "step-name": "CALC", "program-name": "PAYCALC", "completion": "ABEND S0C7"},
        ],
    }
    result = await client.get_job_steps({"jobId": "JOB00042", "jobName": "PAYRUN"})
    assert _last(client)["args"]["params"] == {"step-data": "Y"}
    assert result["returnCode"] == "ABEND S0C7"
    assert result["steps"][1] == {"number": 2, "step": "CALC", "program": "PAYCALC", "completion": "ABEND S0C7"}


@pytest.mark.anyio
async def test_failed_jobs_keeps_only_the_ones_that_ended_badly():
    client = make_client()
    client._handler.payloads[("GET", JOBS)] = [
        {"jobname": "GOOD", "jobid": "JOB1", "status": "OUTPUT", "retcode": "CC 0000"},
        {"jobname": "WARN", "jobid": "JOB2", "status": "OUTPUT", "retcode": "CC 0004"},
        {"jobname": "BAD", "jobid": "JOB3", "status": "OUTPUT", "retcode": "CC 0012"},
        {"jobname": "ABEND", "jobid": "JOB4", "status": "OUTPUT", "retcode": "ABEND S0C7"},
        {"jobname": "JCL", "jobid": "JOB5", "status": "OUTPUT", "retcode": "JCL ERROR"},
        {"jobname": "RUNNING", "jobid": "JOB6", "status": "ACTIVE", "retcode": None},
    ]
    result = await client.list_failed_jobs({"prefix": "PAY*"})
    assert _last(client)["args"]["params"] == {"owner": "*", "prefix": "PAY*", "max-jobs": 200}
    assert result["checked"] == 6
    assert [job["jobName"] for job in result["failed"]] == ["BAD", "ABEND", "JCL"]

    strict = await client.list_failed_jobs({"maxRc": 0})
    assert [job["jobName"] for job in strict["failed"]] == ["WARN", "BAD", "ABEND", "JCL"]


@pytest.mark.anyio
async def test_hold_release_and_change_class():
    client = make_client()
    job = {"jobId": "JOB00042", "jobName": "PAYRUN"}

    assert await client.hold_job(job) == {"held": True}
    call = _last(client)
    assert (call["method"], call["url"]) == ("PUT", JOBS + "PAYRUN/JOB00042")
    assert call["args"]["json"] == {"request": "hold", "version": "2.0"}

    assert await client.release_job(job) == {"released": True}
    assert _last(client)["args"]["json"] == {"request": "release", "version": "2.0"}

    assert await client.change_job_class({**job, "jobClass": "b"}) == {"jobClass": "B"}
    assert _last(client)["args"]["json"] == {"class": "B", "version": "2.0"}

    with pytest.raises(ValueError, match="jobClass"):
        await client.change_job_class({**job, "jobClass": "A;B"})


@pytest.mark.anyio
async def test_recall_and_migrate():
    client = make_client()
    assert await client.recall_dataset({"dataset": "HLQ.ARCHIVED"}) == {"recalled": True}
    call = _last(client)
    assert (call["method"], call["url"]) == ("PUT", FILES + "ds/HLQ.ARCHIVED")
    assert call["args"]["json"] == {"request": "hrecall", "wait": True}
    assert await client.migrate_dataset({"dataset": "HLQ.OLD"}) == {"migrated": True}
    assert _last(client)["args"]["json"] == {"request": "hmigrate", "wait": True}


@pytest.mark.anyio
async def test_the_profile_name_is_optional_but_a_wrong_one_is_refused():
    client = make_client()
    await client.list_datasets({"pattern": "IBMUSER.**"})
    await client.list_datasets({"profileName": "zosmf", "pattern": "IBMUSER.**"})
    with pytest.raises(ValueError, match="does not match"):
        await client.list_datasets({"profileName": "other", "pattern": "IBMUSER.**"})


# ------------------------------------------------------------ system, TSO, console

@pytest.mark.anyio
@responses.activate
async def test_system_list():
    responses.get(ROOT + "/resttopology/systems", json={"items": [
        {"systemNickName": "SYSA", "systemName": "SYSA", "sysplexName": "PLEX1", "zosVR": "z/OS V3R1", "url": "https://host:10443/zosmf/"},
    ], "numRows": 1})
    result = await make_client().list_systems({})
    assert result == {"systems": [
        {"name": "SYSA", "systemName": "SYSA", "sysplex": "PLEX1", "zosVersion": "z/OS V3R1", "url": "https://host:10443/zosmf/"},
    ]}
    assert responses.calls[0].request.headers["X-CSRF-ZOSMF-HEADER"] == "true"


@pytest.mark.anyio
@responses.activate
async def test_tso_command_uses_the_one_request_interface_when_zosmf_has_it():
    responses.put(ROOT + "/tsoApp/v1/tso", json={"cmdResponse": [
        {"message": "IKJ56247I DATA SET HLQ.OLD NOT ALLOCATED"}, {"message": "READY"},
    ]})
    result = await make_client().tso_command({"command": "DELETE 'HLQ.OLD'"})
    assert json.loads(responses.calls[0].request.body) == {"tsoCmd": "DELETE 'HLQ.OLD'", "cmdState": "stateless"}
    assert result["command"] == "DELETE 'HLQ.OLD'"
    assert "IKJ56247I" in result["content"]


@pytest.mark.anyio
@responses.activate
async def test_tso_command_falls_back_to_an_address_space_and_stops_it():
    responses.put(ROOT + "/tsoApp/v1/tso", status=404, body="not found")
    responses.post(ROOT + "/tsoApp/tso", json={"servletKey": "IBMUSER-71-aabcaaaf", "tsoData": []})
    responses.put(ROOT + "/tsoApp/tso/IBMUSER-71-aabcaaaf", json={"tsoData": [
        {"TSO MESSAGE": {"VERSION": "0100", "DATA": "IBMUSER.JCL"}},
        {"TSO PROMPT": {"VERSION": "0100", "HIDDEN": "FALSE"}},
    ]})
    responses.delete(ROOT + "/tsoApp/tso/IBMUSER-71-aabcaaaf", json={"servletKey": "IBMUSER-71-aabcaaaf"})

    result = await make_client().tso_query({"command": "LISTCAT LEVEL('IBMUSER')"})

    assert result["content"].strip() == "IBMUSER.JCL"
    assert [call.request.method for call in responses.calls] == ["PUT", "POST", "PUT", "DELETE"]
    assert "acct=ACCT" in responses.calls[1].request.url and "proc=IZUFPROC" in responses.calls[1].request.url
    assert json.loads(responses.calls[2].request.body) == {
        "TSO RESPONSE": {"VERSION": "0100", "DATA": "LISTCAT LEVEL('IBMUSER')"},
    }


@pytest.mark.anyio
@responses.activate
@pytest.mark.parametrize("command, message", [
    ("DELETE 'HLQ.OLD'", "not a read-only query"),
    ("LISTCAT ENT('HLQ.A') OUTFILE(OUT)", "writes a dataset"),
    ("SEARCH CLASS(DATASET) CLIST", "writes a dataset"),
    ("LISTDS 'HLQ.A'\nDELETE 'HLQ.A'", "not a read-only query"),
])
async def test_tso_query_runs_nothing_that_could_change_the_system(command, message):
    with pytest.raises(ValueError, match=message):
        await make_client().tso_query({"command": command})
    assert len(responses.calls) == 0


@pytest.mark.anyio
@responses.activate
@pytest.mark.parametrize("command, message", [
    ("SUBMIT 'HLQ.JCL(RUN)'", "job.submit"),
    ("SUB 'HLQ.JCL(RUN)'", "job.submit"),
    ("LISTC\nDELETE 'A'", "one line"),
    ("", "required"),
])
async def test_tso_command_refuses_submit_and_more_than_one_line(command, message):
    with pytest.raises(ValueError, match=message):
        await make_client().tso_command({"command": command})
    assert len(responses.calls) == 0


def test_tso_rules():
    assert tso.is_query("listcat level('ibmuser')")
    assert tso.is_query("LISTDS 'HLQ.CLIST' MEMBERS")  # a dataset named CLIST is not the CLIST operand
    assert tso.is_query("LISTCAT ENT('A.OUTFILE')")
    assert not tso.is_query("LISTCAT ENT('A')OUTFILE(X)")
    assert not tso.is_query("LISTC OFILE(X)")
    assert not tso.is_query("ALLOCATE DA('A') NEW")
    assert tso.command_verb("  lu ibmuser") == "LU"
    assert tso.submits("submit 'a'") and not tso.submits("SUBSTR")


@pytest.mark.anyio
@responses.activate
async def test_console_command_returns_the_response_as_lines():
    responses.put(ROOT + "/restconsoles/consoles/defcn", json={
        "cmd-response": "IEE114I 12.00.00 ACTIVITY\r JOBS M/S TS USERS\r 00003 00012",
        "cmd-response-key": "C1234567",
    })
    result = await make_client().console_command({"command": "D A,L"})
    assert json.loads(responses.calls[0].request.body) == {"cmd": "D A,L"}
    assert result["content"].splitlines()[0].startswith("IEE114I")
    assert len(result["content"].splitlines()) == 3


@pytest.mark.anyio
@responses.activate
async def test_a_refusal_from_zosmf_is_reported_in_its_own_words():
    responses.put(ROOT + "/restconsoles/consoles/defcn", status=401, json={"reason": "Not authorized to EMCS console"})
    with pytest.raises(RuntimeError, match="401.*Not authorized to EMCS console"):
        await make_client().console_command({"command": "D A,L"})
    with pytest.raises(ValueError, match="consoleName"):
        await make_client().console_command({"command": "D A,L", "consoleName": "../x"})
