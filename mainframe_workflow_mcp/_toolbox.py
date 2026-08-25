"""Resolves the mainframe toolbox, preferring the private package.

`zcrafter-mainframe-mcp` is used when it is installed; otherwise the bundled
reference implementation in `.toolbox` is used, so a fresh clone runs with no
private access. Import the four surfaces from here rather than from either
package directly.
"""
from __future__ import annotations

try:  # the private package, when the environment has it
    from zcrafter_mainframe.action_log import _sanitize_action_input
    from zcrafter_mainframe.contract import list_tool_definitions
    from zcrafter_mainframe.executor import LocalToolExecutor
    from zcrafter_mainframe.patch import apply_unified_diff

    TOOLBOX = "zcrafter-mainframe-mcp"
except ImportError:  # bundled reference implementation
    from .toolbox.action_log import _sanitize_action_input
    from .toolbox.contract import list_tool_definitions
    from .toolbox.executor import LocalToolExecutor
    from .toolbox.patch import apply_unified_diff

    TOOLBOX = "bundled"

__all__ = [
    "LocalToolExecutor",
    "TOOLBOX",
    "_sanitize_action_input",
    "apply_unified_diff",
    "list_tool_definitions",
]
