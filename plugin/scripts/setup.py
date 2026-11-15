#!/usr/bin/env python3
"""Set up everything boardwright needs besides KiCad and Claude Code themselves.

    python setup.py            ask before each change
    python setup.py --yes      make every change without asking
    python setup.py --check    report only, change nothing

What it does, in order (each step is skipped when it is already done):
  1. uv            the official installer from astral.sh, if uv is missing
  2. kicad-buddy   the live link to KiCad, pinned version, plus its KiCad-side plugin
  3. mcp-server-kicad   the schematic tools, pinned version, downloaded once so the
                        first Claude session does not wait for it
  4. KiCad API server   ticks Preferences > Plugins > Enable KiCad API server
                        (only while KiCad is closed; a backup of the file is kept)
  5. reports kicad-cli and the Claude Code sign-in, then runs doctor.py

It never asks for or stores a password, key or token, and it does not install
KiCad or Claude Code (it prints the official instructions instead).
Standard library only; Windows, macOS, Linux.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_gates import find_kicad_cli  # noqa: E402

BUDDY_SRC = "git+https://github.com/mburger89/KiCAD-Buddy@v0.1.0"
MCP_KICAD = "mcp-server-kicad==0.21.1"          # keep in step with ../.mcp.json
WIN = os.name == "nt"
UV_INSTALL = (['powershell', '-ExecutionPolicy', 'ByPass', '-c', 'irm https://astral.sh/uv/install.ps1 | iex']
              if WIN else ['sh', '-c', 'curl -LsSf https://astral.sh/uv/install.sh | sh'])
KICAD_URL = "https://www.kicad.org/download/"
CLAUDE_URL = "https://code.claude.com/docs/en/setup"

ARGS = set(sys.argv[1:])
YES, CHECK = "--yes" in ARGS, "--check" in ARGS
results: list = []


def say(msg: str = "") -> None:
    print(msg, flush=True)


def note(step: str, status: str, detail: str = "") -> None:
    results.append((step, status, detail))
    say(f"  [{status}] {step}" + (f": {detail}" if detail else ""))


def ask(question: str) -> bool:
    if CHECK:
        return False
    if YES:
        return True
    try:
        return input(f"  {question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def run(cmd: list, timeout: int = 600, quiet: bool = False) -> int:
    if not quiet:
        say("    $ " + " ".join(cmd))
    try:
        r = subprocess.run(cmd, timeout=timeout, stdin=subprocess.DEVNULL,
                           capture_output=quiet, text=True)
        return r.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        say(f"    failed: {exc}")
        return 1


def which(name: str) -> str | None:
    """PATH, then the folders the official installers use (a fresh install is not on PATH yet)."""
    w = shutil.which(name)
    if w:
        return w
    exe = name + (".exe" if WIN else "")
    for d in (Path.home() / ".local" / "bin", Path.home() / ".cargo" / "bin"):
        if (d / exe).is_file():
            return str(d / exe)
    return None


def step_uv() -> str | None:
    say("\n1. uv (runs the KiCad helper tools)")
    uv = which("uv")
    if uv:
        note("uv", "ok", uv)
        return uv
    say("    uv is missing. Official installer: " + " ".join(UV_INSTALL[-1:]))
    if ask("Install uv now with the official installer from astral.sh?"):
        run(UV_INSTALL)
        uv = which("uv")
    note("uv", "ok" if uv else ("missing" if CHECK else "FAIL"), uv or "see https://docs.astral.sh/uv/")
    return uv


def step_buddy(uv: str | None) -> None:
    say("\n2. kicad-buddy (live link to the open board)")
    kb = which("kicad-buddy")
    if kb and "--upgrade" not in ARGS:
        note("kicad-buddy", "ok", kb)
    elif not uv:
        note("kicad-buddy", "skipped", "needs uv")
        return
    elif ask(f"Install kicad-buddy ({BUDDY_SRC.split('@')[-1]}) with uv?"):
        run([uv, "tool", "install", "--force", BUDDY_SRC])
        kb = which("kicad-buddy")
        note("kicad-buddy", "ok" if kb else "FAIL", kb or "install failed, see above")
    else:
        note("kicad-buddy", "missing", f"uv tool install {BUDDY_SRC}")
        return
    if kb and not CHECK and ask("Install (or refresh) kicad-buddy's companion plugin inside KiCad?"):
        rc = run([kb, "--install-plugin"], timeout=120)
        note("kicad-buddy KiCad plugin", "ok" if rc == 0 else "FAIL", "" if rc == 0 else f"exit {rc}")


def step_mcp(uv: str | None) -> None:
    say("\n3. mcp-server-kicad (schematic tools)")
    uvx = which("uvx")
    if not uvx:
        note("mcp-server-kicad", "skipped", "needs uv")
        return
    if CHECK:
        note("mcp-server-kicad", "info", f"fetched by uvx on first use ({MCP_KICAD})")
        return
    if ask(f"Download {MCP_KICAD} now (about a minute, once)?"):
        t = time.time()
        # stdin is closed, so the server starts, sees end of input and exits
        rc = run([uvx, "--from", MCP_KICAD, "mcp-server-kicad-schematic"], timeout=600, quiet=True)
        note("mcp-server-kicad", "ok" if rc in (0, 1) else "warn",
             f"cached in {time.time() - t:.0f} s" if rc in (0, 1) else f"exit {rc}; uvx will retry on first use")
    else:
        note("mcp-server-kicad", "info", "will be fetched on first use")


def kicad_config_files() -> list:
    if os.environ.get("KICAD_CONFIG_HOME"):
        bases = [Path(os.environ["KICAD_CONFIG_HOME"])]
        return [b / "kicad_common.json" for b in bases if (b / "kicad_common.json").is_file()]
    if WIN:
        root = Path(os.environ.get("APPDATA", Path.home())) / "kicad"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Preferences" / "kicad"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kicad"
    files = [d / "kicad_common.json" for d in root.glob("*") if d.is_dir() and d.name[:1].isdigit()]
    files = [f for f in files if f.is_file()]
    return sorted(files, key=lambda f: [int(x) if x.isdigit() else 0 for x in f.parent.name.split(".")])


def kicad_running() -> bool:
    try:
        if WIN:
            out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=20).stdout.lower()
            return any(n in out for n in ("kicad.exe", "pcbnew.exe", "eeschema.exe"))
        return subprocess.run(["pgrep", "-i", "kicad|pcbnew|eeschema"], capture_output=True,
                              timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def step_kicad() -> None:
    say("\n4. KiCad")
    cli = find_kicad_cli()
    note("kicad-cli", "ok" if cli else "FAIL",
         cli or f"install KiCad 9 or 10 from {KICAD_URL}" + (" (or: winget install KiCad.KiCad)" if WIN else ""))
    files = kicad_config_files()
    if not files:
        note("KiCad API server", "warn", "KiCad has not been started yet; start it once, then rerun this")
        return
    cfg = files[-1]                                   # newest KiCad version
    try:
        data = json.loads(cfg.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        note("KiCad API server", "warn", f"could not read {cfg}: {exc}")
        return
    if data.get("api", {}).get("enable_server"):
        note("KiCad API server", "ok", f"enabled ({cfg.parent.name})")
        return
    hint = "KiCad > Preferences > Plugins > Enable KiCad API server, then restart KiCad"
    if kicad_running():
        note("KiCad API server", "missing", f"close KiCad and rerun, or tick it yourself: {hint}")
        return
    if ask(f"Turn on the KiCad API server in {cfg} (a .bak copy is kept)?"):
        shutil.copy2(cfg, cfg.with_suffix(".json.bak"))
        data.setdefault("api", {})["enable_server"] = True
        cfg.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
        note("KiCad API server", "ok", "enabled; takes effect the next time KiCad starts")
    else:
        note("KiCad API server", "missing", hint)


def step_claude() -> None:
    say("\n5. Claude Code")
    claude = which("claude")
    if not claude:
        note("Claude Code", "FAIL", f"install it: {CLAUDE_URL}")
        return
    try:
        r = subprocess.run([claude, "auth", "status", "--json"], capture_output=True, text=True, timeout=30)
        logged = bool(json.loads(r.stdout or "{}").get("loggedIn"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        logged = None
    if logged:
        note("Claude Code sign-in", "ok")
    elif logged is False:
        note("Claude Code sign-in", "next", "run: claude auth login   (Claude Code's own browser sign-in)")
    else:
        note("Claude Code sign-in", "warn", "could not tell; run: claude auth status")


def main() -> int:
    say("boardwright setup" + ("  (check only: nothing will be changed)" if CHECK else ""))
    uv = step_uv()
    step_buddy(uv)
    step_mcp(uv)
    step_kicad()
    step_claude()
    bad = [r for r in results if r[1] in ("FAIL", "missing")]
    say("\nSummary: " + ("everything is in place." if not bad else
                         f"{len(bad)} item(s) need you: " + "; ".join(f"{s} ({d})" for s, _, d in bad)))
    for s, _, d in (r for r in results if r[1] == "next"):
        say(f"Then: {d}")
    say("Next: open your board's folder in Claude Code and run /boardwright:pcb-doctor")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
