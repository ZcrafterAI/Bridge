"""Tool catalog. Real package's `contract.list_tool_definitions`.

Names, schemas and approval flags are derived from ZoweSdkMainframeClient's
own methods in this repo — that class is the interface the real executor
drives, so its signatures pin the contract. `approval` is "required" for any
call that changes z/OS state and "never" for lookups; proxy.py refuses to
guess, so every tool must carry one or the other.
"""
from __future__ import annotations

from typing import Any

_S = {"type": "string"}
_I = {"type": "integer"}
_B = {"type": "boolean"}
_O = {"type": "object"}


def _t(name: str, approval: str, description: str,
       required: dict[str, dict], optional: dict[str, dict] | None = None) -> dict[str, Any]:
    props = {"profileName": {
        **_S, "description": "Optional. The Zowe profile to run against; leave it out to use this server's own.",
    }}
    props.update(required)
    props.update(optional or {})
    return {
        "name": name,
        "approval": approval,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": [*required.keys()],
        },
    }


_DS = {"dataset": {**_S, "description": "Fully-qualified dataset name."}}
_DSM = {**_DS, "member": {**_S, "description": "PDS member name."}}
_JOB = {"jobId": {**_S, "description": "JES job id, e.g. JOB00042."}}
_JOBNAME = {"jobName": {**_S, "description": "Job name; looked up when omitted."}}
_PATH = {"path": {**_S, "description": "Absolute z/OS UNIX path, e.g. /u/ibmuser/app.log"}}
_COMMAND = {"command": {**_S, "description": "The command, on one line."}}

# Params every content-returning read accepts. Pulling a whole member or spool
# file into a model's context is the most expensive thing this server can do,
# so each of these tools can return just the part that was asked for.
_EXCERPT = {
    "searchText": {**_S, "description": "Return only lines matching this text, with line numbers."},
    "maxLines": {**_I, "description": "Cap the number of lines returned."},
    "caseSensitive": {**_B, "description": "Match searchText case-sensitively."},
    "regex": {**_B, "description": "Treat searchText as a regular expression."},
}

_DEFINITIONS: list[dict[str, Any]] = [
    # ---------------- read-only ----------------
    _t("profile.list", "never",
       "List the z/OSMF profile this server uses. You do not need to pass profileName.", {}),
    _t("connection.verify", "never", "Check z/OSMF reachability and authentication.", {}),
    _t("dataset.list", "never", "List datasets matching a pattern.",
       {"pattern": {**_S, "description": "Dataset pattern, e.g. HLQ.**"}},
       {"limit": _I}),
    _t("dataset.info", "never", "Catalog attributes for one dataset, without reading it.", _DS),
    _t("dataset.read", "never", "Read a sequential dataset's contents.", _DS, _EXCERPT),
    _t("member.read", "never", "Read one PDS member.", _DSM, _EXCERPT),
    _t("member.list", "never", "List members of a PDS.", _DS,
       {"pattern": _S, "limit": _I}),
    _t("member.search", "never", "Search PDS members for a string.",
       {**_DS, "searchString": _S},
       {"pattern": _S, "caseSensitive": _B, "regex": _B, "limit": _I}),
    _t("job.list", "never", "List jobs by owner, prefix or status.", {},
       {"owner": _S, "prefix": _S, "status": _S, "limit": _I}),
    _t("job.status", "never", "Status and return code for one job.", _JOB, _JOBNAME),
    _t("job.wait", "never", "Poll until a job reaches a status.", _JOB,
       {**_JOBNAME, "status": _S, "attempts": _I, "delayMs": _I}),
    _t("job.jcl", "never", "Retrieve the JCL a job was submitted with.", _JOB, _JOBNAME),
    _t("job.spool.list", "never", "List a job's spool files.", _JOB, _JOBNAME),
    _t("job.spool.read", "never", "Read one spool file's contents.",
       {**_JOB, "spoolId": _S}, {**_JOBNAME, **_EXCERPT}),
    _t("job.output", "never",
       "Read a job's spool output. Pass searchText to find lines in a large log "
       "instead of returning all of it.", _JOB, {**_JOBNAME, **_EXCERPT}),
    _t("job.steps", "never",
       "Each step of a job with its program and completion code. Use it to find the step "
       "that failed before reading the spool.", _JOB, _JOBNAME),
    _t("job.failed", "never",
       "List finished jobs that ended badly: an abend, a JCL error, or a return code above "
       "maxRc (default 4).", {},
       {"owner": {**_S, "description": "Job owner; * for everyone (default)."},
        "prefix": {**_S, "description": "Job name prefix, e.g. PAY*."},
        "maxRc": {**_I, "description": "Highest return code that still counts as fine."},
        "limit": _I}),
    _t("uss.list", "never", "List a z/OS UNIX directory: names, permissions, sizes.", _PATH,
       {"limit": _I}),
    _t("uss.read", "never", "Read a z/OS UNIX text file.", _PATH, _EXCERPT),
    _t("system.list", "never",
       "List the z/OS systems defined to z/OSMF, with sysplex and z/OS version.", {}),
    _t("tso.query", "never",
       "Run one read-only TSO command and return its output: LISTCAT, LISTDS, LISTALC, "
       "LISTUSER, LISTGRP, RLIST, SEARCH, STATUS, TIME. Anything else needs tso.command.",
       _COMMAND, _EXCERPT),
    _t("zowe.tools.search", "never",
       "Search this server's own tool catalog by keyword.",
       {"query": {**_S, "description": "Keyword to match against tool names and descriptions."}}),
    _t("zowe.capabilities.list", "never",
       "List every tool this server exposes, with its approval requirement.", {},
       {"approval": {**_S, "description": "Filter to 'never' or 'required'."}}),

    # ---------------- mutating (gated) ----------------
    _t("dataset.write", "required", "Overwrite a sequential dataset's contents.",
       {**_DS, "content": _S}),
    _t("member.write", "required", "Create or overwrite a PDS member.",
       {**_DSM, "content": _S}),
    _t("member.patch", "required", "Apply a unified diff to a PDS member.",
       {**_DSM, "unifiedDiff": _S}),
    _t("dataset.create", "required", "Allocate a new dataset.", _DS, {"attributes": _O}),
    _t("dataset.createLike", "required", "Allocate a dataset modelled on another.",
       {**_DS, "likeDataset": _S}, {"attributes": _O}),
    _t("dataset.delete", "required", "Delete a dataset.", _DS),
    _t("dataset.rename", "required", "Rename a dataset.", {**_DS, "newDataset": _S}),
    _t("dataset.copy", "required", "Copy a dataset or member.",
       {"sourceDataset": _S, "targetDataset": _S},
       {"sourceMember": _S, "targetMember": _S, "replace": _B}),
    _t("member.delete", "required", "Delete a PDS member.", _DSM),
    _t("member.rename", "required", "Rename a PDS member.", {**_DSM, "newMember": _S}),
    _t("job.submit", "required", "Submit JCL, inline or from a dataset.", {},
       {"jcl": _S, "dataset": _S}),
    _t("job.cancel", "required", "Cancel a running job.", _JOB, _JOBNAME),
    _t("job.purge", "required", "Purge a job from the spool.", _JOB, _JOBNAME),
    _t("job.hold", "required", "Hold a job so it does not run or print.", _JOB, _JOBNAME),
    _t("job.release", "required", "Release a held job.", _JOB, _JOBNAME),
    _t("job.changeClass", "required", "Move a job to another job class.",
       {**_JOB, "jobClass": {**_S, "description": "The new class, one character, e.g. A."}}, _JOBNAME),
    _t("dataset.recall", "required", "Recall a migrated dataset from archive storage (HRECALL).", _DS),
    _t("dataset.migrate", "required", "Migrate a dataset to archive storage (HMIGRATE).", _DS),
    _t("uss.write", "required", "Create or overwrite a z/OS UNIX text file.",
       {**_PATH, "content": _S}),
    _t("uss.create", "required", "Create an empty z/OS UNIX file or a directory.", _PATH,
       {"type": {**_S, "description": "file (default) or directory."},
        "mode": {**_S, "description": "Permissions as rwxr-xr-x (the default)."}}),
    _t("uss.delete", "required", "Delete a z/OS UNIX file or directory.", _PATH,
       {"recursive": {**_B, "description": "Also delete everything inside a directory."}}),
    _t("uss.rename", "required", "Move or rename a z/OS UNIX file or directory.",
       {**_PATH, "newPath": {**_S, "description": "Where it goes."}}),
    _t("uss.chmod", "required", "Change the permissions of a z/OS UNIX file or directory.",
       {**_PATH, "mode": {**_S, "description": "Octal permissions, e.g. 755."}},
       {"recursive": {**_B, "description": "Apply to everything inside a directory."}}),
    _t("tso.command", "required",
       "Run one TSO command and return its output (ALLOCATE, DELETE, RENAME, RACF commands...). "
       "The plan step must give the exact command. SUBMIT is refused: use job.submit.",
       _COMMAND, _EXCERPT),
    _t("console.command", "required",
       "Issue one MVS operator command and return the response. The plan step must give the "
       "exact command.",
       _COMMAND,
       {"consoleName": {**_S, "description": "EMCS console to use; the default console when omitted."},
        **_EXCERPT}),
]

