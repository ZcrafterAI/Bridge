from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _data_dir(beside_code: Path | None = None) -> Path:
    """Where requests and the audit log are kept. A checkout that already has its store
    beside the code keeps using it; an installed package uses a folder in the home directory,
    never its own install location."""
    beside_code = beside_code or PROJECT_ROOT / "mainframe_workflow_mcp"
    if (beside_code / "state.db").is_file():
        return beside_code
    return Path(os.environ.get("MAINFRAME_WORKFLOW_HOME") or Path.home() / ".zcrafter-bridge")


DB_PATH = Path(os.environ.get("MAINFRAME_WORKFLOW_DB_PATH") or _data_dir() / "state.db")
ARCHIVE_DIR = Path(os.environ.get("MAINFRAME_WORKFLOW_ARCHIVE_DIR") or _data_dir() / "archive")
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


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


# How a person approves a spec or a plan:
#   auto      the AI client's own prompt when it has one, else a page in the browser
#   prompt    the AI client's prompt only
#   browser   a page on this machine only
#   terminal  `zcrafter-bridge approve`, for machines with no browser
#   unsafe-agent  the agent's own call counts as approval. Nobody is asked. Test systems only.
APPROVAL_MODE = os.environ.get("MAINFRAME_WORKFLOW_APPROVAL", "auto").strip().lower() or "auto"
APPROVAL_WAIT_SECONDS = float(os.environ.get("MAINFRAME_WORKFLOW_APPROVAL_WAIT_SECONDS", "60"))
# No mutating tool is offered at all.
READ_ONLY = _flag("MAINFRAME_WORKFLOW_READ_ONLY")
# Dataset patterns nothing may write to, e.g. "SYS1.**,*.PROD.**".
PROTECTED_DATASETS = _list("MAINFRAME_WORKFLOW_PROTECTED_DATASETS")
# Account number for the TSO address space on z/OSMF without the one-request TSO interface.
TSO_ACCOUNT = os.environ.get("MAINFRAME_WORKFLOW_TSO_ACCOUNT", "").strip()
