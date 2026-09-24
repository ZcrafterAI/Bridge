from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MAINFRAME_WORKFLOW_DB_PATH", PROJECT_ROOT / "mainframe_workflow_mcp" / "state.db"))
ZOWE_PROFILE = os.environ.get("MAINFRAME_WORKFLOW_ZOWE_PROFILE", "default")
HTTP_TIMEOUT_SECONDS = float(os.environ.get("MAINFRAME_WORKFLOW_HTTP_TIMEOUT_SECONDS", "30"))
APIML_BASE_PATH = os.environ.get("MAINFRAME_WORKFLOW_APIML_BASE_PATH", "")

# Streamable HTTP transport: bridge runs as a network service reached by
# backend's MCP client, not as a local stdio subprocess.
MCP_TRANSPORT = os.environ.get("MAINFRAME_WORKFLOW_MCP_TRANSPORT", "http")
MCP_HOST = os.environ.get("MAINFRAME_WORKFLOW_MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("MAINFRAME_WORKFLOW_MCP_PORT", "8000"))
MCP_PATH = os.environ.get("MAINFRAME_WORKFLOW_MCP_PATH", "/mcp")
CREDENTIAL_RESOLVER_PATH = Path(
    os.environ.get(
        "MAINFRAME_WORKFLOW_CREDENTIAL_RESOLVER",
        PROJECT_ROOT / "credential-resolver" / "dist" / "resolver.js",
    )
)

# Three credential sources:
#   "resolver" (default) — shells out to credential-resolver, which reads a
#       local Zowe team config + the OS keychain. Fine for a developer's own
#       machine; there is no OS keychain inside a container.
#   "env" — reads ZOSMF_* below directly, meant for a single-tenant
#       KinD/container deployment, where these come from a mounted K8s
#       Secret rather than a real env file. One credential set for the
#       whole process, resolved once at startup.
#   "request_headers" — multi-tenant: each MCP call carries its own
#       connection's credentials as HTTP headers (see credentials.py's
#       resolve_from_request_headers and server.py's per-connection
#       executor cache), since backend now supports more than one z/OSMF
#       target concurrently. ZOSMF_* below are unused in this mode.
CREDENTIAL_SOURCE = os.environ.get("MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE", "resolver")
ZOSMF_HOST = os.environ.get("MAINFRAME_WORKFLOW_ZOSMF_HOST", "")
ZOSMF_PORT = os.environ.get("MAINFRAME_WORKFLOW_ZOSMF_PORT", "443")
ZOSMF_USER = os.environ.get("MAINFRAME_WORKFLOW_ZOSMF_USER", "")
ZOSMF_PASSWORD = os.environ.get("MAINFRAME_WORKFLOW_ZOSMF_PASSWORD", "")
ZOSMF_PROTOCOL = os.environ.get("MAINFRAME_WORKFLOW_ZOSMF_PROTOCOL", "https")
ZOSMF_REJECT_UNAUTHORIZED = os.environ.get(
    "MAINFRAME_WORKFLOW_ZOSMF_REJECT_UNAUTHORIZED", "true"
).strip().lower() not in ("false", "0", "no")
