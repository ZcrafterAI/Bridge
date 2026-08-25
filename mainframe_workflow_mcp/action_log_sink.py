from __future__ import annotations
import contextvars
import json
from datetime import datetime, timezone
from typing import Any
from ._toolbox import _sanitize_action_input
from .db import RequestStore

current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_request_id", default=None,
)


class ActionLogSink:
    """Implements the .log(entry) interface zcrafter's LocalToolExecutor expects,
    persisting each entry into our own RequestStore instead of zcrafter's
    InMemoryActionLogger. Tags each entry with whatever request_id the calling
    proxy handler set in current_request_id before invoking the executor."""

    def __init__(self, store: RequestStore):
        self.store = store

    def log(self, entry: dict[str, Any]) -> None:
        input_value = entry.get("input")
        if input_value is not None:
            input_value = _sanitize_action_input(input_value)
        self.store.add_action_log(
            request_id=current_request_id.get(),
            tool=entry["tool"],
            target=entry.get("target"),
            status=entry["status"],
            summary=entry["summary"],
            input_json=json.dumps(input_value) if input_value is not None else None,
            diff_hash=entry.get("diffHash"),
            now=entry.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )
