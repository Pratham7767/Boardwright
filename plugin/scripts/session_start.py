#!/usr/bin/env python3
"""SessionStart hook: put the project's status and plan into Claude's context.

Runs only in a boardwright project (a folder with boardwright.json or
PROJECT.md).  Anywhere else it prints nothing, so it costs nothing.  It saves
the two tool calls the skill would otherwise make at the start of every
session, and it warns when the project's copy of the gate scripts is older
than the plugin's.  Never fails the session: every error is swallowed.
Standard library only.
"""
from __future__ import annotations

import hashlib
import os
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

PLUGIN_SCRIPTS = Path(__file__).resolve().parent
MAX_LINES = 60


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run(script: Path, proj: Path) -> list:
    try:
        r = subprocess.run([sys.executable, str(script), "."], cwd=str(proj), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=20)
        return (r.stdout or r.stderr or "").strip().splitlines()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"({script.name} did not run: {exc})"]


def main() -> None:
    proj = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not ((proj / "boardwright.json").is_file() or (proj / "PROJECT.md").is_file()):
        return
    local = proj / "scripts"
    if not (local / "status.py").is_file() or not (local / "plan.py").is_file():
        print("boardwright project, but its scripts/ folder is missing or incomplete. Run: "
              f'python "{PLUGIN_SCRIPTS / "init_project.py"}" . --update-scripts')
        return
    stale = sorted(f.name for f in list(PLUGIN_SCRIPTS.glob("*.py")) + list(PLUGIN_SCRIPTS.glob("*.json"))
                   if f.name not in ("session_start.py", "setup.py", "selftest.py", "init_project.py")
                   and (local / f.name).is_file() and digest(local / f.name) != digest(f))
    out = ["boardwright session start (from the plugin's hook; you need not run status.py or plan.py again now):"]
    out += run(local / "status.py", proj) + [""] + run(local / "plan.py", proj)
    if len(out) > MAX_LINES:
        out = out[:MAX_LINES] + [f"... ({len(out) - MAX_LINES} more lines: python scripts/plan.py .)"]
    try:
        sys.path.insert(0, str(PLUGIN_SCRIPTS))
        import choices
        decided = (proj / ".boardwright" / "diagnostics" / "consent.json").is_file()
        if not decided and not choices.get(proj, "diagnostics_asked"):
            out.append("Diagnostics not decided yet: at a natural pause, ask the user once with the Diagnostics "
                       "question (buttons) described in the skill. Never decide it yourself.")
    except Exception:
        pass
    if stale:
        out.append(f"Note: {len(stale)} script(s) in scripts/ differ from this plugin version ({', '.join(stale)}). "
                   "Offer the user: python \"" + str(PLUGIN_SCRIPTS / "init_project.py") + "\" . --update-scripts")
    print("\n".join(out))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
