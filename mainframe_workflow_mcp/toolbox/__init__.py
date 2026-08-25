"""Reference implementation of the mainframe toolbox this server proxies.

The server was originally built against a private package,
`zcrafter-mainframe-mcp`. That package remains the preferred implementation and
is used automatically when installed (see `mainframe_workflow_mcp._toolbox`).
This bundled version exists so the server installs and runs standalone.

It supplies four surfaces:

    contract.list_tool_definitions()  tool catalog (name / schema / approval)
    executor.LocalToolExecutor        dispatch to the client, with audit logging
    patch.apply_unified_diff()        unified-diff application
    action_log._sanitize_action_input redaction before an entry is persisted

The mainframe calls themselves live in `mainframe_workflow_mcp.clients`.
"""
