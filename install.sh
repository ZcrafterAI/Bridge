#!/bin/sh
# Installs Zcrafter Bridge, an MCP server that gives AI agents an IBM z/OS mainframe.
#
#   curl -fsSL https://raw.githubusercontent.com/ZcrafterAI/Bridge/main/install.sh | sh
#
# What it does, and nothing else:
#   1. Finds uv (https://docs.astral.sh/uv/), or installs it for your user from astral.sh.
#      Set BRIDGE_NO_UV_INSTALL=1 to be told instead.
#   2. Runs `uv tool install` for zcrafter-bridge, into a folder of its own under your home
#      directory. No sudo, nothing system-wide.
#   3. Prints how to connect it to your AI client.
set -eu

PACKAGE="zcrafter-bridge"
SOURCE="git+https://github.com/ZcrafterAI/Bridge"
DOCS="https://github.com/ZcrafterAI/Bridge"

# ---- look: colour only on a terminal that wants it ----
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
  BOLD=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
  GREEN=$(printf '\033[32m'); RED=$(printf '\033[31m'); CYAN=$(printf '\033[36m')
  FANCY=1
else
  BOLD=""; DIM=""; RESET=""; GREEN=""; RED=""; CYAN=""; FANCY=0
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
fail() { printf '  %s✗%s %s\n' "$RED" "$RESET" "$*"; }
row()  { printf '    %s%-13s%s %s\n' "$DIM" "$1" "$RESET" "$2"; }
cmd()  { printf '    %s%-13s%s %s%s%s\n' "$DIM" "$1" "$RESET" "$CYAN" "$2" "$RESET"; }

LOG=$(mktemp "${TMPDIR:-/tmp}/zcrafter-bridge-install.XXXXXX")
trap 'rm -f "$LOG"' EXIT

# Runs a command quietly, with a spinner on a terminal. Its output is kept for a failure.
run() {
  label=$1; shift
  if [ "$FANCY" = 1 ]; then
    "$@" >"$LOG" 2>&1 &
    pid=$!
    frames='|/-\'
    i=0
    while kill -0 "$pid" 2>/dev/null; do
      i=$(( (i % 4) + 1 ))
      printf '\r  %s%s%s %s' "$DIM" "$(printf '%s' "$frames" | cut -c "$i")" "$RESET" "$label"
      sleep 0.1
    done
    printf '\r\033[K'
    wait "$pid"
  else
    "$@" >"$LOG" 2>&1
  fi
}

say ""
say "  ${BOLD}▀▀▀█▀${RESET}"
say "  ${BOLD} ▄▀  ${RESET}   ${BOLD}Zcrafter Bridge${RESET}"
say "  ${BOLD}█▄▄▄▄${RESET}   ${DIM}AI agents on your mainframe. Every change approved by you.${RESET}"
say ""

# ---- 1. uv ----
UV=""
if command -v uv >/dev/null 2>&1; then
  UV=$(command -v uv)
elif [ -x "$HOME/.local/bin/uv" ]; then
  UV="$HOME/.local/bin/uv"
elif [ -x "$HOME/.cargo/bin/uv" ]; then
  UV="$HOME/.cargo/bin/uv"
fi

if [ -z "$UV" ]; then
  if [ -n "${BRIDGE_NO_UV_INSTALL:-}" ]; then
    fail "uv is not installed"
    say ""
    say "  Bridge installs with uv. Get it from ${CYAN}https://docs.astral.sh/uv/${RESET} and run this again."
    exit 1
  fi
  if run "Installing uv from astral.sh" sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'; then
    UV="$HOME/.local/bin/uv"
    [ -x "$UV" ] || UV=$(command -v uv 2>/dev/null || true)
  fi
  if [ -z "$UV" ] || [ ! -x "$UV" ]; then
    fail "Could not install uv"
    sed 's/^/      /' "$LOG" | tail -n 12
    say ""
    say "  Install it from ${CYAN}https://docs.astral.sh/uv/${RESET} and run this again."
    exit 1
  fi
  ok "Installed uv $("$UV" --version 2>/dev/null | awk '{print $2}')"
else
  ok "Found uv $("$UV" --version 2>/dev/null | awk '{print $2}')"
fi

# ---- 2. Bridge ----
install_bridge() {
  "$UV" tool install --quiet --upgrade "$PACKAGE" 2>/dev/null || "$UV" tool install --quiet --upgrade "$SOURCE"
}
if ! run "Installing Zcrafter Bridge" install_bridge; then
  fail "Could not install Zcrafter Bridge"
  sed 's/^/      /' "$LOG" | tail -n 20
  say ""
  say "  Report it at ${CYAN}${DOCS}/issues${RESET}"
  exit 1
fi

BIN_DIR=$("$UV" tool dir --bin 2>/dev/null || printf '%s' "$HOME/.local/bin")
BRIDGE="$BIN_DIR/zcrafter-bridge"
[ -x "$BRIDGE" ] || BRIDGE=$(command -v zcrafter-bridge 2>/dev/null || printf 'zcrafter-bridge')
VERSION=$("$BRIDGE" --version 2>/dev/null | awk '{print $2}')
ok "Installed Zcrafter Bridge ${VERSION:-}"

ON_PATH=1
command -v zcrafter-bridge >/dev/null 2>&1 || ON_PATH=0
# A client started outside this shell may not share its PATH, so the full path is the safe one.
RUN="zcrafter-bridge"
[ "$ON_PATH" = 1 ] || RUN="$BRIDGE"

# ---- 3. what next ----
say ""
say "  ${BOLD}1. Connect your AI client${RESET}"
cmd "Claude Code" "claude mcp add zcrafter-bridge -- $RUN"
cmd "Codex" "codex mcp add zcrafter-bridge -- $RUN"
row "Other clients" "command: ${CYAN}${RUN}${RESET}  ${DIM}(Cursor, VS Code, Claude Desktop, Gemini CLI)${RESET}"
say ""
say "  ${BOLD}2. Connect your mainframe${RESET}"
row "Zowe profile" "used automatically. Check it with ${CYAN}zowe zosmf check status${RESET}"
row "Or set" "ZOWE_OPT_HOST, ZOWE_OPT_USER, ZOWE_OPT_PASSWORD"
say ""
say "  ${BOLD}3. Ask your agent${RESET}"
row "Try" "\"List my datasets\"  or  \"Why did my last job fail?\""
say ""
if [ "$ON_PATH" = 0 ]; then
  say "  ${DIM}zcrafter-bridge is not on your PATH yet. Open a new terminal, or run: uv tool update-shell${RESET}"
fi
say "  ${DIM}Docs  ${DOCS}${RESET}"
say ""
