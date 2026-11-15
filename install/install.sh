#!/usr/bin/env bash
# Boardwright installer for macOS and Linux (UNTESTED on both; Windows is the tested platform).
#
#   From a clone:          bash install/install.sh [--yes]
#   Straight from GitHub:  curl -fsSL https://raw.githubusercontent.com/prathware/boardwright/main/install/install.sh | bash
#
# Asks before every change. Never asks for, reads or stores a password, API key or token.
# The KiCad add-on (chat button inside KiCad) is Windows-only for now; on macOS and Linux
# you use boardwright from Claude Code in a terminal, VS Code or the desktop app.
set -u
REPO="prathware/boardwright"
YES=0; [ "${1:-}" = "--yes" ] && YES=1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"
LOCAL=0; [ -n "$HERE" ] && [ -f "$HERE/.claude-plugin/marketplace.json" ] && LOCAL=1
TODO=()
export PATH="$HOME/.local/bin:$PATH"

step() { printf '\n\033[36m%s. %s\033[0m\n' "$1" "$2"; }
ok()   { printf '   [ok] %s\n' "$1"; }
warn() { printf '   [!!] %s\n' "$1"; TODO+=("$1"); }
ask()  {
  [ "$YES" = 1 ] && return 0
  local a; read -r -p "   $1 [y/N] " a </dev/tty || return 1
  [[ "$a" =~ ^([yY]|yes)$ ]]
}
has()  { command -v "$1" >/dev/null 2>&1; }

echo "Boardwright installer (macOS/Linux, untested). It asks before every change."
[ "$LOCAL" = 1 ] && echo "Using this clone: $HERE" || echo "Using GitHub: $REPO"

step 1 "KiCad 9 or 10"
CLI=""
for c in kicad-cli /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli; do
  if has "$c" || [ -x "$c" ]; then CLI="$c"; break; fi
done
if [ -n "$CLI" ]; then ok "kicad-cli: $CLI"
else warn "KiCad: install 9 or 10 from https://www.kicad.org/download/ (macOS: brew install --cask kicad)"; fi

step 2 "Python 3.10 or newer"
PY=""
if has python3 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY=python3; ok "python3: $(python3 --version)"
else warn "Python 3.10+: install it (macOS: brew install python; Debian/Ubuntu: sudo apt install python3)"; fi

step 3 "Claude Code"
if ! has claude; then
  echo "   Official installer: curl -fsSL https://claude.ai/install.sh | bash  (https://code.claude.com/docs/en/setup)"
  if ask "Install Claude Code now with the official installer?"; then curl -fsSL https://claude.ai/install.sh | bash; fi
fi
has claude && ok "claude: $(claude --version)" || warn "Claude Code: see https://code.claude.com/docs/en/setup"

step 4 "The boardwright Claude Code plugin"
if has claude; then
  SRC="$REPO"; [ "$LOCAL" = 1 ] && SRC="$HERE"
  if claude plugin marketplace list --json 2>/dev/null | grep -q '"name": *"boardwright"'; then
    claude plugin marketplace update boardwright >/dev/null
  elif ask "Add the boardwright marketplace ($SRC) to Claude Code?"; then
    claude plugin marketplace add "$SRC"
  fi
  if claude plugin list --json 2>/dev/null | grep -q '"id": *"boardwright@boardwright"'; then
    claude plugin update boardwright@boardwright >/dev/null; ok "plugin installed (updated if newer)"
  elif ask "Install the boardwright plugin for your user?"; then
    claude plugin install boardwright@boardwright && ok "plugin installed" || warn "plugin install failed"
  else warn "plugin: claude plugin install boardwright@boardwright"; fi
fi

step 5 "Helper tools (uv, kicad-buddy, schematic tools, KiCad API setting)"
SETUP=""
if [ "$LOCAL" = 1 ]; then SETUP="$HERE/plugin/scripts/setup.py"
elif has claude && [ -n "$PY" ]; then
  SETUP="$(claude plugin list --json 2>/dev/null | $PY -c 'import json,sys,os
for p in json.load(sys.stdin):
    if p.get("id") == "boardwright@boardwright": print(os.path.join(p["installPath"], "scripts", "setup.py"))')"
fi
if [ -n "$PY" ] && [ -n "$SETUP" ] && [ -f "$SETUP" ]; then
  if [ "$YES" = 1 ]; then $PY "$SETUP" --yes </dev/tty; else $PY "$SETUP" </dev/tty; fi || warn "helper setup left items open (see its summary)"
else warn "helper setup skipped; later run: python3 <plugin>/scripts/setup.py"; fi

step 6 "Sign in to Claude Code"
if has claude; then
  if claude auth status --json 2>/dev/null | grep -q '"loggedIn": *true'; then ok "signed in"
  elif ask "Start Claude Code's own sign-in now (your browser opens)?"; then claude auth login
  else warn "sign in later with: claude auth login"; fi
fi

echo
if [ ${#TODO[@]} -eq 0 ]; then echo "Done. Everything is in place."
else echo "Done, with these left for you:"; for t in "${TODO[@]}"; do echo "  - $t"; done; fi
echo "Next: make an empty folder for a board, open it in Claude Code, and run /boardwright:pcb-new"
