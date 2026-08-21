from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MAINFRAME_WORKFLOW_DB_PATH", PROJECT_ROOT / "mainframe_workflow_mcp" / "state.db"))
ARCHIVE_DIR = Path(os.environ.get("MAINFRAME_WORKFLOW_ARCHIVE_DIR", PROJECT_ROOT / "mainframe_workflow_mcp" / "archive"))
IDLE_DAYS = int(os.environ.get("MAINFRAME_WORKFLOW_IDLE_DAYS", "14"))
RETENTION_DAYS = int(os.environ.get("MAINFRAME_WORKFLOW_RETENTION_DAYS", "90"))
ZOWE_PROFILE = os.environ.get("MAINFRAME_WORKFLOW_ZOWE_PROFILE", "default")
HTTP_TIMEOUT_SECONDS = float(os.environ.get("MAINFRAME_WORKFLOW_HTTP_TIMEOUT_SECONDS", "30"))
APIML_BASE_PATH = os.environ.get("MAINFRAME_WORKFLOW_APIML_BASE_PATH", "")
CREDENTIAL_RESOLVER_PATH = Path(
    os.environ.get(
        "MAINFRAME_WORKFLOW_CREDENTIAL_RESOLVER",
        PROJECT_ROOT / "credential-resolver" / "dist" / "resolver.js",
    )
)
