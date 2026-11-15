#!/usr/bin/env bash
# Boardwright installer for Linux (and macOS, untested).
#
#   From a clone:          bash install/install.sh [--yes] [--no-signin] [--no-open] [--check]
#   --check reports what is installed and what is missing, and changes nothing.
#   Straight from GitHub:  curl -fsSL https://raw.githubusercontent.com/prathware/boardwright/main/install/install.sh | bash
#
# Asks before every change (sudo is used only for the KiCad and Git packages, and only after you say yes).
# Never asks for, reads or stores a password, API key or token: sign-in is Claude Code's own browser flow.
set -u
REPO="prathware/boardwright"
ADDON_URL="https://github.com/$REPO/releases/latest/download/boardwright-kicad.zip"
YES=0; SIGNIN=1; OPEN=1; CHECK=0
for a in "$@"; do
  case "$a" in --yes) YES=1 ;; --no-signin) SIGNIN=0 ;; --no-open) OPEN=0 ;; --check) CHECK=1; OPEN=0 ;; esac
done
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"
LOCAL=0; [ -n "$HERE" ] && [ -f "$HERE/.claude-plugin/marketplace.json" ] && LOCAL=1
OS="$(uname -s)"; DISTRO=""; LIKE=""
if [ -r /etc/os-release ]; then . /etc/os-release; DISTRO="${ID:-}"; LIKE="${ID_LIKE:-}"; fi
TODO=()
export PATH="$HOME/.local/bin:$PATH"

step() { printf '\n\033[36m%s. %s\033[0m\n' "$1" "$2"; }
ok()   { printf '   [ok] %s\n' "$1"; }
warn() { printf '   [!!] %s\n' "$1"; TODO+=("$1"); }
ask()  {
  [ "$CHECK" = 1 ] && return 1
  [ "$YES" = 1 ] && return 0
  local a; read -r -p "   $1 [y/N] " a </dev/tty 2>/dev/null || return 1
  [[ "$a" =~ ^([yY]|yes)$ ]]
}
has()  { command -v "$1" >/dev/null 2>&1; }
is_ubuntu() { [ "$DISTRO" = ubuntu ] || [[ "$LIKE" == *ubuntu* ]]; }
is_debian() { [ "$DISTRO" = debian ] || [[ "$LIKE" == *debian* ]]; }
pkg_hint() {   # $1 = package name -> install command for this distro
  if is_debian || is_ubuntu; then echo "sudo apt install $1"
  elif has dnf; then echo "sudo dnf install $1"
  elif has pacman; then echo "sudo pacman -S $1"
  elif has zypper; then echo "sudo zypper install $1"
  elif [ "$OS" = Darwin ]; then echo "brew install $1"
  else echo "install $1 with your package manager"; fi
}
find_cli() {
  for c in kicad-cli /usr/bin/kicad-cli /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli; do
    if has "$c" || [ -x "$c" ]; then echo "$c"; return; fi
  done
}

echo "Boardwright installer ($OS${DISTRO:+, $DISTRO ${VERSION_ID:-}}). It asks before every change."
[ "$CHECK" = 1 ] && echo "Check only: nothing will be installed or changed."
[ "$OS" = Darwin ] && echo "macOS is untested. Please report what happens."
[ "$LOCAL" = 1 ] && echo "Using this clone: $HERE" || echo "Using GitHub: $REPO"

step 1 "KiCad 9 or 10"
CLI="$(find_cli)"
if [ -z "$CLI" ] && has flatpak && flatpak info org.kicad.KiCad >/dev/null 2>&1; then
  echo "   Only the Flatpak KiCad is installed. Its sandbox cannot start Claude Code, so boardwright needs a"
  echo "   distribution package of KiCad as well (both can stay installed)."
fi
if [ -z "$CLI" ]; then
  if is_ubuntu && has apt-get && [ "$DISTRO" = ubuntu ] && [ "${VERSION_ID%%.*}" -lt 22 ] 2>/dev/null; then
    echo "   The official KiCad 10 PPA needs Ubuntu 22.04 or newer; this is $VERSION_ID."
    echo "   Upgrade Ubuntu, or use KiCad 9 from https://www.kicad.org/download/linux-distros/ if it lists one for $VERSION_ID."
  elif is_ubuntu && has apt-get; then
    echo "   Official KiCad 10 packages for Ubuntu: ppa:kicad/kicad-10.0-releases (https://www.kicad.org/download/linux-distros/)"
    if ask "Install KiCad 10 from the official PPA now (uses sudo)?"; then
      sudo apt-get install -y software-properties-common >/dev/null
      sudo add-apt-repository -y ppa:kicad/kicad-10.0-releases && sudo apt-get update && sudo apt-get install -y kicad
    fi
  elif [ "$OS" = Darwin ]; then
    has brew && ask "Install KiCad with Homebrew (brew install --cask kicad)?" && brew install --cask kicad
  fi
  CLI="$(find_cli)"
fi
if [ -n "$CLI" ]; then ok "kicad-cli: $CLI ($("$CLI" version 2>/dev/null))"
else warn "KiCad: install KiCad 9 or 10, see https://www.kicad.org/download/ (Ubuntu: ppa:kicad/kicad-10.0-releases)"; fi

