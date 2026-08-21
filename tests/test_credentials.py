import json
import subprocess
import pytest
from mainframe_workflow_mcp.credentials import resolve_credentials, CredentialResolutionError

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
