from __future__ import annotations
from fastmcp import FastMCP
from ._toolbox import LocalToolExecutor
from .credentials import resolve_credentials
from . import config
from .action_log_sink import ActionLogSink
from .clients.zowe_sdk import ZoweSdkMainframeClient
from .db import RequestStore
from .lifecycle import archive_sweep, idle_sweep
from .proxy import register_zcrafter_tools
from .requests import RequestManager

mcp = FastMCP("mainframe-workflow")
_store = RequestStore(config.DB_PATH)
_request_manager = RequestManager(_store)


@mcp.tool()
def start_request(raw_request: str) -> dict:
    """Begin a new mainframe request. Phase starts at CLARIFYING."""
    return _request_manager.start_request(raw_request)


@mcp.tool()
def record_clarification(request_id: str, question: str, answer: str) -> dict:
    """Log one clarifying question/answer pair against an active request."""
    return _request_manager.record_clarification(request_id, question, answer)


@mcp.tool()
def draft_spec(request_id: str, content: str) -> dict:
    """Write a new spec revision. Editing an already-approved spec un-approves it (and any approved plan)."""
    return _request_manager.draft_spec(request_id, content)


@mcp.tool()
def approve_spec(request_id: str) -> dict:
    """Approve the latest spec revision. Only call this immediately after the user explicitly approves it in chat."""
    return _request_manager.approve_spec(request_id)


@mcp.tool()
def draft_plan(request_id: str, content: str) -> dict:
    """Write a new implementation plan revision. Requires an approved spec. Editing an approved plan un-approves it."""
    return _request_manager.draft_plan(request_id, content)


@mcp.tool()
def approve_plan(request_id: str) -> dict:
    """Approve the latest plan revision, unlocking mutating mainframe tools for this request. Only call after explicit user approval."""
    return _request_manager.approve_plan(request_id)


@mcp.tool()
def cancel_request(request_id: str, reason: str) -> dict:
    """Abandon an active request from any phase. Fails if the request is already ABANDONED or COMPLETED."""
    return _request_manager.cancel_request(request_id, reason)


@mcp.tool()
def complete_request(request_id: str) -> dict:
    """Mark a request completed once its work is done. Requires an approved plan."""
    return _request_manager.complete_request(request_id)


@mcp.tool()
def get_request_status(request_id: str) -> dict:
    """Return full detail for a request: phase, status, clarifications, spec/plan text, approvals, recent actions."""
    return _request_manager.get_request_status(request_id)


@mcp.tool()
def list_requests(status: str = "ACTIVE") -> list:
    """List requests filtered by status (default ACTIVE)."""
    return _request_manager.list_requests(status)


def build_executor() -> LocalToolExecutor:
    creds = resolve_credentials(config.ZOWE_PROFILE)
    connection = {
        "host_url": f"{creds.host}:{creds.port}",
        "user": creds.user,
        "password": creds.password,
        "ssl_verification": creds.reject_unauthorized,
        "protocol": creds.protocol,
    }
    client = ZoweSdkMainframeClient(
        config.ZOWE_PROFILE,
        connection,
        timeout_seconds=config.HTTP_TIMEOUT_SECONDS,
        base_path=config.APIML_BASE_PATH or creds.base_path or "",
    )
    return LocalToolExecutor(client, ActionLogSink(_store))


def main() -> None:
    idle_sweep(_store, config.IDLE_DAYS)
    archive_sweep(_store, config.ARCHIVE_DIR, config.RETENTION_DAYS)
    register_zcrafter_tools(mcp, _request_manager, build_executor())
    mcp.run(
        transport=config.MCP_TRANSPORT,
        host=config.MCP_HOST,
        port=config.MCP_PORT,
        path=config.MCP_PATH,
    )


if __name__ == "__main__":
    main()