step 2 "Python 3.10 or newer, and Git"
PY=""
if has python3 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY=python3; ok "python3: $(python3 --version)"
elif [ "$DISTRO" = ubuntu ] && [ "${VERSION_ID%%.*}" -lt 22 ] 2>/dev/null; then
  warn "Python 3.10+: Ubuntu $VERSION_ID ships $(python3 --version 2>&1). Upgrade to Ubuntu 22.04+, or install python3.10+ and make it the python3 on your PATH"
else warn "Python 3.10+: $(pkg_hint python3)"; fi
if ! has git && { is_debian || is_ubuntu; } && ask "Install Git with apt (uses sudo)?"; then sudo apt-get install -y git; fi
has git && ok "git: $(git --version)" || warn "Git: $(pkg_hint git)"
has curl || warn "curl: $(pkg_hint curl) (needed by the Claude Code and uv installers)"

step 3 "Claude Code"
if ! has claude; then
  echo "   Official installer: curl -fsSL https://claude.ai/install.sh | bash   (https://code.claude.com/docs/en/setup)"
  if ask "Install Claude Code now with the official installer?"; then curl -fsSL https://claude.ai/install.sh | bash; fi
fi
has claude && ok "claude: $(claude --version)" || warn "Claude Code: see https://code.claude.com/docs/en/setup"

step 4 "The boardwright Claude Code plugin"
if has claude; then
  SRC="$REPO"; [ "$LOCAL" = 1 ] && SRC="$HERE"
  if claude plugin marketplace list --json 2>/dev/null | grep -q '"name": *"boardwright"'; then
    [ "$CHECK" = 1 ] || claude plugin marketplace update boardwright >/dev/null
  elif ask "Add the boardwright marketplace ($SRC) to Claude Code?"; then
    claude plugin marketplace add "$SRC"
  fi
  if claude plugin list --json 2>/dev/null | grep -q '"id": *"boardwright@boardwright"'; then
    [ "$CHECK" = 1 ] || claude plugin update boardwright@boardwright >/dev/null; ok "plugin installed"
  elif ask "Install the boardwright plugin for your user?"; then
    claude plugin install boardwright@boardwright && ok "plugin installed" || warn "plugin install failed (see above)"
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
  SARGS=(); [ "$YES" = 1 ] && SARGS=(--yes); [ "$CHECK" = 1 ] && SARGS=(--check)
  if [ -r /dev/tty ] && [ "$YES" = 0 ]; then $PY "$SETUP" "${SARGS[@]}" </dev/tty; else $PY "$SETUP" "${SARGS[@]}" </dev/null; fi \
    || warn "helper setup left items open (see its summary above)"
else warn "helper setup skipped; later run: python3 <plugin>/scripts/setup.py"; fi

step 6 "The KiCad add-on (chat button in the PCB Editor)"
if [ "$OS" = Darwin ]; then
  echo "   Not available on macOS yet: use boardwright from Claude Code (terminal, VS Code or the desktop app)."
else
  ZIP=""
  if [ "$CHECK" = 1 ]; then
    echo "   (check only: the add-on zip is not built or downloaded)"
  elif [ "$LOCAL" = 1 ] && [ -n "$PY" ]; then
    $PY "$HERE/kicad-addon/build.py" >/dev/null && ZIP="$HERE/kicad-addon/dist/boardwright-kicad.zip"
  elif ask "Download the add-on zip from $ADDON_URL ?"; then
    ZIP="${TMPDIR:-/tmp}/boardwright-kicad.zip"
    curl -fsSL -o "$ZIP" "$ADDON_URL" || { ZIP=""; warn "download failed"; }
  fi
  if [ -n "$ZIP" ] && [ -f "$ZIP" ]; then
    ok "add-on package: $ZIP"
    echo "   KiCad installs add-ons itself. In KiCad's main window:"
    echo "   Plugin and Content Manager > Install from File... > pick the file above > Close, then restart KiCad."
    [ "$OPEN" = 1 ] && has xdg-open && xdg-open "$(dirname "$ZIP")" >/dev/null 2>&1 &
    TODO+=("KiCad add-on: Plugin and Content Manager > Install from File... > $ZIP, then restart KiCad")
  elif [ "$CHECK" = 0 ]; then warn "KiCad add-on: get boardwright-kicad.zip from the Releases page and use Install from File..."; fi
fi

step 7 "Sign in to Claude Code"
if has claude; then
  if claude auth status --json 2>/dev/null | grep -q '"loggedIn": *true'; then ok "signed in"
  elif [ "$SIGNIN" = 1 ] && ask "Start Claude Code's own sign-in now (your browser opens)?"; then claude auth login
  else warn "sign in later with: claude auth login"; fi
fi

echo
if [ ${#TODO[@]} -eq 0 ]; then echo "Done. Everything is in place."
else echo "Done, with these left for you:"; for t in "${TODO[@]}"; do echo "  - $t"; done; fi
echo "Next: make an empty folder for a board, open it in Claude Code, and run /boardwright:pcb-new"
