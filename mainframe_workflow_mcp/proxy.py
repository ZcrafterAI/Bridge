from __future__ import annotations
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4
from fastmcp.tools import Tool
from ._toolbox import LocalToolExecutor, list_tool_definitions
from .requests import RequestManager
from .action_log_sink import current_request_id

_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "number": int | float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _build_function(name: str, input_schema: dict[str, Any], impl: Callable[[dict[str, Any]], Awaitable[Any]]):
    # fastmcp derives both the advertised MCP schema AND the pydantic
    # validator used at call time from the real function signature (verified
    # during planning — a **kwargs handler with a fake __signature__ passes
    # fastmcp's own guard but then fails at call time with a pydantic
    # KeyError, because pydantic reads real __annotations__, not
    # __signature__). So this builds a real function with real named
    # parameters via exec(), which both fastmcp and pydantic introspect correctly.
    required = set(input_schema.get("required", []))
    properties = input_schema.get("properties", {})

    params_src = []
    annotations: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        py_type = _TYPE_MAP.get(prop_schema.get("type"), Any)
        if prop_name in required:
            annotations[prop_name] = py_type
            params_src.append(prop_name)
        else:
            annotations[prop_name] = Optional[py_type]
            params_src.append(f"{prop_name}=None")

    joined = ", ".join(params_src)
    src = (
        f"async def _handler(*, {joined}):\n    return await _impl(locals())\n"
        if joined
        else "async def _handler():\n    return await _impl({})\n"
    )
    namespace: dict[str, Any] = {"_impl": impl}
    exec(src, namespace)
    handler = namespace["_handler"]
    handler.__annotations__ = annotations
    handler.__name__ = name.replace(".", "_")
    return handler


async def _call_executor(
    executor: LocalToolExecutor, tool_name: str, tool_input: dict[str, Any], approved: bool | None = None,
) -> dict[str, Any]:
    call: dict[str, Any] = {"id": str(uuid4()), "name": tool_name, "input": tool_input}
    if approved is not None:
        call["approved"] = approved
    return await executor.execute(call)


def _make_readonly_impl(tool_name: str, executor: LocalToolExecutor):
    async def impl(kwargs: dict[str, Any]) -> dict[str, Any]:
        return await _call_executor(executor, tool_name, kwargs)
    return impl


def register_zcrafter_tools(mcp, request_manager: RequestManager, executor: LocalToolExecutor) -> None:
    for definition in list_tool_definitions():
        tool_name = definition["name"]
        input_schema = definition["inputSchema"]

        approval = definition["approval"]
        if approval == "never":
            impl = _make_readonly_impl(tool_name, executor)
            handler = _build_function(tool_name, input_schema, impl)
        elif approval == "required":
            impl = _make_mutating_impl(tool_name, request_manager, executor)
            schema_with_request_id = {
                **input_schema,
                "properties": {
                    **input_schema.get("properties", {}),
                    "request_id": {"type": "string", "description": "The mainframe_workflow_mcp request this action belongs to."},
                },
                "required": [*input_schema.get("required", []), "request_id"],
            }
            handler = _build_function(tool_name, schema_with_request_id, impl)
        else:
            raise ValueError(
                f"Unknown approval value {approval!r} for tool {tool_name!r} — refusing to guess whether it is mutating"
            )

        tool = Tool.from_function(handler, name=tool_name, description=definition["description"])
        mcp.add_tool(tool)


def _make_mutating_impl(tool_name: str, request_manager: RequestManager, executor: LocalToolExecutor):
    async def impl(kwargs: dict[str, Any]) -> dict[str, Any]:
        request_id = kwargs.pop("request_id")
        request = request_manager.get_request(request_id)
        if request is None:
            return {"status": "error", "error": {"code": "REQUEST_NOT_FOUND", "message": f"No such request: {request_id}"}}
        if request["status"] != "ACTIVE":
            return {"status": "error", "error": {"code": "REQUEST_NOT_ACTIVE", "message": f"Request {request_id} is {request['status']}, not ACTIVE"}}
        if request["phase"] not in ("PLAN_APPROVED", "EXECUTING"):
            return {
                "status": "error",
                "error": {
                    "code": "PLAN_NOT_APPROVED",
                    "message": f"Request {request_id}'s plan is not approved yet (phase={request['phase']})",
                },
            }

        token = current_request_id.set(request_id)
        try:
            result = await _call_executor(executor, tool_name, kwargs, approved=True)
        finally:
            current_request_id.reset(token)

        if result.get("status") == "ok" and request["phase"] == "PLAN_APPROVED":
            request_manager.mark_executing(request_id)
        return result
    return impl
