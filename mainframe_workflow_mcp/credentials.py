from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from . import config


class CredentialResolutionError(RuntimeError):
    pass


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
