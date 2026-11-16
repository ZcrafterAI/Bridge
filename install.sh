#!/bin/sh
# Installs Zcrafter Bridge, an MCP server that gives AI agents an IBM z/OS mainframe.
#
#   curl -fsSL https://raw.githubusercontent.com/ZcrafterAI/Bridge/main/install.sh | sh
#
# It installs one command, zcrafter-bridge, with uv or pipx (whichever you have), and prints
# how to connect it to your AI client. It changes nothing else on your machine.
set -eu

PACKAGE="zcrafter-bridge"
SOURCE="git+https://github.com/ZcrafterAI/Bridge"

say() { printf '%s\n' "$*"; }

if command -v uv >/dev/null 2>&1; then
  say "Installing $PACKAGE with uv..."
  uv tool install --upgrade "$PACKAGE" 2>/dev/null || uv tool install --upgrade "$SOURCE"
elif command -v pipx >/dev/null 2>&1; then
  say "Installing $PACKAGE with pipx..."
  pipx install --force "$PACKAGE" 2>/dev/null || pipx install --force "$SOURCE"
else
  say "Zcrafter Bridge installs with uv or pipx, and neither was found."
  say "Install uv first (https://docs.astral.sh/uv/), then run this again:"
  say "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if ! command -v zcrafter-bridge >/dev/null 2>&1; then
  say ""
  say "Installed, but zcrafter-bridge is not on your PATH yet. Open a new terminal, or run:"
  say "  uv tool update-shell"
  exit 0
fi

say ""
say "Installed: $(zcrafter-bridge --version)"
say ""
say "Connect it to your AI client:"
say "  Claude Code   claude mcp add zcrafter-bridge -- zcrafter-bridge"
say "  Codex         in ~/.codex/config.toml:  [mcp_servers.zcrafter-bridge]  command = \"zcrafter-bridge\""
say "  Others        command: zcrafter-bridge   (no arguments)"
say ""
say "No mainframe handy? Add --demo to try it on a pretend one:"
say "  claude mcp add zcrafter-bridge-demo -- zcrafter-bridge --demo"
say ""
say "For a real mainframe it uses your Zowe profile (zowe zosmf check status),"
say "or ZOWE_OPT_HOST, ZOWE_OPT_USER and ZOWE_OPT_PASSWORD."
