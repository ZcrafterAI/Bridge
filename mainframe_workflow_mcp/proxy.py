from __future__ import annotations
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4
from fastmcp.tools import Tool
from mcp.types import ToolAnnotations
from ._toolbox import LocalToolExecutor, list_tool_definitions

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


def _make_impl(tool_name: str, executor: LocalToolExecutor):
    # Approval gating lives in backend now, one hop up from bridge (see
    # docs/architecture.md) — by the time a call reaches here it has already
    # been authorized, whether the tool's contract marks it "never" or
    # "required". Bridge just executes what it's asked and records the
    # outcome; it doesn't second-guess the caller.
    async def impl(kwargs: dict[str, Any]) -> dict[str, Any]:
        call = {"id": str(uuid4()), "name": tool_name, "input": kwargs, "approved": True}
        return await executor.execute(call)
    return impl


def register_zcrafter_tools(mcp, executor: LocalToolExecutor) -> None:
    for definition in list_tool_definitions():
        tool_name = definition["name"]
        input_schema = definition["inputSchema"]
        approval = definition["approval"]
        if approval not in ("never", "required"):
            raise ValueError(
                f"Unknown approval value {approval!r} for tool {tool_name!r} — refusing to guess whether it is mutating"
            )

        impl = _make_impl(tool_name, executor)
        handler = _build_function(tool_name, input_schema, impl)
        # Standard MCP hint, not a bespoke field: backend's tool dispatch
        # reads this to decide direct-call vs. approval-gate, so it has to
        # be the real annotation, not just the "approval" string in our own
        # tool catalog (which stays too, for zowe.tools.search/capabilities.list).
        tool_annotations = ToolAnnotations(
            readOnlyHint=approval == "never",
            destructiveHint=approval == "required",
        )
        tool = Tool.from_function(
            handler, name=tool_name, description=definition["description"], annotations=tool_annotations,
        )
        mcp.add_tool(tool)
