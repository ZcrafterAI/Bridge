"""Dispatch layer. Real package's `executor.LocalToolExecutor`.

Contract, per this repo's tests and proxy.py:
  * `await execute(call)` where call = {"id", "name", "input", optional "approved"}
  * returns {"status": "ok", "data": ...} or {"status": "error", "error": {...}}
  * calls `logger.log(entry)` once per call, with the entry shape
    ActionLogSink consumes: id / tool / target / status / timestamp / summary
    / input / diffHash.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .contract import METHODS, get_tool_definition, list_tool_definitions


def _target(tool: str, tool_input: dict[str, Any]) -> str:
    """Human-readable object the call acted on — what shows in the audit log."""
    ds = tool_input.get("dataset") or tool_input.get("sourceDataset")
    mem = tool_input.get("member") or tool_input.get("sourceMember")
    if ds and mem:
        return f"{ds}({mem})"
    if ds:
        return str(ds)
    if tool_input.get("jobId"):
        return str(tool_input["jobId"])
    if tool_input.get("pattern"):
        return str(tool_input["pattern"])
    return tool


class LocalToolExecutor:
    def __init__(self, client: Any, logger: Any = None) -> None:
        self.client = client
        self.logger = logger

    def _log(self, call_id: str, tool: str, tool_input: dict, status: str,
             summary: str, diff_hash: str | None = None) -> None:
        if self.logger is None:
            return
        self.logger.log({
            "id": call_id,
            "tool": tool,
            "target": _target(tool, tool_input),
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "input": tool_input,
            **({"diffHash": diff_hash} if diff_hash else {}),
        })

    async def execute(self, call: dict[str, Any]) -> dict[str, Any]:
        tool = call.get("name", "")
        tool_input = dict(call.get("input") or {})
        call_id = call.get("id", "")

        definition = get_tool_definition(tool)
        if definition is None:
            self._log(call_id, tool, tool_input, "error", f"Unknown tool {tool}.")
            return {"status": "error",
                    "error": {"code": "UNKNOWN_TOOL", "message": f"No such tool: {tool}"}}

        # A mutating tool must never reach the client without the gate's
        # approval flag — the whole point of the workflow server.
        if definition["approval"] == "required" and not call.get("approved"):
            self._log(call_id, tool, tool_input, "error", f"{tool} called without approval.")
            return {"status": "error",
                    "error": {"code": "NOT_APPROVED",
                              "message": f"{tool} is a mutating tool and was not approved"}}

        # catalog search is answered here, not on the mainframe
        if tool == "zowe.tools.search":
            q = str(tool_input.get("query", "")).lower()
            hits = [{"name": d["name"], "description": d["description"], "approval": d["approval"]}
                    for d in list_tool_definitions()
                    if q in d["name"].lower() or q in d["description"].lower()]
            self._log(call_id, tool, tool_input, "ok", f"{len(hits)} tools matched {q!r}.")
            return {"status": "ok", "data": {"tools": hits}}

        if tool == "zowe.capabilities.list":
            want = str(tool_input.get("approval") or "").strip()
            caps = [{"name": d["name"], "approval": d["approval"],
                     "description": d["description"]}
                    for d in list_tool_definitions()
                    if not want or d["approval"] == want]
            self._log(call_id, tool, tool_input, "ok", f"{len(caps)} tools listed.")
            return {"status": "ok", "data": {"tools": caps}}

        method = getattr(self.client, METHODS[tool], None)
        if method is None:
            self._log(call_id, tool, tool_input, "error", f"{tool} unimplemented on client.")
            return {"status": "error",
                    "error": {"code": "UNIMPLEMENTED",
                              "message": f"Client has no handler for {tool}"}}

        diff_hash = None
        if tool_input.get("unifiedDiff"):
            diff_hash = hashlib.sha256(
                str(tool_input["unifiedDiff"]).encode()).hexdigest()[:16]

        try:
            data = await method(tool_input)
        except NotImplementedError as exc:
            self._log(call_id, tool, tool_input, "error", str(exc), diff_hash)
            return {"status": "error", "error": {"code": "UNSUPPORTED", "message": str(exc)}}
        except Exception as exc:  # surfaced to the agent, never swallowed
            msg = f"{type(exc).__name__}: {exc}"
            self._log(call_id, tool, tool_input, "error", msg, diff_hash)
            return {"status": "error", "error": {"code": "TOOL_FAILED", "message": msg}}

        self._log(call_id, tool, tool_input, "ok", f"{tool} completed.", diff_hash)
        return {"status": "ok", "data": data}
