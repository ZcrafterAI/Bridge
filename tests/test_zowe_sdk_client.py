from __future__ import annotations

import asyncio
import pytest
from mainframe_workflow_mcp.clients.zowe_sdk import ZoweSdkMainframeClient

PROFILE = {"profileName": "zosmf"}


class FakeHandler:
    def __init__(self):
        self.calls = []
        self.payloads = {}

    def perform_request(self, method, request_arguments, expected_code=None):
        url = request_arguments.get("url", "")
        self.calls.append({"method": method, "url": url, "args": request_arguments, "expected_code": expected_code})
        key = (method, url)
        if key in self.payloads:
            return self.payloads[key]
        return {}


class FakeSdk:
    def __init__(self, endpoint: str, handler: FakeHandler):
        self.request_endpoint = endpoint
        self.request_handler = handler
        self.request_arguments = {"url": endpoint, "auth": ("u", "p"), "headers": {}}
        self.session_arguments = {"timeout": 30, "verify": False}

    def create_custom_request_arguments(self):
        return {"url": self.request_endpoint, "auth": ("u", "p"), "headers": {"Content-type": "application/json"}}

    def list_dsn(self, name_pattern):
        return {"items": [{"dsname": "IBMUSER.JCL", "dsorg": "PO", "recfm": "FB", "lrecl": "80"}]}

    def list_dsn_members(self, dataset_name):
        return [{"member": "IEFBR14"}]

    def get_dsn_content(self, dataset_name):
        return {"response": f"content of {dataset_name}"}

    def write_to_dsn(self, dataset_name, data):
        return {}

    def get_info(self):
        return {"zos_version": "05.29.00", "zosmf_version": "2.5"}

    def list_jobs(self, owner=None, prefix="*", max_jobs=1000, user_correlator=None):
        return [{"jobname": "TESTJOB", "jobid": "JOB00123", "status": "OUTPUT", "retcode": "CC 0000", "owner": "IBMUSER"}]

    def get_job_status(self, jobname, jobid):
        return {"jobname": jobname, "jobid": jobid, "status": "OUTPUT", "retcode": "CC 0000", "owner": "IBMUSER"}

    def submit_plaintext(self, jcl):
        return {"jobname": "TESTJOB", "jobid": "JOB00999"}

    def submit_from_mainframe(self, jcl_path):
        return {"jobname": "TESTJOB", "jobid": "JOB00998"}


def make_client(timeout=5.0, **overrides) -> ZoweSdkMainframeClient:
    handler = FakeHandler()
    files = overrides.get("files") or FakeSdk("https://host:10443/zosmf/restfiles/", handler)
    jobs = overrides.get("jobs") or FakeSdk("https://host:10443/zosmf/restjobs/jobs/", handler)
    zosmf = overrides.get("zosmf") or FakeSdk("https://host:10443/zosmf/info", handler)
    client = ZoweSdkMainframeClient(
        "zosmf",
        {"host_url": "host:10443", "user": "u", "password": "p", "ssl_verification": False},
        timeout_seconds=timeout,
        files=files,
        jobs=jobs,
        zosmf=zosmf,
    )
    client._handler = handler  # type: ignore[attr-defined]
    return client


@pytest.mark.anyio
async def test_profile_mismatch_fails_before_http():
    client = make_client()
    with pytest.raises(ValueError, match="does not match"):
        await client.list_datasets({"profileName": "other", "pattern": "IBMUSER.**"})
    assert client._handler.calls == []


@pytest.mark.anyio
async def test_verify_connection_returns_cli_shape():
    client = make_client()
    result = await client.verify_connection(PROFILE)
    assert result["ok"] is True
    assert result["profileName"] == "zosmf"
    assert result["zosmfReachable"] is True
    assert result["zosVersion"] == "05.29.00"


@pytest.mark.anyio
async def test_list_datasets_normalizes_items():
    client = make_client()
    result = await client.list_datasets({**PROFILE, "pattern": "IBMUSER.**"})
    assert result["dataSets"][0]["name"] == "IBMUSER.JCL"
    assert result["dataSets"][0]["organization"] == "PO"


@pytest.mark.anyio
async def test_http_timeout_fails_fast():
    class SlowZosmf(FakeSdk):
        def get_info(self):
            import time
            time.sleep(1)
            return {}

    handler = FakeHandler()
    client = make_client(
        timeout=0.05,
        zosmf=SlowZosmf("https://host:10443/zosmf/info", handler),
    )
    with pytest.raises(TimeoutError, match="timed out"):
        await client.verify_connection(PROFILE)


@pytest.mark.anyio
async def test_apiml_catalog_tools_are_unimplemented():
    client = make_client()
    with pytest.raises(NotImplementedError, match="REST"):
        await client.list_apiml_services(PROFILE)


@pytest.mark.anyio
async def test_client_does_not_spawn_zowe(monkeypatch):
    spawned = []

    async def fake_exec(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("subprocess should not run")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    client = make_client()
    await client.list_datasets({**PROFILE, "pattern": "A.**"})
    await client.list_jobs(PROFILE)
    await client.read_member({**PROFILE, "dataset": "A.B", "member": "M"})
    assert spawned == []
