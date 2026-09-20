import importlib

def test_defaults_resolve_under_project_root(monkeypatch):
    for var in (
        "MAINFRAME_WORKFLOW_DB_PATH",
        "MAINFRAME_WORKFLOW_ZOWE_PROFILE",
        "MAINFRAME_WORKFLOW_HTTP_TIMEOUT_SECONDS",
        "MAINFRAME_WORKFLOW_APIML_BASE_PATH",
        "MAINFRAME_WORKFLOW_CREDENTIAL_RESOLVER",
        "MAINFRAME_WORKFLOW_MCP_TRANSPORT",
        "MAINFRAME_WORKFLOW_MCP_HOST",
        "MAINFRAME_WORKFLOW_MCP_PORT",
        "MAINFRAME_WORKFLOW_MCP_PATH",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
    import mainframe_workflow_mcp.config as config
    importlib.reload(config)

    assert config.DB_PATH == config.PROJECT_ROOT / "mainframe_workflow_mcp" / "state.db"
    assert config.ZOWE_PROFILE == "default"
    assert config.HTTP_TIMEOUT_SECONDS == 30.0
    assert config.APIML_BASE_PATH == ""
    assert config.CREDENTIAL_RESOLVER_PATH == config.PROJECT_ROOT / "credential-resolver" / "dist" / "resolver.js"
    assert config.MCP_TRANSPORT == "http"
    assert config.MCP_HOST == "0.0.0.0"
    assert config.MCP_PORT == 8000
    assert config.MCP_PATH == "/mcp"

def test_env_overrides_are_read(monkeypatch, tmp_path):
    monkeypatch.setenv("MAINFRAME_WORKFLOW_DB_PATH", str(tmp_path / "custom.db"))
    monkeypatch.setenv("MAINFRAME_WORKFLOW_HTTP_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_APIML_BASE_PATH", "/ibmzosmf/api/v1")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_CREDENTIAL_RESOLVER", str(tmp_path / "resolver.js"))
    monkeypatch.setenv("MAINFRAME_WORKFLOW_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_MCP_PORT", "9001")
    monkeypatch.setenv("MAINFRAME_WORKFLOW_MCP_PATH", "/custom-mcp")
    import mainframe_workflow_mcp.config as config
    importlib.reload(config)

    assert config.DB_PATH == tmp_path / "custom.db"
    assert config.HTTP_TIMEOUT_SECONDS == 15.0
    assert config.APIML_BASE_PATH == "/ibmzosmf/api/v1"
    assert config.CREDENTIAL_RESOLVER_PATH == tmp_path / "resolver.js"
    assert config.MCP_TRANSPORT == "streamable-http"
    assert config.MCP_HOST == "127.0.0.1"
    assert config.MCP_PORT == 9001
    assert config.MCP_PATH == "/custom-mcp"
