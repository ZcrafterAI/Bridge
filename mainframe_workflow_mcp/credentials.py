from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from fastmcp.server.dependencies import get_http_headers
from . import config


class CredentialResolutionError(RuntimeError):
    pass


# Headers backend attaches per MCP call when CREDENTIAL_SOURCE=request_headers
# (see server.py) -- backend is the only service that ever holds a
# decrypted z/OSMF password; these travel for the duration of one call and
# are never persisted here. Mirrors anthropic.go's existing
# X-ZCrafter-Session-Id pattern for the redaction service, just
# backend->bridge instead of backend->redaction.
_HEADER_CONNECTION_ID = "x-zcrafter-connection-id"
_HEADER_HOST = "x-zcrafter-zosmf-host"
_HEADER_PORT = "x-zcrafter-zosmf-port"
_HEADER_USER = "x-zcrafter-zosmf-user"
_HEADER_PASSWORD = "x-zcrafter-zosmf-password"
_HEADER_PROTOCOL = "x-zcrafter-zosmf-protocol"
_HEADER_REJECT_UNAUTHORIZED = "x-zcrafter-zosmf-reject-unauthorized"


@dataclass(frozen=True)
class ZosmfCredentials:
    host: str
    port: int
    user: str
    password: str
    protocol: str = "https"
    reject_unauthorized: bool = True
    base_path: str | None = None

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"


def resolve_credentials(profile_name: str | None = None) -> ZosmfCredentials:
    if config.CREDENTIAL_SOURCE == "env":
        return _resolve_from_env()
    return _resolve_from_node_resolver(profile_name)


def resolve_from_request_headers() -> tuple[str, ZosmfCredentials]:
    """Resolve (connection_id, credentials) from the current MCP request's
    HTTP headers -- CREDENTIAL_SOURCE=request_headers mode, for multi-tenant
    deployments where each caller's z/OSMF target varies per request rather
    than being fixed for the whole process. See server.py's per-connection
    executor cache, keyed by the connection_id this returns.
    """
    headers = get_http_headers()
    connection_id = headers.get(_HEADER_CONNECTION_ID, "").strip()
    host = headers.get(_HEADER_HOST, "").strip()
    user = headers.get(_HEADER_USER, "").strip()
    password = headers.get(_HEADER_PASSWORD, "").strip()
    if not connection_id or not host or not user or not password:
        raise CredentialResolutionError(
            f"CREDENTIAL_SOURCE=request_headers requires {_HEADER_CONNECTION_ID}, "
            f"{_HEADER_HOST}, {_HEADER_USER} and {_HEADER_PASSWORD} on every MCP call"
        )
    reject_unauthorized = headers.get(_HEADER_REJECT_UNAUTHORIZED, "true").strip().lower() not in ("false", "0", "no")
    creds = ZosmfCredentials(
        host=host,
        port=int(headers.get(_HEADER_PORT, "443") or "443"),
        user=user,
        password=password,
        protocol=headers.get(_HEADER_PROTOCOL, "https") or "https",
        reject_unauthorized=reject_unauthorized,
        base_path=config.APIML_BASE_PATH or None,
    )
    return connection_id, creds


def _resolve_from_env() -> ZosmfCredentials:
    if not config.ZOSMF_HOST or not config.ZOSMF_USER or not config.ZOSMF_PASSWORD:
        raise CredentialResolutionError(
            "MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE=env requires "
            "MAINFRAME_WORKFLOW_ZOSMF_HOST, _USER and _PASSWORD to be set"
        )
    return ZosmfCredentials(
        host=config.ZOSMF_HOST,
        port=int(config.ZOSMF_PORT),
        user=config.ZOSMF_USER.strip(),
        password=config.ZOSMF_PASSWORD.strip(),
        protocol=config.ZOSMF_PROTOCOL,
        reject_unauthorized=config.ZOSMF_REJECT_UNAUTHORIZED,
        base_path=config.APIML_BASE_PATH or None,
    )


def _resolve_from_node_resolver(profile_name: str | None) -> ZosmfCredentials:
    args = ["node", str(config.CREDENTIAL_RESOLVER_PATH)]
    if profile_name:
        args.append(profile_name)
    proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise CredentialResolutionError(
            f"credential-resolver exited {proc.returncode}: {proc.stderr.strip()}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CredentialResolutionError(
            f"credential-resolver returned invalid JSON: {proc.stdout!r}"
        ) from exc
    try:
        return ZosmfCredentials(
            host=data["host"],
            port=int(data["port"]),
            user=str(data["user"]).strip(),
            password=str(data["password"]).strip(),
            protocol=data.get("protocol", "https"),
            reject_unauthorized=bool(data["rejectUnauthorized"]) if "rejectUnauthorized" in data else True,
            base_path=data.get("basePath") or None,
        )
    except KeyError as exc:
        raise CredentialResolutionError(f"missing field in resolver output: {exc}") from exc
