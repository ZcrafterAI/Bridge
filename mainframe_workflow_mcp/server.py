from __future__ import annotations
from fastmcp import FastMCP
from ._toolbox import LocalToolExecutor
from .credentials import resolve_credentials
from . import config
from .action_log_sink import ActionLogSink
from .clients.zowe_sdk import ZoweSdkMainframeClient
from .db import ActionLogStore
from .proxy import register_zcrafter_tools

mcp = FastMCP("mainframe-workflow")
_store = ActionLogStore(config.DB_PATH)


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
    register_zcrafter_tools(mcp, build_executor())
    mcp.run(
        transport=config.MCP_TRANSPORT,
        host=config.MCP_HOST,
        port=config.MCP_PORT,
        path=config.MCP_PATH,
    )


if __name__ == "__main__":
    main()
