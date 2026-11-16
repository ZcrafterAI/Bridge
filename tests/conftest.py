import os
import tempfile
import webbrowser

import pytest

# Set before any test imports the server: its store must never be the one in the home folder.
_SCRATCH = tempfile.mkdtemp(prefix="bridge-tests-")
os.environ["MAINFRAME_WORKFLOW_DB_PATH"] = os.path.join(_SCRATCH, "state.db")
os.environ["MAINFRAME_WORKFLOW_ARCHIVE_DIR"] = os.path.join(_SCRATCH, "archive")
os.environ["MAINFRAME_WORKFLOW_APPROVAL"] = "prompt"


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    """A test must never open a page on the machine it runs on. The addresses it would have
    opened are kept, so a test can act as the person and visit one."""
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *args, **kwargs: opened.append(url) or True)
    return opened


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch, tmp_path):
    """A test must never read this machine's Zowe config, keychain or ZOWE_OPT_* variables."""
    from mainframe_workflow_mcp import credentials

    def refuse(service, account):
        raise AssertionError("a test tried to read the real OS keychain")

    monkeypatch.setattr(credentials, "_keychain_get", refuse)
    monkeypatch.setenv("ZOWE_CLI_HOME", str(tmp_path / "no-zowe-home"))
    for name in ("HOST", "USER", "PASSWORD", "PORT", "PROTOCOL", "BASE_PATH", "REJECT_UNAUTHORIZED"):
        monkeypatch.delenv(f"ZOWE_OPT_{name}", raising=False)
    monkeypatch.chdir(tmp_path)
