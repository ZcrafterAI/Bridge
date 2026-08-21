from __future__ import annotations

import asyncio
import re
from typing import Any

from zcrafter_mainframe.patch import apply_unified_diff
from zowe.zos_files_for_zowe_sdk import Files
from zowe.zos_jobs_for_zowe_sdk import Jobs
from zowe.zosmf_for_zowe_sdk import Zosmf

_API_ML_UNSUPPORTED = "API ML service discovery is not available through the REST provider yet."


class ZoweSdkMainframeClient:
    def __init__(
        self,
        profile_name: str,
        connection: dict[str, Any],
        *,
        timeout_seconds: float = 30.0,
        files: Any | None = None,
        jobs: Any | None = None,
        zosmf: Any | None = None,
        base_path: str = "",
    ) -> None:
        if not profile_name:
            raise ValueError("Zowe CLI profile name is required.")
        self.profile_name = profile_name
        self._timeout = timeout_seconds
        self._files = files if files is not None else Files(connection)
        self._jobs = jobs if jobs is not None else Jobs(connection)
        self._zosmf = zosmf if zosmf is not None else Zosmf(connection)
        self._apply_csrf(self._files)
        self._apply_csrf(self._jobs)
        self._apply_csrf(self._zosmf)
        if base_path:
            self._apply_base_path(base_path)

    def _apply_csrf(self, sdk: Any) -> None:
        for headers in (
            getattr(sdk, "default_headers", None),
            getattr(sdk, "request_arguments", {}).get("headers") if isinstance(getattr(sdk, "request_arguments", None), dict) else None,
        ):
            if isinstance(headers, dict):
                headers["X-CSRF-ZOSMF-HEADER"] = "true"
        timeout = self._timeout
        if hasattr(sdk, "session_arguments") and isinstance(sdk.session_arguments, dict):
            sdk.session_arguments["timeout"] = timeout
        handler = getattr(sdk, "request_handler", None)
        if handler is not None and hasattr(handler, "session_arguments"):
            handler.session_arguments["timeout"] = timeout

    def _reset_json_content_type(self, sdk: Any) -> None:
        for headers in (
            getattr(sdk, "default_headers", None),
            getattr(sdk, "request_arguments", {}).get("headers") if isinstance(getattr(sdk, "request_arguments", None), dict) else None,
        ):
            if isinstance(headers, dict):
                headers["Content-Type"] = "application/json"
                headers["Content-type"] = "application/json"

    def _apply_base_path(self, base_path: str) -> None:
        prefix = base_path.rstrip("/")
        self._rewrite_endpoint(self._files, f"{prefix}/restfiles/")
        self._rewrite_endpoint(self._jobs, f"{prefix}/restjobs/jobs/")
        self._rewrite_endpoint(self._zosmf, f"{prefix}/info")

    def _rewrite_endpoint(self, sdk: Any, service_path: str) -> None:
        host_url = getattr(getattr(sdk, "connection", None), "host_url", None)
        if not host_url:
            return
        endpoint = f"https://{host_url}{service_path}"
        sdk.request_endpoint = endpoint
        if isinstance(getattr(sdk, "request_arguments", None), dict):
            sdk.request_arguments["url"] = endpoint

    def _assert_profile(self, input: dict[str, Any]) -> None:
        tool_profile = _string(input.get("profileName"))
        if not tool_profile:
            raise ValueError("Tool profile is required.")
        if tool_profile != self.profile_name:
            raise ValueError(
                f'Tool profile "{tool_profile}" does not match resolved client profile "{self.profile_name}"'
            )

    async def _run(self, fn, *args, **kwargs):
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"z/OSMF HTTP call timed out after {self._timeout}s") from exc

    def _files_request(
        self,
        method: str,
        suffix: str,
        *,
        params: dict[str, Any] | None = None,
        data: Any = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        expected_code: list[int] | None = None,
    ) -> Any:
        args = self._files.create_custom_request_arguments()
        args["headers"] = {
            **(args.get("headers") or {}),
            "Content-Type": "text/plain" if data is not None and json_body is None else "application/json",
            "X-CSRF-ZOSMF-HEADER": "true",
        }
        args["url"] = f"{self._files.request_endpoint}{suffix.lstrip('/')}"
        if params:
            args["params"] = params
        if data is not None:
            args["data"] = data
        if json_body is not None:
            args["json"] = json_body
        if headers:
            args.setdefault("headers", {}).update(headers)
        codes = expected_code if expected_code is not None else [200]
        return self._files.request_handler.perform_request(method, args, codes)

    def _jobs_request(
        self,
        method: str,
        suffix: str = "",
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        expected_code: list[int] | None = None,
    ) -> Any:
        args = self._jobs.create_custom_request_arguments()
        args["headers"] = {
            **(args.get("headers") or {}),
            "Content-Type": "text/plain" if data is not None and json_body is None else "application/json",
            "X-CSRF-ZOSMF-HEADER": "true",
        }
        args["url"] = f"{self._jobs.request_endpoint}{suffix}"
        if params:
            args["params"] = params
        if json_body is not None:
            args["json"] = json_body
        if data is not None:
            args["data"] = data
        if headers:
            args.setdefault("headers", {}).update(headers)
        codes = expected_code if expected_code is not None else [200]
        return self._jobs.request_handler.perform_request(method, args, codes)

    async def verify_connection(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        info = await self._run(self._zosmf.get_info)
        return {
            "ok": True,
            "profileName": self.profile_name,
            "auth": "apiml" if "basePath" in str(getattr(self._files, "request_endpoint", "")) else "zosmf",
            "zosmfReachable": True,
            **_normalize_zosmf_info(info),
        }

    async def list_apiml_services(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        raise NotImplementedError(_API_ML_UNSUPPORTED)

    async def get_apiml_service(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        raise NotImplementedError(_API_ML_UNSUPPORTED)

    async def get_apiml_api_doc(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        raise NotImplementedError(_API_ML_UNSUPPORTED)

    async def list_datasets(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        payload = await self._run(self._files.list_dsn, _string(input["pattern"]))
        data_sets = [_normalize_dataset(item) for item in _items(payload)]
        return {"dataSets": _limit(data_sets, input.get("limit"))}

    async def get_dataset_info(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        payload = await self._run(self._files.list_dsn, _string(input["dataset"]))
        items = _items(payload)
        match = None
        wanted = _string(input["dataset"]).upper()
        for item in items:
            if isinstance(item, dict) and _string(_pick(item, "dsname", "name")).upper() == wanted:
                match = item
                break
        if match is None and items:
            match = items[0] if isinstance(items[0], dict) else {}
        return {"dataSet": _normalize_dataset(match or {})}

    async def read_dataset(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        payload = await self._run(self._files.get_dsn_content, _string(input["dataset"]))
        return {"content": _content(payload)}

    async def read_member(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        target = _format_member(input["dataset"], input["member"])
        payload = await self._run(self._files.get_dsn_content, target)
        return {"content": _content(payload)}

    async def list_members(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        payload = await self._run(self._files.list_dsn_members, _string(input["dataset"]))
        members = [_normalize_member(item) for item in _as_list(payload)]
        pattern = _string(input.get("pattern"))
        if pattern:
            members = [m for m in members if _wildcard_match(_string(m.get("name")), pattern)]
        return {"members": _limit(members, input.get("limit"))}

    async def write_dataset(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        await self._run(self._files.write_to_dsn, _string(input["dataset"]), _string(input.get("content")))
        self._reset_json_content_type(self._files)
        return {}

    async def write_member(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        target = _format_member(input["dataset"], input["member"])
        await self._run(self._files.write_to_dsn, target, _string(input.get("content")))
        self._reset_json_content_type(self._files)
        return {}

    async def patch_member(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        current = await self.read_member(input)
        patched = apply_unified_diff(current["content"], _string(input["unifiedDiff"]))
        await self.write_member({**input, "content": patched})
        return {}

    async def create_dataset(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        body = _create_body(input.get("attributes"))
        await self._run(
            self._files_request,
            "POST",
            f"ds/{_string(input['dataset'])}",
            json_body=body,
            expected_code=[201, 200],
        )
        return {"created": True}

    async def create_dataset_like(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        body: dict[str, Any] = {"like": _string(input["likeDataset"])}
        if isinstance(input.get("attributes"), dict) and input.get("attributes"):
            extra = _create_body(input.get("attributes"))
            body.update({k: v for k, v in extra.items() if v not in (None, "")})
        await self._run(
            self._files_request,
            "POST",
            f"ds/{_string(input['dataset'])}",
            json_body=body,
            expected_code=[201, 200],
        )
        return {"created": True}

    async def delete_dataset(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        await self._run(
            self._files_request,
            "DELETE",
            f"ds/{_string(input['dataset'])}",
            expected_code=[200, 202, 204],
        )
        return {"deleted": True}

    async def rename_dataset(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        await self._run(
            self._files_request,
            "PUT",
            f"ds/{_string(input['newDataset'])}",
            json_body={"request": "rename", "from-dataset": {"dsn": _string(input["dataset"])}},
            expected_code=[200, 204],
        )
        return {"renamed": True}

    async def copy_dataset(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        from_body: dict[str, Any] = {"dsn": _string(input["sourceDataset"])}
        if input.get("sourceMember"):
            from_body["member"] = _string(input["sourceMember"])
        target = _string(input["targetDataset"])
        if input.get("targetMember"):
            target = _format_member(input["targetDataset"], input["targetMember"])
        body: dict[str, Any] = {"request": "copy", "from-dataset": from_body}
        if input.get("replace"):
            body["replace"] = True
        await self._run(
            self._files_request,
            "PUT",
            f"ds/{target}",
            json_body=body,
            expected_code=[200, 204],
        )
        return {"copied": True}

    async def delete_member(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        target = _format_member(input["dataset"], input["member"])
        await self._run(
            self._files_request,
            "DELETE",
            f"ds/{target}",
            expected_code=[200, 202, 204],
        )
        return {"deleted": True}

    async def rename_member(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        dataset = _string(input["dataset"])
        await self._run(
            self._files_request,
            "PUT",
            f"ds/{_format_member(dataset, input['newMember'])}",
            json_body={
                "request": "rename",
                "from-dataset": {"dsn": dataset, "member": _string(input["member"])},
            },
            expected_code=[200, 204],
        )
        return {"renamed": True}

    async def search_members(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        dataset = _string(input["dataset"])
        members = await self.list_members(input)
        needle = _string(input["searchString"])
        case_sensitive = bool(input.get("caseSensitive"))
        regex = bool(input.get("regex"))
        matcher = _make_matcher(needle, case_sensitive, regex)
        matches: list[dict[str, Any]] = []
        for member in members["members"]:
            name = _string(member.get("name"))
            if not name:
                continue
            content = await self.read_member({**input, "member": name})
            for index, line in enumerate(_split_lines(content["content"]), start=1):
                if matcher(line):
                    matches.append({"dataset": dataset, "member": name, "line": index, "text": line})
        return {"matches": matches}

    async def list_jobs(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        owner = _string(input.get("owner")) or "*"
        prefix = _string(input.get("prefix"), "*")
        payload = await self._run(self._jobs.list_jobs, owner, prefix)
        jobs = [_normalize_job(item) for item in _as_list(payload)]
        if input.get("status"):
            requested = _string(input["status"]).upper()
            jobs = [job for job in jobs if _string(job.get("status")).upper() == requested]
        return {"jobs": _limit(jobs, input.get("limit"))}

    async def get_job_status(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        job_name, job_id = await self._resolve_job(input)
        payload = await self._run(self._jobs.get_job_status, job_name, job_id)
        return _normalize_job(payload)

    async def submit_job(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        jcl = input.get("jcl")
        if isinstance(jcl, str) and jcl.strip():
            payload = await self._run(self._jobs.submit_plaintext, jcl)
            return _normalize_submitted_job(payload)
        dataset = input.get("dataset")
        if isinstance(dataset, str) and dataset.strip():
            payload = await self._run(self._jobs.submit_from_mainframe, dataset)
            return _normalize_submitted_job(payload)
        raise ValueError("Either jcl or dataset is required to submit a job.")

    async def cancel_job(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        job_name, job_id = await self._resolve_job(input)
        await self._run(
            self._jobs_request,
            "PUT",
            f"{job_name}/{job_id}",
            json_body={"request": "cancel"},
            expected_code=[200, 202],
        )
        return {"cancelled": True}

    async def purge_job(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        job_name, job_id = await self._resolve_job(input)
        await self._run(
            self._jobs_request,
            "DELETE",
            f"{job_name}/{job_id}",
            expected_code=[200, 202],
        )
        return {"purged": True}

    async def wait_for_job(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        target_status = _string(input.get("status"), "OUTPUT").upper()
        attempts = int(input.get("attempts") or 30)
        delay_seconds = int(input.get("delayMs") or 1000) / 1000
        last_status: dict[str, Any] | None = None
        for attempt in range(max(1, attempts)):
            last_status = await self.get_job_status(input)
            if _string(last_status.get("status")).upper() == target_status:
                return last_status
            if attempt < attempts - 1:
                await asyncio.sleep(delay_seconds)
        raise TimeoutError(f'Job "{input["jobId"]}" did not reach status "{target_status}".')

    async def get_job_jcl(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        spool = await self.list_job_spool_files(input)
        for spool_file in spool["spoolFiles"]:
            if _string(spool_file.get("ddName")).upper() != "JESJCL":
                continue
            if spool_file.get("id") is None:
                continue
            return await self.get_job_spool_content({**input, "spoolId": spool_file["id"]})
        raise LookupError(f'No JESJCL spool file found for job {input["jobId"]}.')

    async def list_job_spool_files(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        job_name, job_id = await self._resolve_job(input)
        payload = await self._run(self._jobs_request, "GET", f"{job_name}/{job_id}/files")
        return {"spoolFiles": [_normalize_spool_file(item) for item in _as_list(payload)]}

    async def get_job_spool_content(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        job_name, job_id = await self._resolve_job(input)
        spool_id = _string(input["spoolId"])
        if spool_id.endswith(".0"):
            spool_id = str(int(float(spool_id)))
        payload = await self._run(self._jobs_request, "GET", f"{job_name}/{job_id}/files/{spool_id}/records")
        return {"content": _content(payload)}

    async def get_job_output(self, input: dict[str, Any]) -> dict[str, Any]:
        self._assert_profile(input)
        spool = await self.list_job_spool_files(input)
        contents = []
        for spool_file in spool["spoolFiles"]:
            if spool_file.get("id") is None:
                continue
            content = await self.get_job_spool_content({**input, "spoolId": spool_file["id"]})
            contents.append(content["content"])
        return {"content": "\n\n".join(contents), "spoolFiles": spool["spoolFiles"]}

    async def _resolve_job(self, input: dict[str, Any]) -> tuple[str, str]:
        job_id = _string(input["jobId"])
        job_name = _string(input.get("jobName"))
        if job_name:
            return job_name, job_id
        payload = await self._run(self._jobs_request, "GET", "", params={"owner": "*", "jobid": job_id})
        for item in _as_list(payload):
            if isinstance(item, dict) and _string(_pick(item, "jobid", "jobId")) == job_id:
                return _string(_pick(item, "jobname", "jobName")), job_id
        raise LookupError(f'Job "{job_id}" was not found.')


def _create_body(attributes: Any) -> dict[str, Any]:
    if not isinstance(attributes, dict):
        attributes = {}
    data_set_type = _string(_pick(attributes, "type", "datasetType", "dataSetType")).strip().lower()
    body: dict[str, Any] = {}
    if data_set_type in {"pds", "pdse", "partitioned", "library"}:
        body["dsorg"] = "PO"
        body["dsntype"] = "LIBRARY" if data_set_type in {"pdse", "library"} else "PDS"
        body.setdefault("dirblk", 10)
        body.setdefault("alcunit", "TRK")
        body.setdefault("primary", 5)
        body.setdefault("secondary", 2)
        body.setdefault("recfm", "FB")
        body.setdefault("lrecl", 80)
        body.setdefault("blksize", 32720)
    elif data_set_type in {"ps", "seq", "sequential", ""}:
        body["dsorg"] = "PS"
        body.setdefault("alcunit", "TRK")
        body.setdefault("primary", 5)
        body.setdefault("secondary", 1)
        body.setdefault("recfm", "FB")
        body.setdefault("lrecl", 80)
        body.setdefault("blksize", 32720)
    mapping = (
        (("recordFormat", "recfm"), "recfm"),
        (("recordLength", "lrecl"), "lrecl"),
        (("blockSize", "blksize", "blksz"), "blksize"),
        (("primarySpace", "primary"), "primary"),
        (("secondarySpace", "secondary"), "secondary"),
        (("directoryBlocks", "directory"), "dirblk"),
        (("volumeSerial", "volume"), "volser"),
        (("unit",), "unit"),
        (("dataClass",), "dataclass"),
        (("managementClass",), "mgntclass"),
        (("storageClass",), "storclass"),
        (("spaceUnit", "spaceUnits"), "alcunit"),
    )
    for keys, dest in mapping:
        value = _pick(attributes, *keys)
        if value is not None and value != "":
            body[dest] = value
    return body


def _items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "records", "dataSets", "members", "jobs"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
        return [payload] if payload else []
    return []


def _as_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "records", "jobs", "spoolFiles"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return nested
        return [payload] if payload else []
    return []


def _content(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("response", "content", "contents", "data", "text", "records"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return ""


def _normalize_zosmf_info(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return _compact(
        {
            "zosVersion": _pick(item, "zos_version", "zosVersion"),
            "zosmfVersion": _pick(item, "zosmf_version", "zosmfVersion"),
            "apiVersion": _pick(item, "api_version", "apiVersion"),
        }
    )


def _normalize_dataset(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return _compact(
        {
            "name": _pick(item, "name", "dsname", "dataSetName", "dataset"),
            "organization": _pick(item, "organization", "dsorg"),
            "recordFormat": _pick(item, "recordFormat", "recfm"),
            "recordLength": _pick(item, "recordLength", "lrecl"),
            "blockSize": _pick(item, "blockSize", "blksize", "blksz"),
            "volume": _pick(item, "volume", "volser", "vol"),
            "migrated": _pick(item, "migrated", "migr"),
            "used": _pick(item, "used"),
        }
    )


def _normalize_job(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return _compact(
        {
            "jobId": _pick(item, "jobId", "jobid"),
            "jobName": _pick(item, "jobName", "jobname"),
            "status": _string(_pick(item, "status"), "UNKNOWN").strip() or "UNKNOWN",
            "returnCode": _pick(item, "returnCode", "retcode"),
            "owner": _pick(item, "owner"),
            "class": _pick(item, "class", "jobclass"),
            "type": _pick(item, "type", "jobtype"),
        }
    )


def _normalize_member(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"name": item}
    if not isinstance(item, dict):
        return {}
    return _compact({"name": _pick(item, "name", "member", "memberName")})


def _normalize_submitted_job(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return _compact({"jobId": _pick(item, "jobId", "jobid"), "jobName": _pick(item, "jobName", "jobname")})


def _normalize_spool_file(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return _compact(
        {
            "id": _pick(item, "id", "spoolId", "spoolid", "ddid"),
            "stepName": _pick(item, "stepName", "stepname"),
            "ddName": _pick(item, "ddName", "ddname"),
            "recordFormat": _pick(item, "recordFormat", "recfm"),
            "records": _pick(item, "records", "record-count", "recordCount"),
            "bytes": _pick(item, "bytes", "byte-count", "byteCount"),
        }
    )


def _compact(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None and value != ""}


def _string(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _format_member(dataset: Any, member: Any) -> str:
    return f"{_string(dataset)}({_string(member)})"


def _pick(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _limit(items: list[dict[str, Any]], raw_limit: Any) -> list[dict[str, Any]]:
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return items
    if limit <= 0:
        return items
    return items[:limit]


def _wildcard_match(name: str, pattern: str) -> bool:
    regex = "^" + re.escape(pattern).replace("\\*", ".*").replace("\\?", ".") + "$"
    return re.match(regex, name, re.IGNORECASE) is not None


def _make_matcher(needle: str, case_sensitive: bool, regex: bool):
    if regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(needle, flags)
        return lambda line: compiled.search(line) is not None
    if case_sensitive:
        return lambda line: needle in line
    lowered = needle.lower()
    return lambda line: lowered in line.lower()


def _split_lines(content: str) -> list[str]:
    if content == "":
        return []
    return content.splitlines()


__all__ = ["ZoweSdkMainframeClient"]
