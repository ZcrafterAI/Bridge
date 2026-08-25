"""Redaction applied before an action-log entry is persisted.

Exact behaviour is pinned by tests/test_workflow_action_log_sink.py:
secrets become "[REDACTED]"; a unified diff becomes "[HASHED]" outright
(its body can carry source, so it is never persisted); ordinary fields
pass through unchanged.
"""
from __future__ import annotations
from typing import Any

_SENSITIVE = {"password", "passwd", "pass", "token", "tokenvalue", "secret",
              "apikey", "api_key", "authorization", "auth", "credential",
              "credentials", "user", "username"}
# never persisted in the clear - the executor stores a diffHash separately
_HASHED = {"unifiedDiff", "unified_diff"}
# bulk payloads: kept but truncated, so the log stays readable
_BULK = {"content", "jcl", "data"}
_MAX = 512


def _sanitize_action_input(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key in _HASHED:
                out[k] = "[HASHED]"
            elif key.lower() in _SENSITIVE:
                out[k] = "[REDACTED]"
            elif key in _BULK and isinstance(v, str) and len(v) > _MAX:
                out[k] = f"{v[:_MAX]}... <{len(v)} bytes total>"
            else:
                out[k] = _sanitize_action_input(v)
        return out
    if isinstance(value, list):
        return [_sanitize_action_input(v) for v in value]
    return value
