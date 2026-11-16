"""Finding the mainframe sign-in without Node: environment variables, then the Zowe team
config with the password from the OS keychain."""
import base64
import json
import subprocess

import pytest
from mainframe_workflow_mcp import credentials
from mainframe_workflow_mcp.credentials import (
    CredentialResolutionError,
    from_environment,
    from_zowe_config,
    resolve_credentials,
)


def _config(home, body, name="zowe.config.json"):
    home.mkdir(parents=True, exist_ok=True)
    path = home / name
    path.write_text(json.dumps(body))
    return str(path)


TEAM = {
    "profiles": {
        "zosmf": {"type": "zosmf", "properties": {"port": 10443}, "secure": []},
        "base": {"type": "base", "properties": {"host": "zos.example.test", "rejectUnauthorized": False},
                 "secure": ["user", "password"]},
    },
    "defaults": {"zosmf": "zosmf", "base": "base"},
}


def _vault(path, **secrets):
    payload = {path: {f"profiles.base.properties.{k}": v for k, v in secrets.items()}}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return lambda service, account: encoded if (service, account) == ("Zowe", "secure_config_props") else None


def test_environment_variables_are_enough():
    creds = from_environment({
        "ZOWE_OPT_HOST": "zos.example.test", "ZOWE_OPT_USER": " IBMUSER ", "ZOWE_OPT_PASSWORD": "secret",
        "ZOWE_OPT_PORT": "10443", "ZOWE_OPT_REJECT_UNAUTHORIZED": "false", "ZOWE_OPT_BASE_PATH": "/ibmzosmf/api/v1",
    })
    assert (creds.host, creds.port, creds.user, creds.password) == ("zos.example.test", 10443, "IBMUSER", "secret")
    assert creds.reject_unauthorized is False and creds.base_path == "/ibmzosmf/api/v1"
    assert creds.protocol == "https"


def test_environment_needs_host_user_and_password():
    assert from_environment({"ZOWE_OPT_HOST": "h", "ZOWE_OPT_USER": "u"}) is None
    assert from_environment({}) is None
    defaults = from_environment({"ZOWE_OPT_HOST": "h", "ZOWE_OPT_USER": "u", "ZOWE_OPT_PASSWORD": "p"})
    assert defaults.port == 443 and defaults.reject_unauthorized is True


def test_team_config_with_the_password_in_the_keychain(tmp_path):
    home = tmp_path / "zowe"
    path = _config(home, TEAM)
    creds = from_zowe_config(None, home=home, cwd=tmp_path, keychain_get=_vault(path, user="IBMUSER", password="secret "))
    assert creds.base_url == "https://zos.example.test:10443"
    assert (creds.user, creds.password) == ("IBMUSER", "secret")
    assert creds.reject_unauthorized is False


def test_a_project_config_overrides_the_global_one(tmp_path):
    home, project = tmp_path / "zowe", tmp_path / "work" / "repo"
    path = _config(home, TEAM)
    _config(project, {"profiles": {"zosmf": {"properties": {"port": 443}}}})
    creds = from_zowe_config(
        None, home=home, cwd=project / "src" / "deep", keychain_get=_vault(path, user="U", password="P"),
    )
    assert creds.port == 443 and creds.host == "zos.example.test"


def test_the_older_one_entry_per_property_layout_still_works(tmp_path):
    home = tmp_path / "zowe"
    path = _config(home, TEAM)

    def keychain(service, account):
        if service == "Zowe-Secure-Credentials":
            return {f"{path}/profiles/base/properties/user": "IBMUSER",
                    f"{path}/profiles/base/properties/password": "secret"}.get(account)
        return None

    creds = from_zowe_config("zosmf", home=home, cwd=tmp_path, keychain_get=keychain)
    assert (creds.user, creds.password) == ("IBMUSER", "secret")


@pytest.mark.parametrize("profile, keychain, message", [
    ("nope", lambda s, a: None, 'profile "nope" not found'),
    (None, lambda s, a: None, "zowe config secure"),
])
def test_problems_say_what_to_run(tmp_path, profile, keychain, message):
    home = tmp_path / "zowe"
    _config(home, TEAM)
    with pytest.raises(CredentialResolutionError, match=message):
        from_zowe_config(profile, home=home, cwd=tmp_path, keychain_get=keychain)


def test_no_config_at_all_names_both_ways_out(tmp_path):
    with pytest.raises(CredentialResolutionError, match="zowe config init.*ZOWE_OPT_HOST"):
        from_zowe_config(None, home=tmp_path / "empty", cwd=tmp_path, keychain_get=lambda s, a: None)


def test_environment_wins_and_the_keychain_is_never_opened(monkeypatch):
    for key, value in (("HOST", "h"), ("USER", "u"), ("PASSWORD", "p")):
        monkeypatch.setenv(f"ZOWE_OPT_{key}", value)
    # conftest makes any keychain read fail the test, so reaching here proves none happened.
    assert resolve_credentials().host == "h"


def test_the_node_helper_is_the_fallback_when_it_is_built(monkeypatch):
    monkeypatch.setattr(credentials, "_node_resolver_available", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda args, capture_output, text, timeout: subprocess.CompletedProcess(
        args, 0, stdout=json.dumps({"host": "h", "port": 443, "user": "u", "password": "p"}), stderr="",
    ))
    assert resolve_credentials().host == "h"

    monkeypatch.setattr(credentials, "_node_resolver_available", lambda: False)
    with pytest.raises(CredentialResolutionError, match="Zowe config not found"):
        resolve_credentials()
