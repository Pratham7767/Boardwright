#!/usr/bin/env bash
# Developer setup (Linux, macOS): make sure OmniRoute (an AI gateway, https://github.com/cheaper-inference/OmniRoute,
# MIT) is installed and running, so Claude Code can keep working on Boardwright through other AI providers when
# the Claude plan's limit is reached. For people developing Boardwright; the product itself does not need it.
#
#   bash tools/dev/ensure-omniroute.sh            install if missing, start
#   bash tools/dev/ensure-omniroute.sh --check    say what is there, change nothing
#
# Everything goes into ~/.local/share/boardwright/dev (or BOARDWRIGHT_DEV_DIR): a private Node.js 24 (OmniRoute
# needs Node 22.22+ or 24+; the system Node is left alone) and OmniRoute, both pinned and checked by checksum.
# This script never reads, writes or prints an OmniRoute key: you create keys in OmniRoute's own dashboard.
set -euo pipefail
NODE_VER=24.22.3
OMNI_VER=3.8.54
PORT=20128
ROOT="${BOARDWRIGHT_DEV_DIR:-$HOME/.local/share/boardwright/dev}"
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  PLAT=linux-x64;    EXT=tar.xz; SHA=4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb ;;
  Linux-aarch64) PLAT=linux-arm64;  EXT=tar.xz; SHA=6e51a2ada00f0011cc266f65d98922b403d7ad88f809ca2aa615a5fe1ce6e86c ;;
  Darwin-arm64)  PLAT=darwin-arm64; EXT=tar.gz; SHA=ff6e17d4874b76d272212b908cc020d6e815fba5a6c7eaaa06add725840307fd ;;
  Darwin-x86_64) PLAT=darwin-x64;   EXT=tar.gz; SHA=977614af0504c81045e7fd85596dbca0e5f951b96681516dadafedcca8c447f7 ;;
  *) echo "no pinned Node.js for $(uname -s) $(uname -m)"; exit 2 ;;
esac
NODE_DIR="$ROOT/node-v$NODE_VER-$PLAT"
PREFIX="$ROOT/omniroute"
OMNI="$PREFIX/bin/omniroute"
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
running() { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }

if [ "${1:-}" = "--check" ]; then
  [ -x "$NODE_DIR/bin/node" ] && echo "node 24      ok ($NODE_DIR)" || echo "node 24      missing"
  [ -x "$OMNI" ] && echo "omniroute    ok ($OMNI)" || echo "omniroute    missing"
  running && echo "running      yes, http://localhost:$PORT" || echo "running      no"
  exit 0
fi

mkdir -p "$ROOT"
if [ ! -x "$NODE_DIR/bin/node" ]; then
  echo "download  Node.js $NODE_VER (private copy for OmniRoute)"
  curl -fsSL -o "$ROOT/node.$EXT" "https://nodejs.org/dist/v$NODE_VER/node-v$NODE_VER-$PLAT.$EXT"
  [ "$(sha "$ROOT/node.$EXT")" = "$SHA" ] || { rm -f "$ROOT/node.$EXT"; echo "Node.js: checksum does not match; nothing installed."; exit 1; }
  tar -xf "$ROOT/node.$EXT" -C "$ROOT" && rm -f "$ROOT/node.$EXT"
fi
export PATH="$NODE_DIR/bin:$PATH"
if [ ! -x "$OMNI" ]; then
  echo "install   OmniRoute $OMNI_VER (npm, into $PREFIX)"
  # npm 11 runs install scripts only for packages it is told to allow; OmniRoute's own needs these
  npm install -g --prefix "$PREFIX" "omniroute@$OMNI_VER" \
    --allow-scripts=omniroute,keytar,onnxruntime-node,@parcel/watcher,@swc/core,protobufjs,esbuild --no-fund --no-audit
  [ -x "$OMNI" ] || { echo "installing OmniRoute failed (see npm's messages above)"; exit 1; }
fi
if ! running; then
  echo "start     OmniRoute on http://localhost:$PORT"
  nohup "$OMNI" >"$ROOT/omniroute.log" 2>&1 &
fi
echo "ready     OmniRoute: dashboard http://localhost:$PORT (connect providers and create a key there)"
echo "          use it:   $OMNI launch      (starts Claude Code through OmniRoute)"
