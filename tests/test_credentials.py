import json
import subprocess
import pytest
from mainframe_workflow_mcp import config, credentials
from mainframe_workflow_mcp.credentials import resolve_credentials, resolve_from_request_headers, CredentialResolutionError

# These tests exercise the "resolver" path specifically and must not depend
# on whatever CREDENTIAL_SOURCE happens to be set in the developer's real
# .env (e.g. "env", once real Xplore credentials are configured there).
@pytest.fixture(autouse=True)
def _resolver_source(monkeypatch):
    monkeypatch.setattr(config, "CREDENTIAL_SOURCE", "resolver")

def test_resolve_credentials_parses_resolver_output(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({
                "host": "xplore.example.com", "port": 443,
                "user": "IBMUSER", "password": "secret", "protocol": "https",
                "rejectUnauthorized": False, "basePath": "/ibmzosmf/api/v1",
            }), stderr="",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)
    creds = resolve_credentials()
    assert creds.host == "xplore.example.com"
    assert creds.port == 443
    assert creds.base_url == "https://xplore.example.com:443"
    assert creds.reject_unauthorized is False
    assert creds.base_path == "/ibmzosmf/api/v1"

def test_resolve_credentials_raises_on_nonzero_exit(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="profile not found")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(CredentialResolutionError, match="profile not found"):
        resolve_credentials()

def test_resolve_credentials_raises_on_invalid_json(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        return subprocess.CompletedProcess(args, 0, stdout="not json", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(CredentialResolutionError, match="invalid JSON"):
        resolve_credentials()

def test_resolve_credentials_passes_profile_name(monkeypatch):
    captured = {}
    def fake_run(args, capture_output, text, timeout):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
            "host": "h", "port": 443, "user": "u", "password": "p",
        }), stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    resolve_credentials("myprofile")
    assert captured["args"][-1] == "myprofile"


def test_resolve_credentials_strips_whitespace_on_secrets(monkeypatch):
    def fake_run(args, capture_output, text, timeout):
        return subprocess.CompletedProcess(
            args, 0, stdout=json.dumps({
                "host": "xplore.example.com", "port": 443,
                "user": " IBMUSER ", "password": " secret", "protocol": "https",
            }), stderr="",
        )
    monkeypatch.setattr(subprocess, "run", fake_run)
    creds = resolve_credentials()
    assert creds.user == "IBMUSER"
    assert creds.password == "secret"


def test_resolve_credentials_from_env_when_source_is_env(monkeypatch):
    monkeypatch.setattr(config, "CREDENTIAL_SOURCE", "env")
    monkeypatch.setattr(config, "ZOSMF_HOST", "xplore.example.com")
    monkeypatch.setattr(config, "ZOSMF_PORT", "10443")
    monkeypatch.setattr(config, "ZOSMF_USER", " IBMUSER ")
    monkeypatch.setattr(config, "ZOSMF_PASSWORD", " secret ")
    monkeypatch.setattr(config, "ZOSMF_PROTOCOL", "https")
    monkeypatch.setattr(config, "ZOSMF_REJECT_UNAUTHORIZED", False)
    monkeypatch.setattr(config, "APIML_BASE_PATH", "/ibmzosmf/api/v1")

    creds = resolve_credentials()

    assert creds.host == "xplore.example.com"
    assert creds.port == 10443
    assert creds.user == "IBMUSER"
    assert creds.password == "secret"
    assert creds.reject_unauthorized is False
    assert creds.base_path == "/ibmzosmf/api/v1"


def test_resolve_credentials_from_env_never_shells_out(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("env credential source must not invoke the node resolver")
    monkeypatch.setattr(subprocess, "run", fail_run)
    monkeypatch.setattr(config, "CREDENTIAL_SOURCE", "env")
    monkeypatch.setattr(config, "ZOSMF_HOST", "xplore.example.com")
    monkeypatch.setattr(config, "ZOSMF_USER", "IBMUSER")
    monkeypatch.setattr(config, "ZOSMF_PASSWORD", "secret")

    resolve_credentials()


def test_resolve_credentials_from_env_raises_when_incomplete(monkeypatch):
    monkeypatch.setattr(config, "CREDENTIAL_SOURCE", "env")
    monkeypatch.setattr(config, "ZOSMF_HOST", "")
    monkeypatch.setattr(config, "ZOSMF_USER", "")
    monkeypatch.setattr(config, "ZOSMF_PASSWORD", "")

    with pytest.raises(CredentialResolutionError, match="ZOSMF_HOST"):
        resolve_credentials()


# --- resolve_from_request_headers (CREDENTIAL_SOURCE=request_headers, multi-tenant) ---

def _headers(**overrides):
    base = {
        "x-zcrafter-connection-id": "conn-1",
        "x-zcrafter-zosmf-host": "xplore.example.com",
        "x-zcrafter-zosmf-port": "10443",
        "x-zcrafter-zosmf-user": "IBMUSER",
        "x-zcrafter-zosmf-password": "secret",
        "x-zcrafter-zosmf-protocol": "https",
        "x-zcrafter-zosmf-reject-unauthorized": "false",
    }
    base.update(overrides)
    return base


def test_resolve_from_request_headers_parses_all_fields(monkeypatch):
    monkeypatch.setattr(credentials, "get_http_headers", lambda: _headers())
    connection_id, creds = resolve_from_request_headers()
    assert connection_id == "conn-1"
    assert creds.host == "xplore.example.com"
    assert creds.port == 10443
    assert creds.user == "IBMUSER"
    assert creds.password == "secret"
    assert creds.reject_unauthorized is False


def test_resolve_from_request_headers_defaults_port_and_protocol(monkeypatch):
    headers = _headers()
    del headers["x-zcrafter-zosmf-port"]
    del headers["x-zcrafter-zosmf-protocol"]
    del headers["x-zcrafter-zosmf-reject-unauthorized"]
    monkeypatch.setattr(credentials, "get_http_headers", lambda: headers)
    _, creds = resolve_from_request_headers()
    assert creds.port == 443
    assert creds.protocol == "https"
    assert creds.reject_unauthorized is True


@pytest.mark.parametrize(
    "missing",
    ["x-zcrafter-connection-id", "x-zcrafter-zosmf-host", "x-zcrafter-zosmf-user", "x-zcrafter-zosmf-password"],
)
def test_resolve_from_request_headers_raises_when_required_header_missing(monkeypatch, missing):
    headers = _headers()
    del headers[missing]
    monkeypatch.setattr(credentials, "get_http_headers", lambda: headers)
    with pytest.raises(CredentialResolutionError):
        resolve_from_request_headers()


def test_resolve_from_request_headers_no_live_request_raises(monkeypatch):
    # get_http_headers() itself never raises (returns {} with no active
    # request per its own docstring) -- this just confirms that flows
    # through as a clear CredentialResolutionError, not a KeyError.
    monkeypatch.setattr(credentials, "get_http_headers", lambda: {})
    with pytest.raises(CredentialResolutionError):
        resolve_from_request_headers()
