"""Where the mainframe address, user and password come from.

Tried in order:

1. Environment variables, named the way Zowe CLI names them (ZOWE_OPT_HOST, ZOWE_OPT_USER,
   ZOWE_OPT_PASSWORD...). For containers, CI and anyone without a Zowe profile.
2. Your Zowe team config (~/.zowe/zowe.config.json and project configs), with the password
   read from the operating system's keychain, where `zowe config secure` put it.
3. The Node helper in credential-resolver/, when it has been built. Kept for installs that
   already rely on it.

Nothing read here is written anywhere.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

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


def _from_properties(data: Mapping[str, Any]) -> ZosmfCredentials:
    try:
        return ZosmfCredentials(
            host=str(data["host"]),
            port=int(data.get("port") or 443),
            user=str(data["user"]).strip(),
            password=str(data["password"]).strip(),
            protocol=str(data.get("protocol") or "https"),
            reject_unauthorized=_truthy(data["rejectUnauthorized"]) if "rejectUnauthorized" in data else True,
            base_path=data.get("basePath") or None,
        )
    except KeyError as exc:
        raise CredentialResolutionError(f"missing field in resolver output: {exc}") from exc


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


# ---------------------------------------------------------------- 1. environment

def from_environment(env: Mapping[str, str]) -> ZosmfCredentials | None:
    """Credentials from ZOWE_OPT_* variables, or None when they are not all set."""
    host, user, password = (env.get(f"ZOWE_OPT_{k}", "").strip() for k in ("HOST", "USER", "PASSWORD"))
    if not (host and user and password):
        return None
    data: dict[str, Any] = {"host": host, "user": user, "password": password}
    for key, name in (("port", "PORT"), ("protocol", "PROTOCOL"), ("basePath", "BASE_PATH"),
                      ("rejectUnauthorized", "REJECT_UNAUTHORIZED")):
        value = env.get(f"ZOWE_OPT_{name}", "").strip()
        if value:
            data[key] = value
    return _from_properties(data)


# ---------------------------------------------------------------- 2. Zowe team config

def zowe_home(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("ZOWE_CLI_HOME") or Path.home() / ".zowe")


def _keychain_get(service: str, account: str) -> str | None:
    """One secret from the operating system's keychain. Tests replace this."""
    import keyring  # imported late: reading a keychain is the last thing tried

    try:
        return keyring.get_password(service, account)
    except Exception as exc:  # no keychain on this machine, or it is locked
        raise CredentialResolutionError(f"could not read the OS keychain: {exc}") from exc


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CredentialResolutionError(f"could not read {path}: {exc}") from exc
    return loaded if isinstance(loaded, dict) else None


def _project_config_dir(start: Path) -> Path | None:
    current = start.resolve()
    while True:
        if (current / "zowe.config.json").is_file() or (current / "zowe.config.user.json").is_file():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _merge(lower: dict[str, Any], higher: dict[str, Any]) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    for name in {*(lower.get("profiles") or {}), *(higher.get("profiles") or {})}:
        low = (lower.get("profiles") or {}).get(name) or {}
        high = (higher.get("profiles") or {}).get(name) or {}
        profiles[name] = {
            "type": high.get("type") or low.get("type"),
            "properties": {**(low.get("properties") or {}), **(high.get("properties") or {})},
            "secure": list(dict.fromkeys([*(low.get("secure") or []), *(high.get("secure") or [])])),
        }
    return {"profiles": profiles, "defaults": {**(lower.get("defaults") or {}), **(higher.get("defaults") or {})}}


def load_team_config(home: Path, cwd: Path) -> tuple[dict[str, Any], list[str]]:
    """The merged Zowe config and the files it came from, lowest priority first."""
    files = [home / "zowe.config.json", home / "zowe.config.user.json"]
    project = _project_config_dir(cwd)
    if project is not None and project != home:
        files += [project / "zowe.config.json", project / "zowe.config.user.json"]
    merged: dict[str, Any] = {"profiles": {}, "defaults": {}}
    used: list[str] = []
    for file in files:
        loaded = _read_json(file)
        if loaded is None:
            continue
        used.append(str(file))
        merged = _merge(merged, loaded)
    if not used:
        raise CredentialResolutionError(
            f"Zowe config not found under {home} or the project directory. Run `zowe config init`, "
            "or set ZOWE_OPT_HOST, ZOWE_OPT_USER and ZOWE_OPT_PASSWORD."
        )
    return merged, used


