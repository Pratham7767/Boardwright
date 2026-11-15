#!/usr/bin/env python3
"""Setup check for the PCB pipeline plugin.

Usage:  python doctor.py [project_dir]
Prints a table (check | status | detail | how to fix); exit 0 if no FAIL, else 1.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_gates import find_kicad_cli  # noqa: E402

rows = []
API_HINT = "Open KiCad, Preferences > Plugins > Enable KiCad API server, restart KiCad"
BUDDY_HINT = ("python <plugin>/scripts/setup.py  (installs it; or by hand: "
              "uv tool install git+https://github.com/mburger89/KiCAD-Buddy@v0.1.0, then kicad-buddy --install-plugin)")


def add(check, status, detail="", fix=""):
    rows.append((check, status, detail, fix))


def sh(cmd, timeout=20):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return exc


def main():
    v = sys.version_info
    add("Python >= 3.10", "ok" if v >= (3, 10) else "FAIL", f"{v.major}.{v.minor}.{v.micro}",
        "" if v >= (3, 10) else "Install Python 3.10 or newer")

    cli = find_kicad_cli()
    if not cli:
        add("kicad-cli", "FAIL", "not found",
            "Install KiCad 9 or 10, or set KICAD_CLI to the full path of kicad-cli")
    else:
        p = sh([cli, "version"])
        out = p.stdout.strip() if hasattr(p, "stdout") else ""
        try:
            major = int(out.split(".")[0])
        except ValueError:
            major = 0
        if major < 9:
            add("kicad-cli", "FAIL", f"{cli} (version '{out or 'unknown'}')",
                "Install KiCad 9 or newer")
        else:
            add("kicad-cli", "ok", f"{cli} (version {out})")
        bindir = Path(cli).resolve().parent
        py = next((bindir / n for n in ("python.exe", "python3", "python")
                   if (bindir / n).exists()), None)
        if py:
            add("KiCad bundled python", "ok", str(py))
        else:
            add("KiCad bundled python", "warn", f"none next to {bindir}",
                "Needed by the barrier/EMC scripts; reinstall KiCad with its Python")

    hints = {"git": "Install Git from https://git-scm.com",
             "uv": "Install uv from https://docs.astral.sh/uv"}
    for tool in ("git", "uv"):
        w = shutil.which(tool)
        add(f"{tool} on PATH", "ok" if w else "warn", w or "not found", "" if w else hints[tool])

    kb = shutil.which("kicad-buddy")
    if not kb:
        add("kicad-buddy on PATH", "FAIL", "not found", BUDDY_HINT)
        add("KiCad API connection", "warn", "skipped (kicad-buddy missing)", BUDDY_HINT)
    else:
        add("kicad-buddy on PATH", "ok", kb)
        p = sh([kb, "--check"], timeout=20)
        if isinstance(p, subprocess.TimeoutExpired):
            add("KiCad API connection", "warn", "kicad-buddy --check timed out (20 s)", API_HINT)
        elif isinstance(p, Exception):
            add("KiCad API connection", "warn", f"could not run: {p}", BUDDY_HINT)
        else:
            text = (p.stdout or "") + (p.stderr or "")
            ok = '"ipc_connected": true' in text or '"ipc_connected":true' in text
            add("KiCad API connection", "ok" if ok else "warn",
                "ipc_connected: true" if ok else "ipc_connected not true",
                "" if ok else API_HINT)

    env = os.environ.get("KICAD_CLI")
    hint = f"Set KICAD_CLI={cli}" if cli else "Set KICAD_CLI to the full path of kicad-cli"
    if env or cli:
        add("KICAD_CLI variable", "ok", env or "not set (not needed: kicad-cli was found)")
    else:
        add("KICAD_CLI variable", "warn", "not set", hint)

    if len(sys.argv) > 1:
        proj = Path(sys.argv[1]).resolve()
        for ext in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
            n = sorted(proj.glob(f"*{ext}")) if proj.is_dir() else []
            add(f"project *{ext}", "ok" if len(n) == 1 else "warn",
                n[0].name if len(n) == 1 else f"{len(n)} found in {proj}",
                "" if len(n) == 1 else "Keep exactly one in the project root")
        running = []
        if os.name == "nt":
            p = sh(["tasklist"])
            if hasattr(p, "stdout"):
                low = p.stdout.lower()
                running = [n for n in ("kicad.exe", "pcbnew.exe", "eeschema.exe") if n in low]
        else:
            p = sh(["pgrep", "-il", "kicad|pcbnew|eeschema"])
            if hasattr(p, "stdout") and p.stdout.strip():
                running = p.stdout.strip().splitlines()
        add("KiCad running (info)", "ok", ", ".join(running) if running else "no KiCad process",
            "KiCad may overwrite files changed by scripts; save and reload after script edits"
            if running else "")

    table = [("check", "status", "detail", "how to fix")] + rows
    w = [max(len(str(r[i])) for r in table) for i in range(4)]
    for i, r in enumerate(table):
        print(" | ".join(str(c).ljust(w[j]) for j, c in enumerate(r)).rstrip())
        if i == 0:
            print("-+-".join("-" * x for x in w))
    return 1 if any(r[1] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
