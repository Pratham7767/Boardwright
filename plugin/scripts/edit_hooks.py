#!/usr/bin/env python3
"""Claude Code hooks for design history and the one-editor lock (PreToolUse, PostToolUse, Stop).

    python edit_hooks.py pre | post | stop | prompt      (reads the hook's JSON on stdin)

prompt: the designer's routing plan decisions, taken from what they typed (/boardwright:pcb-plan
      approve c1, reject c2, on, off): recorded here, so Claude cannot approve its own plan.

pre:  before a tool that changes a design file, take the project's edit lock for this session. If
      another session holds it, the tool is denied with who holds it; the session may still read.
post: after any edit (or shell command), save a history step if a design file changed.
stop: at the end of the turn, give the lock back.

Runs only in a boardwright project (boardwright.json or PROJECT.md). Never breaks a session: any
error is swallowed and the tool goes ahead. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history  # noqa: E402
import routing_plan  # noqa: E402

WRITE_MCP = re.compile(
    r"^mcp__plugin_boardwright_kicad-(live__(pcb_(add|delete|place|align|paste|refill|revert|save|set)"
    r"|sch_(add|delete|set)|lib_(create|copy|add|upgrade)|kicad_run_action)"
    r"|schematic__(add|remove|move|place|set|connect|wire|no_connect|modify|auto_place))")


def is_design_path(p: str) -> bool:
    name = Path(p).name
    return name.endswith(history.DESIGN_EXT) or name in history.DESIGN_NAMES


def is_edit(tool: str, inp: dict) -> bool:
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return is_design_path(str(inp.get("file_path", "")))
    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        writes = re.search(r'"(move|set|add|delete|netclass|rule|refill|place|route)"\s*:', cmd)
        return ("bw_edit.py" in cmd and (bool(writes) or "@" in cmd)) or bool(
            re.search(r"history\.py\S*\s+\S+\s+restore", cmd))
    return bool(WRITE_MCP.match(tool))


def plan_guard(proj: Path, tool: str, inp: dict) -> str:
    """Why a tool must not run under the routing plan rules, or ''."""
    if tool in ("Edit", "Write", "MultiEdit") and Path(str(inp.get("file_path", ""))).name.startswith("routing-plan."):
        return ("the plan file records the designer's decisions and is not edited by hand. Propose changes with "
                "routing_plan.py propose; the designer approves with /boardwright:pcb-plan.")
    cmd = str(inp.get("command", "")) if tool in ("Bash", "PowerShell") else ""
    target = r"\S*routing-plan\.(?:json|md)"
    if cmd and re.search(r">>?\s*['\"]?" + target                       # redirected into it
                         + r"|\bsed\b[^|;&]*\s-i[^|;&]*" + target          # edited in place
                         + r"|\b(?:cp|mv|copy|move|Copy-Item|Move-Item)\b[^|;&]*\s" + target + r"['\"]?\s*(?:$|[|;&])"
                         + r"|(?:Set-Content|Out-File|Add-Content)\b[^|;&]*" + target
                         + r"|" + target + r"['\"]?\)\.write_text|open\(['\"]" + target + r"['\"],\s*['\"][wa]", cmd):
        return "the plan file is not written from the shell; use routing_plan.py propose."
    if tool.endswith("kicad-live__pcb_add_tracks") or tool.endswith("kicad-live__pcb_add_vias"):
        nets = sorted({str(s.get("net", "")) for s in (inp.get("segments") or inp.get("vias") or [])} - {""})
        blocked = routing_plan.gate(proj, nets)
        if blocked:
            return "; ".join(f"{n}: {w}" for n, w in blocked.items())
    return ""


def project(data: dict) -> Path | None:
    p = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    return p if (p / "boardwright.json").is_file() or (p / "PROJECT.md").is_file() else None


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    data = json.loads(sys.stdin.read() or "{}")
    proj = project(data)
    if not proj:
        return
    who = str(data.get("session_id") or "unknown")
    tool, inp = str(data.get("tool_name", "")), data.get("tool_input") or {}
    if mode == "prompt":
        # The designer's own decisions, recorded from what they typed: Claude has no command for these.
        said = str(data.get("prompt", "")).strip()
        m = re.match(r"^/(?:boardwright:)?pcb-plan\s+(.*)$", said, re.S)
        if m:
            words = m.group(1).split()
            if words and words[0] in ("on", "off"):
                cfg = proj / "boardwright.json"
                d = json.loads(cfg.read_text("utf-8")) if cfg.is_file() else {}
                d["routing_plan"] = words[0] == "on"
                cfg.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", "utf-8")
                print(f"Routing plan mode turned {words[0]} by the designer (recorded by the plugin in boardwright.json).")
            else:
                msg = routing_plan.decide(proj, words, said)
                if msg:
                    print(msg)
        return
    if mode == "pre":
        why = plan_guard(proj, tool, inp)
        if why:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": "Boardwright routing plan: " + why}}))
            return
    if mode == "pre" and is_edit(tool, inp):
        other = history.lock_take(proj, who, "session " + who[:8])
        if other:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Boardwright: another Claude session is editing this board: " + history.describe(other)
                    + ". Only one session edits at a time. Read only, or tell the user to finish or close the "
                    "other session (the lock frees at the end of its turn, or after 30 minutes idle).")}}))
    elif mode == "post":
        if is_edit(tool, inp):
            history.lock_take(proj, who, "session " + who[:8])
        note = tool if tool != "Bash" else "shell: " + str(inp.get("command", ""))[:60].replace("\n", " ")
        history.Store(proj).snap(note.replace("mcp__plugin_boardwright_", ""))
    elif mode == "stop":
        history.lock_release(proj, who)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