def _secure_vault(keychain_get: Callable[[str, str], str | None]) -> dict[str, Any]:
    """Zowe keeps every secure property in one keychain entry, as base64 JSON keyed by config file."""
    raw = keychain_get("Zowe", "secure_config_props")
    if not raw:
        return {}
    for decode in (lambda text: base64.b64decode(text).decode("utf-8"), lambda text: text):
        try:
            parsed = json.loads(decode(raw))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def from_zowe_config(
    profile_name: str | None,
    *,
    home: Path | None = None,
    cwd: Path | None = None,
    keychain_get: Callable[[str, str], str | None] | None = None,
) -> ZosmfCredentials:
    keychain_get = keychain_get or _keychain_get
    merged, files = load_team_config(home or zowe_home(), cwd or Path.cwd())
    defaults = merged.get("defaults") or {}
    name = profile_name or defaults.get("zosmf") or ""
    profile = (merged.get("profiles") or {}).get(name)
    if not name or profile is None:
        raise CredentialResolutionError(
            f'z/OSMF profile "{name}" not found in Zowe config. Run `zowe config list profiles`, '
            "then set MAINFRAME_WORKFLOW_ZOWE_PROFILE."
        )
    base_name = defaults.get("base")
    base = (merged.get("profiles") or {}).get(base_name) if base_name else None
    properties: dict[str, Any] = {**((base or {}).get("properties") or {}), **(profile.get("properties") or {})}
    secure = list(dict.fromkeys([*((base or {}).get("secure") or []), *(profile.get("secure") or [])]))
    lookup = [n for n in (name, base_name) if n]

    vault: dict[str, Any] | None = None
    for field in secure:
        if properties.get(field) not in (None, ""):
            continue
        if vault is None:
            vault = _secure_vault(keychain_get)
        value = None
        for file in files:
            bucket = vault.get(file) or {}
            for candidate in lookup:
                found = bucket.get(f"profiles.{candidate}.properties.{field}")
                if isinstance(found, str) and found:
                    value = found
                    break
            if value:
                break
        if value is None:  # an older layout: one keychain entry per property
            for file in files:
                for candidate in lookup:
                    value = keychain_get(
                        "Zowe-Secure-Credentials", f"{file}/profiles/{candidate}/properties/{field}",
                    )
                    if value:
                        break
                if value:
                    break
        if value:
            properties[field] = value

    if properties.get("password") in (None, "") and properties.get("tokenValue"):
        properties["password"] = properties["tokenValue"]
    if not (properties.get("host") and properties.get("user") and properties.get("password")):
        raise CredentialResolutionError(
            f'Zowe profile "{name}" is missing host, user or password after the keychain lookup. '
            "Run `zowe config secure`, or set ZOWE_OPT_HOST, ZOWE_OPT_USER and ZOWE_OPT_PASSWORD."
        )
    return _from_properties(properties)


# ---------------------------------------------------------------- 3. the Node helper

def from_node_resolver(profile_name: str | None = None) -> ZosmfCredentials:
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
    return _from_properties(data)


def _node_resolver_available() -> bool:
    return config.CREDENTIAL_RESOLVER_PATH.is_file() and shutil.which("node") is not None


def resolve_credentials(profile_name: str | None = None) -> ZosmfCredentials:
    from_env = from_environment(os.environ)
    if from_env is not None:
        return from_env
    try:
        return from_zowe_config(profile_name)
    except CredentialResolutionError as first:
        if not _node_resolver_available():
            raise
        try:
            return from_node_resolver(profile_name)
        except CredentialResolutionError as second:
            raise CredentialResolutionError(f"{first} (Node helper: {second})") from second
