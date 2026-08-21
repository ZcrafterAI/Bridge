import importlib
from pathlib import Path

def test_defaults_resolve_under_project_root(monkeypatch):
    for var in (
        "MAINFRAME_WORKFLOW_DB_PATH",
        "MAINFRAME_WORKFLOW_ARCHIVE_DIR",
        "MAINFRAME_WORKFLOW_IDLE_DAYS",
        "MAINFRAME_WORKFLOW_RETENTION_DAYS",
        "MAINFRAME_WORKFLOW_ZOWE_PROFILE",
        "MAINFRAME_WORKFLOW_HTTP_TIMEOUT_SECONDS",
        "MAINFRAME_WORKFLOW_APIML_BASE_PATH",
        "MAINFRAME_WORKFLOW_CREDENTIAL_RESOLVER",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    import mainframe_workflow_mcp.config as config
    importlib.reload(config)

    assert config.DB_PATH == config.PROJECT_ROOT / "mainframe_workflow_mcp" / "state.db"
    assert config.ARCHIVE_DIR == config.PROJECT_ROOT / "mainframe_workflow_mcp" / "archive"
    assert config.IDLE_DAYS == 14
    assert config.RETENTION_DAYS == 90
    assert config.ZOWE_PROFILE == "default"
    assert config.HTTP_TIMEOUT_SECONDS == 30.0
    assert config.APIML_BASE_PATH == ""
    assert config.CREDENTIAL_RESOLVER_PATH == config.PROJECT_ROOT / "credential-resolver" / "dist" / "resolver.js"

def test_env_overrides_are_read(monkeypatch, tmp_path):
    monkeypatch.setenv("MAINFRAME_WORKFLOW_DB_PATH", str(tmp_path / "custom.db"))
    monkeypatch.setenv("MAINFRAME_WORKFLOW_IDLE_DAYS", "3")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_HTTP_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_APIML_BASE_PATH", "/ibmzosmf/api/v1")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_CREDENTIAL_RESOLVER", str(tmp_path / "resolver.js"))
    import mainframe_workflow_mcp.config as config
    importlib.reload(config)

    assert config.DB_PATH == tmp_path / "custom.db"
    assert config.IDLE_DAYS == 3
    assert config.HTTP_TIMEOUT_SECONDS == 15.0
    assert config.APIML_BASE_PATH == "/ibmzosmf/api/v1"
    assert config.CREDENTIAL_RESOLVER_PATH == tmp_path / "resolver.js"