# tool name -> ZoweSdkMainframeClient method
METHODS: dict[str, str] = {
    "profile.list": "list_profiles",
    "connection.verify": "verify_connection",
    "dataset.list": "list_datasets",
    "dataset.info": "get_dataset_info",
    "dataset.read": "read_dataset",
    "member.read": "read_member",
    "member.list": "list_members",
    "member.search": "search_members",
    "job.list": "list_jobs",
    "job.status": "get_job_status",
    "job.wait": "wait_for_job",
    "job.jcl": "get_job_jcl",
    "job.spool.list": "list_job_spool_files",
    "job.spool.read": "get_job_spool_content",
    "job.output": "get_job_output",
    "dataset.write": "write_dataset",
    "member.write": "write_member",
    "member.patch": "patch_member",
    "dataset.create": "create_dataset",
    "dataset.createLike": "create_dataset_like",
    "dataset.delete": "delete_dataset",
    "dataset.rename": "rename_dataset",
    "dataset.copy": "copy_dataset",
    "member.delete": "delete_member",
    "member.rename": "rename_member",
    "job.submit": "submit_job",
    "job.cancel": "cancel_job",
    "job.purge": "purge_job",
    "job.steps": "get_job_steps",
    "job.failed": "list_failed_jobs",
    "uss.list": "list_uss",
    "uss.read": "read_uss",
    "system.list": "list_systems",
    "tso.query": "tso_query",
    "job.hold": "hold_job",
    "job.release": "release_job",
    "job.changeClass": "change_job_class",
    "dataset.recall": "recall_dataset",
    "dataset.migrate": "migrate_dataset",
    "uss.write": "write_uss",
    "uss.create": "create_uss",
    "uss.delete": "delete_uss",
    "uss.rename": "rename_uss",
    "uss.chmod": "chmod_uss",
    "tso.command": "tso_command",
    "console.command": "console_command",
}


def list_tool_definitions() -> list[dict[str, Any]]:
    return [dict(d) for d in _DEFINITIONS]


def get_tool_definition(name: str) -> dict[str, Any] | None:
    for d in _DEFINITIONS:
        if d["name"] == name:
            return dict(d)
    return None
