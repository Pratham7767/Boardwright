#!/usr/bin/env bash
# Boardwright routing engine for Linux and macOS: installs the tools the deterministic engine uses into
# ~/.local/share/boardwright/engine (nothing in your projects, nothing system-wide). The installer runs it.
#
#   bash plugin/scripts/setup_engine.sh
#
# Each download is pinned to one version and checked against its published SHA-256 before use:
#   Freerouting 2.5.0 (GPL-3, a separate program), a Java 25 runtime for it (Eclipse Temurin),
#   KiCadRoutingTools 0.24.1 (MIT) with its prebuilt router, and its Python packages in their own environment.
set -euo pipefail
ROOT="${BOARDWRIGHT_ENGINE_DIR:-$HOME/.local/share/boardwright/engine}"
mkdir -p "$ROOT"
OS="$(uname -s)"; ARCH="$(uname -m)"
T=https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8
K=https://github.com/drandyhaas/KiCadRoutingTools/releases/download/v0.24.1
case "$OS-$ARCH" in
  Linux-x86_64)  JRE="$T/OpenJDK25U-jre_x64_linux_hotspot_25.0.5_8.tar.gz";    JSHA=6fac98f0c8202efc3135a9e9e42aa61963ec42d1c5cbb40caf231e7b14a24ef6
                 RTR="$K/grid_router-linux-x86_64.so";  RSHA=d3107721e55c25cfd467bfc7a27923791b7f73bab14dae7fd007496adf6f2096 ;;
  Linux-aarch64) JRE="$T/OpenJDK25U-jre_aarch64_linux_hotspot_25.0.5_8.tar.gz"; JSHA=963931723891302ebb2687178532c3d793d71e2577cd058061c7efb396140a86
                 RTR=""; RSHA="" ;;
  Darwin-arm64)  JRE="$T/OpenJDK25U-jre_aarch64_mac_hotspot_25.0.5_8.tar.gz";   JSHA=72ebd76b502c849e88dea39afae51baf5f82f2b5b1b6389c28ea707b20451bce
                 RTR="$K/grid_router-macos-arm64.so";   RSHA=29a4a715af31dc3eb4a28e1ee29d0cfb234a996b0f1cc5fdf2c1240132ca0a4f ;;
  Darwin-x86_64) JRE="$T/OpenJDK25U-jre_x64_mac_hotspot_25.0.5_8.tar.gz";       JSHA=806902c796c670969b7b27df73b8f0fe0924a61bd65083aa53064115e49cab2d
                 RTR="$K/grid_router-macos-x86_64.so";  RSHA=e729941e0229371b19be049d1eee0629aa6bb7d9f9564fb11f57a99b60557ea6 ;;
  *) echo "This computer ($OS $ARCH) has no prebuilt engine tools yet."; exit 2 ;;
esac

if [ -z "$RTR" ]; then
  echo "This computer ($OS $ARCH) has no prebuilt KiCadRoutingTools router, so the Boardwright engine cannot be installed here."
  echo "Build the router with Rust (rustup.rs) using KiCadRoutingTools' build_router.py, or use a supported platform. Nothing was installed."
  exit 2
fi

sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
get() {  # name url sha file
  local dst="$ROOT/$4"
  if [ -f "$dst" ] && [ "$(sha "$dst")" = "$3" ]; then echo "ok        $1 (already here)"; return; fi
  echo "download  $1"
  curl -fsSL "$2" -o "$dst.part"
  if [ "$(sha "$dst.part")" != "$3" ]; then rm -f "$dst.part"; echo "$1: checksum does not match; nothing installed from it."; exit 1; fi
  mv "$dst.part" "$dst"; echo "ok        $1 (checksum matches)"
}

get jre "$JRE" "$JSHA" jre.tar.gz
get freerouting https://github.com/freerouting/freerouting/releases/download/v2.5.0/freerouting-2.5.0.jar \
    f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7 freerouting-2.5.0.jar
get krt "$K/KiCadRoutingTools-0.24.1.zip" 95fe2610a591b2b5702d41e8e85b89dc5318a48d75f528e2b866c3b3ced5fdb2 krt.zip
if [ -n "$RTR" ]; then get krt-router "$RTR" "$RSHA" grid_router.so; fi

mkdir -p "$ROOT/jre"
[ -n "$(find "$ROOT/jre" -name java -type f 2>/dev/null | head -1)" ] || tar -xzf "$ROOT/jre.tar.gz" -C "$ROOT/jre"
JAVA="$(find "$ROOT/jre" -path '*bin/java' -type f | head -1)"

if [ ! -f "$ROOT/krt/py_router/route.py" ]; then
  rm -rf "$ROOT/krt-unzip" "$ROOT/krt"; mkdir -p "$ROOT/krt-unzip"
  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ROOT/krt.zip" "$ROOT/krt-unzip"
  PR="$(find "$ROOT/krt-unzip" -type d -name py_router | head -1)"
  [ -n "$PR" ] || { echo "KiCadRoutingTools archive has no py_router folder"; exit 1; }
  mv "$(dirname "$PR")" "$ROOT/krt"; rm -rf "$ROOT/krt-unzip"
fi
mkdir -p "$ROOT/krt/rust_router"
if [ -f "$ROOT/grid_router.so" ]; then cp -f "$ROOT/grid_router.so" "$ROOT/krt/rust_router/grid_router.so"; cp -f "$ROOT/grid_router.so" "$ROOT/krt/grid_router.so"; fi
# the release package has no rust_router/Cargo.toml; KiCadRoutingTools reads the router version from it
[ -f "$ROOT/krt/rust_router/Cargo.toml" ] || printf '[package]\nname = "grid_router"\nversion = "0.24.1"\n' > "$ROOT/krt/rust_router/Cargo.toml"

command -v uv >/dev/null || { echo "uv is needed (the main Boardwright installer sets it up)."; exit 2; }
[ -x "$ROOT/venv/bin/python" ] || uv venv -q --python 3.12 "$ROOT/venv"
uv pip install -q --python "$ROOT/venv/bin/python" "numpy>=1.22" "scipy>=1.7" "shapely>=2.0" "Pillow>=9.2" "ortools>=9.15"
cat > "$ROOT/engine.json" <<JSON
{"version": 1, "java": "$JAVA", "freerouting_jar": "$ROOT/freerouting-2.5.0.jar", "krt": "$ROOT/krt",
 "krt_python": "$ROOT/venv/bin/python", "installed": "$(date -u +%Y-%m-%dT%H:%M:%S)"}
JSON
"$JAVA" -jar "$ROOT/freerouting-2.5.0.jar" -h 2>&1 | head -1 || true
echo "Done. The Boardwright engine tools are in $ROOT"
