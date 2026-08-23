"""Live z/OSMF exercise of every ZoweSdkMainframeClient method.

Run from the repo root:
    .venv/Scripts/python scripts/live_zowe_sdk_tools.py

Uses credential-resolver + HTTP only (no `zowe` CLI). Mutating calls are
restricted to throwaway {user}.RTEST.* datasets and a submitted IEFBR14 job.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import textwrap
import traceback
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
load_dotenv(ROOT / ".env")

from mainframe_workflow_mcp.credentials import resolve_credentials  # noqa: E402
from mainframe_workflow_mcp.clients.zowe_sdk import ZoweSdkMainframeClient  # noqa: E402

PROFILE = os.environ.get("MAINFRAME_WORKFLOW_ZOWE_PROFILE", "zosmf")
TIMEOUT = float(os.environ.get("MAINFRAME_WORKFLOW_HTTP_TIMEOUT_SECONDS", "30"))
BASE_PATH = os.environ.get("MAINFRAME_WORKFLOW_APIML_BASE_PATH", "")


def redact(text: str) -> str:
    return re.sub(r"Basic [A-Za-z0-9+/=]+", "Basic [REDACTED]", text)


def preview(value, limit: int = 1200) -> str:
    text = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)
    text = text.replace("\r\n", "\n")
    if len(text) > limit:
        return text[:limit] + f"\n... [{len(text) - limit} more chars]"
    return text


async def show(name: str, coro, results: list[dict]):
    print(f"\n=== {name} ===")
    try:
        data = await coro
        print(preview(data))
        results.append({"tool": name, "ok": True, "data": data})
        return data
    except Exception as exc:
        message = redact(f"{type(exc).__name__}: {exc}")
        print(f"ERROR: {message}")
        results.append({"tool": name, "ok": False, "error": message})
        return None


async def expect_not_implemented(name: str, coro, results: list[dict]):
    print(f"\n=== {name} (expected NotImplementedError) ===")
    try:
        await coro
        print("ERROR: call succeeded; expected NotImplementedError")
        results.append({"tool": name, "ok": False, "error": "expected NotImplementedError"})
    except NotImplementedError as exc:
        print(f"OK: {exc}")
        results.append({"tool": name, "ok": True, "data": str(exc)})


async def cleanup(client, p: dict, datasets: list[str]):
    for dataset in datasets:
        try:
            await client.delete_dataset({**p, "dataset": dataset})
            print(f"cleaned up {dataset}")
        except Exception as exc:
            message = redact(str(exc))
            if "404" in message or "not cataloged" in message.lower():
                print(f"cleanup skip {dataset}: not present")
            else:
                print(f"cleanup skip {dataset}: {message}")


async def main() -> int:
    creds = resolve_credentials(PROFILE)
    print(
        "resolved "
        f"host={creds.host} port={creds.port} user={creds.user} "
        f"rejectUnauthorized={creds.reject_unauthorized} basePath={creds.base_path!r} "
        f"(password omitted, length={len(creds.password)})"
    )
    hlq = creds.user.upper()
    pds = f"{hlq}.RTEST.PDS"
    seq = f"{hlq}.RTEST.SEQ"
    renamed = f"{hlq}.RTEST.REN"
    copy_ds = f"{hlq}.RTEST.CPY"
    scratch = [pds, seq, renamed, copy_ds]

    connection = {
        "host_url": f"{creds.host}:{creds.port}",
        "user": creds.user,
        "password": creds.password,
        "ssl_verification": creds.reject_unauthorized,
        "protocol": creds.protocol,
    }
    client = ZoweSdkMainframeClient(
        PROFILE,
        connection,
        timeout_seconds=TIMEOUT,
        base_path=BASE_PATH or creds.base_path or "",
    )
    p = {"profileName": PROFILE}
    results: list[dict] = []

    await show("connection.verify", client.verify_connection(p), results)
    listed = await show(
        "dataset.list",
        client.list_datasets({**p, "pattern": f"{hlq}.**", "limit": 20}),
        results,
    )
    sample_pds = None
    sample_member = None
    if listed and listed.get("dataSets"):
        for item in listed["dataSets"]:
            name = item.get("name") or ""
            if "." in name:
                sample_pds = name
                break
        if sample_pds is None:
            sample_pds = listed["dataSets"][0].get("name")
        await show("dataset.info", client.get_dataset_info({**p, "dataset": sample_pds}), results)
        members = await show("member.list", client.list_members({**p, "dataset": sample_pds, "limit": 10}), results)
        if members and members.get("members"):
            sample_member = members["members"][0].get("name")
            await show(
                "member.read",
                client.read_member({**p, "dataset": sample_pds, "member": sample_member}),
                results,
            )
        else:
            await show("dataset.read", client.read_dataset({**p, "dataset": sample_pds}), results)

    jobs = await show("job.list", client.list_jobs({**p, "owner": hlq, "limit": 10}), results)
    existing_job = None
    if jobs and jobs.get("jobs"):
        existing_job = jobs["jobs"][0]
        job_in = {**p, "jobId": existing_job["jobId"], "jobName": existing_job.get("jobName")}
        await show("job.status", client.get_job_status(job_in), results)
        spool = await show("job.spool.files", client.list_job_spool_files(job_in), results)
        if spool and spool.get("spoolFiles"):
            first = spool["spoolFiles"][0]
            await show(
                "job.spool.content",
                client.get_job_spool_content({**job_in, "spoolId": first["id"]}),
                results,
            )
            await show("job.jcl", client.get_job_jcl(job_in), results)
            await show("job.output", client.get_job_output(job_in), results)

    await expect_not_implemented("apiml.services.list", client.list_apiml_services(p), results)
    await expect_not_implemented("apiml.service.get", client.get_apiml_service(p), results)
    await expect_not_implemented("apiml.apiDoc.get", client.get_apiml_api_doc(p), results)

    print("\n--- mutating throwaway datasets under", hlq, "---")
    await cleanup(client, p, scratch)
    try:
        created = await show(
            "dataset.create",
            client.create_dataset({**p, "dataset": pds, "attributes": {"type": "pdse", "recordLength": 80}}),
            results,
        )
        await show(
            "dataset.create (seq)",
            client.create_dataset({**p, "dataset": seq, "attributes": {"type": "sequential", "recordLength": 80}}),
            results,
        )
        if created is None:
            print("Aborting remaining mutating tests; could not create scratch PDS.")
        else:
            await show(
                "member.write",
                client.write_member({**p, "dataset": pds, "member": "HELLO", "content": "HELLO FROM REST CLIENT\nLINE TWO\n"}),
                results,
            )
            await show("member.read (scratch)", client.read_member({**p, "dataset": pds, "member": "HELLO"}), results)
            await show(
                "member.patch",
                client.patch_member(
                    {
                        **p,
                        "dataset": pds,
                        "member": "HELLO",
                        "unifiedDiff": textwrap.dedent(
                            """\
                            --- a/HELLO
                            +++ b/HELLO
                            @@ -1,2 +1,2 @@
                            -HELLO FROM REST CLIENT
                            +HELLO FROM REST CLIENT PATCHED
                             LINE TWO
                            """
                        ),
                    }
                ),
                results,
            )
            await show(
                "member.search",
                client.search_members({**p, "dataset": pds, "searchString": "PATCHED"}),
                results,
            )
            await show(
                "dataset.write",
                client.write_dataset({**p, "dataset": seq, "content": "SEQUENTIAL RECORD\n"}),
                results,
            )
            await show("dataset.read (scratch)", client.read_dataset({**p, "dataset": seq}), results)
            await show(
                "member.rename",
                client.rename_member({**p, "dataset": pds, "member": "HELLO", "newMember": "HELLO2"}),
                results,
            )
            await show("member.list (scratch)", client.list_members({**p, "dataset": pds}), results)
            await show(
                "dataset.createLike",
                client.create_dataset_like({**p, "dataset": copy_ds, "likeDataset": pds}),
                results,
            )
            await show(
                "dataset.copy",
                client.copy_dataset(
                    {**p, "sourceDataset": pds, "sourceMember": "HELLO2", "targetDataset": copy_ds, "targetMember": "COPIED"}
                ),
                results,
            )
            await show(
                "dataset.rename",
                client.rename_dataset({**p, "dataset": seq, "newDataset": renamed}),
                results,
            )
            await show("dataset.info (renamed)", client.get_dataset_info({**p, "dataset": renamed}), results)
            await show(
                "member.delete",
                client.delete_member({**p, "dataset": pds, "member": "HELLO2"}),
                results,
            )

            jcl = textwrap.dedent(
                f"""\
                //{hlq}A JOB 'IZUACCT',NOTIFY=&SYSUID,CLASS=A,MSGCLASS=H
                //STEP1    EXEC PGM=IEFBR14
                """
            )
            submitted = await show("job.submit", client.submit_job({**p, "jcl": jcl}), results)
            if submitted and submitted.get("jobId"):
                job_in = {**p, "jobId": submitted["jobId"], "jobName": submitted.get("jobName")}
                awaited = await show(
                    "job.wait",
                    client.wait_for_job({**job_in, "status": "OUTPUT", "attempts": 20, "delayMs": 1000}),
                    results,
                )
                if awaited:
                    await show("job.status (submitted)", client.get_job_status(job_in), results)
                    await show("job.spool.files (submitted)", client.list_job_spool_files(job_in), results)
                    await show("job.output (submitted)", client.get_job_output(job_in), results)
                hold_jcl = textwrap.dedent(
                    f"""\
                    //{hlq}B JOB 'IZUACCT',NOTIFY=&SYSUID,CLASS=A,MSGCLASS=H,TYPRUN=HOLD
                    //STEP1    EXEC PGM=IEFBR14
                    """
                )
                held = await show("job.submit (TYPRUN=HOLD)", client.submit_job({**p, "jcl": hold_jcl}), results)
                if held and held.get("jobId"):
                    held_in = {**p, "jobId": held["jobId"], "jobName": held.get("jobName")}
                    await show("job.cancel", client.cancel_job(held_in), results)
                    await show("job.purge (held)", client.purge_job(held_in), results)
                await show("job.purge (iefbr14)", client.purge_job(job_in), results)
    finally:
        await cleanup(client, p, scratch)

    failed = [row for row in results if not row["ok"]]
    print("\n========== SUMMARY ==========")
    for row in results:
        mark = "PASS" if row["ok"] else "FAIL"
        print(f"{mark:4} {row['tool']}")
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
