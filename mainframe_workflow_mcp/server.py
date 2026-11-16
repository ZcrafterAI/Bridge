from __future__ import annotations
import threading
from typing import Any
from fastmcp import Context, FastMCP
from ._toolbox import LocalToolExecutor
from .approval import ApprovalBroker
from .credentials import resolve_credentials
from . import config
from .action_log_sink import ActionLogSink
from .clients.zowe_sdk import ZoweSdkMainframeClient
from .db import RequestStore
from .lifecycle import archive_sweep, idle_sweep
from .plan_steps import PlanStepError
from .proxy import register_zcrafter_tools
from .requests import RequestManager

mcp = FastMCP(
    "mainframe-workflow",
    instructions=(
        "Tools for an IBM z/OS mainframe. Reading (datasets, members, z/OS UNIX files, jobs, "
        "spool) needs no approval. Anything that changes the system needs a request: "
        "start_request, draft_spec, approve_spec, draft_plan with the list of steps, "
        "approve_plan. approve_spec and approve_plan ask the person directly; you cannot "
        "approve for them. After approval, a change runs only if it matches a step of the "
        "approved plan."
    ),
)
_store = RequestStore(config.DB_PATH)
_request_manager = RequestManager(_store, protected=config.PROTECTED_DATASETS)
_broker = ApprovalBroker(
    _store, mode=config.APPROVAL_MODE, wait_seconds=config.APPROVAL_WAIT_SECONDS,
)


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
async def approve_spec(request_id: str, ctx: Context) -> dict:
    """Ask the person to approve the latest spec revision. The server shows them the spec and
    waits for their answer; this call cannot approve anything by itself. If it returns
    WAITING_FOR_PERSON, tell the person an approval is waiting and call it again."""
    return await _ask_person(ctx, request_id, "spec")


@mcp.tool()
def draft_plan(request_id: str, content: str, steps: list[dict[str, Any]] | None = None) -> dict:
    """Write a new plan revision. Requires an approved spec. Editing an approved plan un-approves it.

    `steps` lists every change the plan makes, one object per mutating tool call:
    {"tool": "member.write", "args": {"dataset": "HLQ.SRC", "member": "PAYCALC"}}.
    Each step must name its target (dataset, member, path, command, job id). Include
    content, unifiedDiff or jcl when you know the exact text: the person then approves
    exactly that, and the call must send exactly that. Add "times": N when one step has to
    run more than once. After approval only calls that match a step run; anything else is
    refused, so a plan with no steps can change nothing."""
    try:
        return _request_manager.draft_plan(request_id, content, steps)
    except PlanStepError as exc:
        return {"status": "error", "error": {"code": "INVALID_PLAN_STEPS", "message": str(exc)}}


@mcp.tool()
async def approve_plan(request_id: str, ctx: Context) -> dict:
    """Ask the person to approve the latest plan revision and its steps. The server shows them
    the plan and waits for their answer; this call cannot approve anything by itself. Once
    approved, the mutating tools run for this request, but only the steps the plan lists. If it
    returns WAITING_FOR_PERSON, tell the person an approval is waiting and call it again."""
    return await _ask_person(ctx, request_id, "plan")


async def _ask_person(ctx: Context, request_id: str, kind: str) -> dict:
    revision = _request_manager.revision_awaiting_approval(request_id, kind)
    decision = await _broker.ask(ctx, request_id, kind, revision["version"])
    if decision.status == "ask-client":
        # The client shows the person its own prompt and calls this tool again with the answer.
        return decision.payload
    if decision.status == "approved":
        record = _request_manager.approve_spec if kind == "spec" else _request_manager.approve_plan
        return {**record(request_id, version=revision["version"]), "approved_via": decision.via}
    phase = (_request_manager.get_request(request_id) or {}).get("phase")
    if decision.status == "rejected":
        return {
            "request_id": request_id,
            "status": "REJECTED",
            "phase": phase,
            "message": (
                f"The person rejected this {kind}. Ask what they want changed, write a new "
                f"revision, then ask again. The same revision will not be approved."
            ),
        }
    return {
        "request_id": request_id,
        "status": "WAITING_FOR_PERSON",
        "phase": phase,
        "message": f"{decision.detail} Tell them an approval is waiting, then call approve_{kind} again.",
    }


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
    """Return full detail for a request: phase, status, clarifications, spec/plan text, the plan's steps and which are left, approvals, recent actions."""
    return _request_manager.get_request_status(request_id)


@mcp.tool()
def list_requests(status: str = "ACTIVE") -> list:
    """List requests filtered by status (default ACTIVE)."""
    return _request_manager.list_requests(status)


def _build_client() -> ZoweSdkMainframeClient:
    creds = resolve_credentials(config.ZOWE_PROFILE)
    connection = {
        "host_url": f"{creds.host}:{creds.port}",
        "user": creds.user,
        "password": creds.password,
        "ssl_verification": creds.reject_unauthorized,
        "protocol": creds.protocol,
    }
    return ZoweSdkMainframeClient(
        config.ZOWE_PROFILE,
        connection,
        timeout_seconds=config.HTTP_TIMEOUT_SECONDS,
        base_path=config.APIML_BASE_PATH or creds.base_path or "",
        tso_account=config.TSO_ACCOUNT,
    )


class _LazyClient:
    """The z/OSMF client, built the first time a tool needs the mainframe.

    The server used to read the Zowe profile at startup and die when there was none, which
    looked like a broken install. It now starts, lists its tools, and a tool call reports the
    missing profile in words the person can act on. A failure is not remembered, so fixing the
    profile works without a restart."""

    def __init__(self, factory) -> None:
        self._factory = factory
        self._client: Any = None
        self._lock = threading.Lock()

    @property
    def profile_name(self) -> str:
        return config.ZOWE_PROFILE

    async def list_profiles(self, input: dict[str, Any]) -> dict[str, Any]:
        return {"profiles": [config.ZOWE_PROFILE], "default": config.ZOWE_PROFILE}

    def _get(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = self._factory()
            return self._client

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return getattr(self._get(), name)
        except AttributeError:
            raise
        except Exception as exc:
            error = exc

            async def _unavailable(input: dict[str, Any]) -> dict[str, Any]:
                raise RuntimeError(
                    f"Could not connect with Zowe profile {config.ZOWE_PROFILE!r}: {error}. "
                    "Check `zowe zosmf check status`, then try again."
                )

            return _unavailable


def build_executor() -> LocalToolExecutor:
    return LocalToolExecutor(_LazyClient(_build_client), ActionLogSink(_store))


def main() -> None:
    idle_sweep(_store, config.IDLE_DAYS)
    archive_sweep(_store, config.ARCHIVE_DIR, config.RETENTION_DAYS)
    register_zcrafter_tools(
        mcp, _request_manager, build_executor(),
        read_only=config.READ_ONLY, protected=config.PROTECTED_DATASETS,
    )
    mcp.run()


if __name__ == "__main__":
    main()
