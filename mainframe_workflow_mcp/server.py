from __future__ import annotations
import threading
from collections import OrderedDict
from fastmcp import FastMCP
from ._toolbox import LocalToolExecutor
from .credentials import ZosmfCredentials, resolve_credentials, resolve_from_request_headers
from . import config
from .action_log_sink import ActionLogSink
from .clients.zowe_sdk import ZoweSdkMainframeClient
from .db import ActionLogStore
from .proxy import register_zcrafter_tools

mcp = FastMCP("mainframe-workflow")
_store = ActionLogStore(config.DB_PATH)

# CREDENTIAL_SOURCE=request_headers (multi-tenant): each MCP call carries
# its own connection's credentials as headers (see credentials.py), so
# there's no single process-wide executor -- a small bounded cache keyed
# by the connection_id backend generates avoids rebuilding a
# ZoweSdkMainframeClient on every single call. Backend guarantees this ID
# is unique per connection (derived from mainframe_connections.id, never
# user-suppliable), so cache collisions can't leak one connection's
# executor to another.
_MAX_CACHED_CONNECTIONS = 32
_connection_cache: "OrderedDict[str, LocalToolExecutor]" = OrderedDict()
_connection_cache_lock = threading.Lock()


def build_executor(profile_name: str | None = None, creds: ZosmfCredentials | None = None) -> LocalToolExecutor:
    if creds is None:
        creds = resolve_credentials(config.ZOWE_PROFILE)
    profile = profile_name or config.ZOWE_PROFILE
    connection = {
        "host_url": f"{creds.host}:{creds.port}",
        "user": creds.user,
        "password": creds.password,
        "ssl_verification": creds.reject_unauthorized,
        "protocol": creds.protocol,
    }
    client = ZoweSdkMainframeClient(
        profile,
        connection,
        timeout_seconds=config.HTTP_TIMEOUT_SECONDS,
        base_path=config.APIML_BASE_PATH or creds.base_path or "",
    )
    return LocalToolExecutor(client, ActionLogSink(_store))


def get_executor_for_request() -> LocalToolExecutor:
    """Executor provider for CREDENTIAL_SOURCE=request_headers -- resolves
    which connection this specific MCP call is for from its HTTP headers,
    reusing a cached ZoweSdkMainframeClient when one already exists for
    that connection rather than reconnecting every call.

    Deliberately does NOT tie the client's profile_name to connection_id:
    `profileName` in a tool call's arguments is set by the model (from the
    tool's schema/description, typically after calling profile.list), not
    directly by backend, so requiring it to match connection_id would mean
    backend rewriting every tool call's arguments before forwarding.
    Multi-tenancy correctness lives entirely in the connection_id header
    and this cache; profile_name stays the same generic label every
    connection uses, same as single-tenant env mode.
    """
    connection_id, creds = resolve_from_request_headers()
    with _connection_cache_lock:
        cached = _connection_cache.get(connection_id)
        if cached is not None:
            _connection_cache.move_to_end(connection_id)
            return cached

        executor = build_executor(creds=creds)
        _connection_cache[connection_id] = executor
        if len(_connection_cache) > _MAX_CACHED_CONNECTIONS:
            _connection_cache.popitem(last=False)  # evict least-recently-used
        return executor


def main() -> None:
    if config.CREDENTIAL_SOURCE == "request_headers":
        register_zcrafter_tools(mcp, get_executor_for_request)
    else:
        # env/resolver modes: one credential set for the whole process,
        # resolved once at startup exactly as before -- get_executor just
        # returns that same fixed instance on every call.
        fixed_executor = build_executor()
        register_zcrafter_tools(mcp, lambda: fixed_executor)

    mcp.run(
        transport=config.MCP_TRANSPORT,
        host=config.MCP_HOST,
        port=config.MCP_PORT,
        path=config.MCP_PATH,
    )


if __name__ == "__main__":
    main()
