"""The `zcrafter-bridge` command.

    zcrafter-bridge                 run the MCP server (what an AI client launches)
    zcrafter-bridge --demo          run it against a pretend mainframe on this machine
    zcrafter-bridge approve         approve or reject waiting requests in a terminal
    zcrafter-bridge install-skill   copy the agent skill into ~/.claude/skills
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from importlib import metadata
from pathlib import Path


def _version() -> str:
    try:
        return metadata.version("zcrafter-bridge")
    except metadata.PackageNotFoundError:
        return "0+source"


def _skill_source() -> Path | None:
    here = Path(__file__).resolve().parent
    for candidate in (here / "skill" / "SKILL.md",
                      here.parent / ".claude" / "skills" / "mainframe-workflow" / "SKILL.md"):
        if candidate.is_file():
            return candidate
    return None


def install_skill(target_root: Path | None = None) -> int:
    source = _skill_source()
    if source is None:
        print("The skill file is not part of this install.", file=sys.stderr)
        return 1
    target = (target_root or Path.home() / ".claude" / "skills") / "mainframe-workflow"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target / "SKILL.md")
    print(f"Installed the mainframe-workflow skill at {target}")
    return 0


def _start_demo() -> None:
    """Point this process at a pretend mainframe, with a store of its own."""
    from .demo import USER, start_demo_mainframe

    _, port = start_demo_mainframe()
    os.environ.update({
        "ZOWE_OPT_HOST": "127.0.0.1",
        "ZOWE_OPT_PORT": str(port),
        "ZOWE_OPT_USER": USER,
        "ZOWE_OPT_PASSWORD": "demo",
        "ZOWE_OPT_PROTOCOL": "http",
        "ZOWE_OPT_REJECT_UNAUTHORIZED": "false",
    })
    os.environ.pop("MAINFRAME_WORKFLOW_APIML_BASE_PATH", None)
    scratch = Path(tempfile.mkdtemp(prefix="zcrafter-bridge-demo-"))
    os.environ.setdefault("MAINFRAME_WORKFLOW_DB_PATH", str(scratch / "state.db"))
    os.environ.setdefault("MAINFRAME_WORKFLOW_ARCHIVE_DIR", str(scratch / "archive"))
    print(
        "[bridge] Demo mode: a pretend mainframe on this machine. Nothing real is touched. "
        "Try: \"PAYRUN abended last night, find out why and fix it.\"",
        file=sys.stderr, flush=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zcrafter-bridge",
        description="MCP server that gives AI agents an IBM z/OS mainframe, with every change approved by a person.",
    )
    parser.add_argument("--version", action="version", version=f"zcrafter-bridge {_version()}")
    parser.add_argument("--demo", action="store_true",
                        help="use a pretend mainframe on this machine instead of a real one")
    parser.add_argument("--read-only", action="store_true", help="offer no tool that changes anything")
    parser.add_argument("command", nargs="?", choices=["serve", "approve", "install-skill"], default="serve")
    args = parser.parse_args(argv)

    if args.command == "approve":
        from .approve import main as approve_main
        return approve_main()
    if args.command == "install-skill":
        return install_skill()

    if args.read_only:
        os.environ["MAINFRAME_WORKFLOW_READ_ONLY"] = "true"
    if args.demo:
        _start_demo()
    from . import server  # imported last: it reads its settings when it loads
    server.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
