#!/usr/bin/env python3
"""Boardwright MCP server: the read-only and checking scripts as tools for any MCP-capable agent.

Usage:  python bw_mcp.py        (run by the agent; speaks MCP over stdin/stdout)

Register it in the agent as command `python`, args [<path>/plugin/scripts/bw_mcp.py], working
directory = the project folder. Every tool also takes an optional `project` argument (a folder).

Transport: JSON-RPC 2.0, one message per line, standard library only. Methods: initialize,
notifications/initialized, tools/list, tools/call, ping.

Tools: status, plan, run_gates, sch_check, history_list, fab_check, routing_plan_show, board_find.
There are deliberately NO editing tools: no board edits, no restore, no routing-plan approval, no
plan --done. Editing stays in the agent's own shell under the project rules (AGENTS.md).
Every tool refuses a `project` folder that has neither PROJECT.md nor boardwright.json. run_gates always
runs with --no-export (it never regenerates fab/). history_list never creates a history: with none yet
it answers "no history yet".
Each tool runs one script in the project folder with a 300 s timeout and returns its output text
and exit code (0 passed, 1 a check failed, 2 setup problem). Results are cut at about 20,000 characters.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PROTOCOL = "2025-06-18"
TIMEOUT = 300
MAX_CHARS = 20000

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_PROP = {"type": "string", "description": "Project folder (default: the server's working directory)."}


def _schema(props=None, required=None):
    p = {"project": PROJECT_PROP}
    p.update(props or {})
    s = {"type": "object", "properties": p}
    if required:
        s["required"] = required
    return s


TOOLS = [
    ("status", "Where the project is: gates, stage reports, PROJECT.md headlines (read-only).", _schema()),
    ("plan", "What to do next: READY NOW steps, user steps, failed gates, reopened steps (read-only).", _schema()),
    ("run_gates", "Run the rule guard, ERC and DRC. Always runs with --no-export: it never makes or "
     "changes fab files (the release is made in the agent's own shell). Writes reports/gates.json. "
     "Exit 0 passed, 1 failed.", _schema()),
    ("sch_check", "Schematic checks: fields, footprints, pins, unconnected pins, decoupling.", _schema()),
    ("history_list", "The saved design steps, newest first (read-only: answers \"no history yet\" when there is none).",
     _schema({"count": {"type": "integer", "default": 20, "description": "How many steps."}})),
    ("fab_check", "Board setup and net classes against the factory's published minimums (changes nothing).",
     _schema({"fab": {"type": "string", "description": "Factory name (default: from boardwright.json)."}})),
    ("routing_plan_show", "The routing plan (corridors and their status) as a table.", _schema()),
    ("board_find", "Search the board (read-only, nothing saved): footprints, pads, tracks, vias, zones, nets.",
     _schema({"selector": {"type": "object",
                           "description": "e.g. {\"kind\": \"pad\", \"ref\": \"C3\"}. Keys: kind "
                                          "(footprint|pad|track|via|zone|net), ref, net, layer, near [x,y,r], limit."}},
             ["selector"])),
]


def _kicad_python():
    from kicad_python import find
    return find()


def is_project(proj):
    return (Path(proj) / "PROJECT.md").is_file() or (Path(proj) / "boardwright.json").is_file()


def has_history(proj):
    """True when the project already has saved steps. Never creates anything."""
    if (Path(proj) / ".boardwright" / "history.git" / "HEAD").is_file():
        return True
    try:
        r = subprocess.run(["git", "-C", str(proj), "for-each-ref", "--count=1", "--format=%(refname)",
                            "refs/boardwright/steps"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def _command(name, a, proj):
    py = sys.executable
    s = lambda f: str(HERE / f)  # noqa: E731
    if name == "status":
        return [py, s("status.py"), proj]
    if name == "plan":
        return [py, s("plan.py"), proj]
    if name == "run_gates":
        return [py, s("run_gates.py"), proj, "--no-export"]
    if name == "sch_check":
        return [py, s("sch_check.py"), proj]
    if name == "history_list":
        return [py, s("history.py"), proj, "list", str(int(a.get("count", 20)))]
    if name == "fab_check":
        cmd = [py, s("fab_rules.py"), proj, "check"]
        if a.get("fab"):
            cmd += ["--fab", str(a["fab"])]
        return cmd
    if name == "routing_plan_show":
        return [py, s("routing_plan.py"), proj, "show"]
    if name == "board_find":
        sel = a.get("selector")
        if not isinstance(sel, dict):
            raise ValueError("selector must be an object, e.g. {\"kind\": \"pad\", \"ref\": \"C3\"}")
        kpy = _kicad_python()
        if not kpy:
            raise ValueError("KiCad's Python not found (set KICAD_CLI); board_find needs it")
        return [kpy, "-I", s("bw_edit.py"), proj, json.dumps({"find": sel})]
    raise KeyError(name)


def call_tool(name, args):
    """Return (text, is_error)."""
    if name not in {t[0] for t in TOOLS}:
        return f"unknown tool: {name}", True
    args = args or {}
    proj = Path(args.get("project") or Path.cwd()).resolve()
    if not proj.is_dir():
        return f"project folder not found: {proj}", True
    if not is_project(proj):
        return f"not a Boardwright project: {proj} has neither PROJECT.md nor boardwright.json", True
    if name == "history_list" and not has_history(proj):
        return "no history yet (no design step has been saved in this project)\n[exit code 0]", False
    try:
        cmd = _command(name, args, str(proj))
    except (ValueError, TypeError) as e:
        return str(e), True
    try:
        r = subprocess.run(cmd, cwd=str(proj), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"{name} timed out after {TIMEOUT} s", True
    except OSError as e:
        return f"{name} could not start: {e}", True
    out = r.stdout or ""
    if r.stderr.strip():
        out += ("\n" if out else "") + "[stderr]\n" + r.stderr
    if len(out) > MAX_CHARS:
        out = out[:MAX_CHARS] + f"\n[... cut at {MAX_CHARS} characters; full detail is in reports/]"
    out += f"\n[exit code {r.returncode}]"
    # A failed check (1) is a valid answer, not a tool error; 2 is a setup problem.
    return out, r.returncode not in (0, 1)


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return {"protocolVersion": want if want in ("2024-11-05", "2025-03-26", PROTOCOL) else PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "boardwright", "version": "0.1.0"},
                "instructions": "Read-only and checking tools for a Boardwright KiCad project. "
                                "Editing is done in your own shell under AGENTS.md."}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": sc} for n, d, sc in TOOLS]}
    if method == "tools/call":
        p = msg.get("params") or {}
        text, err = call_tool(p.get("name"), p.get("arguments"))
        return {"content": [{"type": "text", "text": text}], "isError": err}
    if mid is None:  # notification (notifications/initialized etc.): no reply
        return None
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            mid = msg.get("id") if isinstance(msg, dict) else None
            try:
                res = handle(msg)
                reply = None if res is None or (isinstance(msg, dict) and "id" not in msg) else \
                    {"jsonrpc": "2.0", "id": mid, "result": res}
            except LookupError as e:
                reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {e}"}}
            except Exception as e:  # keep the server alive
                reply = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"internal error: {e}"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
