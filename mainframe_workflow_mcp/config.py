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
