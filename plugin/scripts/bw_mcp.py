#!/usr/bin/env python3
"""Boardwright MCP server: the plugin's checks and board edits as 15 small tools for any MCP client.

Usage:  python bw_mcp.py        (run by the client; speaks MCP over stdin/stdout)

Register it as command `python`, args [<path>/plugin/scripts/bw_mcp.py]. Every tool takes an optional
`project` folder (default: the working directory; if that is not a Boardwright project, the folder in the
environment variable CLAUDE_PROJECT_DIR). A folder without PROJECT.md or boardwright.json is refused.

Transport: JSON-RPC 2.0, one message per line, standard library only. Methods: initialize,
notifications/initialized, tools/list, tools/call, ping. Protocol version 2025-06-18.

Tools: status, check, find, edit, place, route, history, plan, fab, lifecycle, diagnostics, engine,
setup (new project, update scripts, doctor), digest (board summary), export (release fab files, sim files,
pre-compliance pack, parts register, datasheet index). `parts` of the plan is not built yet.

Guards that live in the server, so clients without Claude Code hooks are protected too:
  - every write tool (edit, place, route, plan propose|draw, fab write, engine run, setup update, export)
    takes the project's
    edit lock (history.lock_take) first, refuses with the holder's description when someone else holds it,
    saves a history step afterwards and releases the lock at the end of the call;
  - NO tool exists for routing-plan approval, diagnostics consent or history restore: those are the
    user's alone (/boardwright:pcb-plan, /boardwright:pcb-diagnostics, /boardwright:pcb-undo);
  - the mains/hazardous/fast-net and routing-plan refusals stay in bw_edit.py and routing_plan.py; their
    answers are passed through unchanged.
Scripts run from this folder, one child process per call, 600 s at most. Answers are short plain text, cut
at 12,000 characters; the reply also carries structuredContent {ok, exit_code}.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PROTOCOL = "2025-06-18"
TIMEOUT = 600
MAX_CHARS = 12000
WHO = "mcp-" + uuid.uuid4().hex[:8]       # this server process, as an editor of the board

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

INSTRUCTIONS = (
    "Boardwright: checks and edits for a KiCad project (status, check, find, edit, place, route, plan, history, "
    "fab, lifecycle, diagnostics, engine, setup, digest, export). Board edits need KiCad closed; with it open use the kicad-live tools. "
    "Every edit takes the project's one-editor lock and saves an undoable history step. Routing-plan approvals, "
    "diagnostics consent and history restore are the user's alone and have no tool: ask the user to type "
    "/boardwright:pcb-plan, /boardwright:pcb-diagnostics or /boardwright:pcb-undo. Pass `project` when the "
    "working folder is not the project.")

CHECK_KINDS = ["gates", "sch", "safety", "emc", "hs", "pdn", "impedance", "fab", "lifecycle", "blocks", "all"]
# kind -> [(label, script, extra args)]
CHECKS = {
    "gates": [("gates", "run_gates.py", ["--no-export"])],
    "sch": [("sch", "sch_check.py", [])],
    "safety": [("safety_class", "safety_class.py", []), ("mains", "mains_check.py", []),
               ("creepage", "creepage_rules.py", []), ("barrier", "barrier_check.py", [])],
    "emc": [("emc_geometry", "emc_geometry.py", []), ("emc_rules", "emc_rules.py", []),
            ("emc_harmonics", "emc_harmonics.py", [])],
    "hs": [("hs", "hs_rules.py", [])],
    "pdn": [("pdn", "pdn_check.py", [])],
    "impedance": [("impedance", "impedance_check.py", [])],
    "fab": [("fab", "fab_rules.py", ["check"])],
    "lifecycle": [("lifecycle", "lifecycle_check.py", ["--offline"])],
    "blocks": [("blocks", "block_check.py", [])],
}
CHECK_ORDER = ["gates", "sch", "safety", "emc", "hs", "pdn", "impedance", "fab", "lifecycle", "blocks"]
FAIL_LINE = re.compile(r"\b(FAIL|FAILED|ERROR|CRITICAL|NOT PASSED|refused|unconnected)\b|\bHIGH\b")

DIGEST_SECTIONS = ["summary", "parts", "nets", "unrouted", "near", "net", "area", "all"]
P = {"type": "string", "description": "Project folder (default: working dir)."}
B = {"type": "boolean"}
S = {"type": "string"}


def _schema(props=None, required=None):
    p = {"project": P}
    p.update(props or {})
    s = {"type": "object", "properties": p}
    if required:
        s["required"] = required
    return s


def _enum(*vals):
    return {"type": "string", "enum": list(vals)}


TOOLS = [
    ("status", "Where the project is and what to do next (stages, gates, ready steps).",
     _schema({"full": B}), True),
    ("check", "Run checks and answer one line each, failures only; kind picks the checks.",
     _schema({"kind": _enum(*CHECK_KINDS), "detail": B}, ["kind"]), False),
    ("find", "Search the board without changing it: footprints, pads, tracks, vias, zones, nets.",
     _schema({"selector": {"type": "object", "description": "{kind: footprint|pad|track|via|zone|net, ref, net, "
                                                           "layer, near: [x,y,r], limit}"}}, ["selector"]), True),
    ("edit", "Edit the board with a list of ops (move, set, add, delete, netclass, rule, refill); dry_run saves nothing.",
     _schema({"ops": {"type": "array", "items": {"type": "object"}}, "dry_run": B}, ["ops"]), False),
    ("place", "Place one footprint near a pin or point, trying the allowed rotations.",
     _schema({"ref": S, "near": S, "within": {"type": "number"}, "side": S, "rot": {"type": "array"}, "dry_run": B},
             ["ref", "near"]), False),
    ("route", "Route the named ordinary nets; mains, hazardous and fast nets are refused.",
     _schema({"nets": {"type": "array", "items": S}, "width": {"type": "number"}, "layers": {"type": "array"},
              "vias": B, "dry_run": B}, ["nets"]), False),
    ("history", "List saved design steps or diff two of them (undo is the user's: /boardwright:pcb-undo).",
     _schema({"action": _enum("list", "diff"), "count": {"type": "integer"}, "a": S, "b": S}, ["action"]), True),
    ("plan", "Routing plan: show, propose a plan, draw it on the board or verify tracks (approval is the user's).",
     _schema({"action": _enum("show", "propose", "draw", "verify"), "plan": {"type": "object"}}, ["action"]), False),
    ("fab", "Factory rules: list the factories, check the board against one, or write its limits to the rules file.",
     _schema({"action": _enum("list", "check", "write"), "factory": S}, ["action"]), False),
    ("lifecycle", "Part lifecycle from LCSC listings (asks LCSC; offline uses the cache).",
     _schema({"refresh": B, "offline": B}), False),
    ("diagnostics", "Local diagnostics: status, build the report, or export the zip (consent is the user's).",
     _schema({"action": _enum("status", "report", "export")}, ["action"]), False),
    ("engine", "The deterministic place-and-route engine: status, leftovers (last run) or run.",
     _schema({"action": _enum("status", "leftovers", "run"), "args": {"type": "array", "items": S}}, ["action"]), False),
    ("setup", "New project folder (project = the folder, name optional), update its scripts, or doctor (setup check).",
     _schema({"action": _enum("new", "update", "doctor"), "name": S}, ["action"]), False),
    ("digest", "Short text summary of the board: summary, parts, nets, unrouted, near [REF, mm], net [NAME], area [x1,y1,x2,y2].",
     _schema({"section": _enum(*DIGEST_SECTIONS), "args": {"type": "array"}}), True),
    ("export", "Write files: release (fab/, only if all gates pass), sim, precompliance, parts register, datasheet index.",
     _schema({"action": _enum("release", "sim", "precompliance", "parts", "datasheets"),
              "names": {"type": "array", "items": S}, "all": B, "pages": S, "force": B}, ["action"]), False),
]
NAMES = {t[0] for t in TOOLS}


# ---------------------------------------------------------------- helpers

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


def cap(text, limit=MAX_CHARS):
    """At most LIMIT characters, cut at a line end, with a note saying how many lines went."""
    if len(text) <= limit:
        return text
    lines, used, keep = text.split("\n"), 0, 0
    for i, ln in enumerate(lines):
        if used + len(ln) + 1 > limit - 100:
            break
        used += len(ln) + 1
        keep = i + 1
    rest = len(lines) - keep
    return "\n".join(lines[:keep]) + f"\n(cut: {rest} more lines; ask with detail or a narrower selector)"


def run(cmd, proj, timeout=TIMEOUT, env=None):
    """(output text, exit code). 124 = timed out, 127 = could not start."""
    try:
        r = subprocess.run(cmd, cwd=str(proj), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return f"timed out after {int(timeout)} s", 124
    except OSError as e:
        return f"could not start: {e}", 127
    out = (r.stdout or "").strip()
    if r.stderr.strip() and r.returncode != 0:
        out += ("\n" if out else "") + "[stderr] " + r.stderr.strip()[-1500:]
    return out, r.returncode


def py(script, proj, *args):
    return [sys.executable, str(HERE / script), str(proj), *args]


def resolve_project(args):
    """(Path, error text). Default: the working directory, else CLAUDE_PROJECT_DIR."""
    given = args.get("project")
    if given:
        cands = [Path(str(given))]
    else:
        cands = [Path.cwd()]
        env = os.environ.get("CLAUDE_PROJECT_DIR")
        if env:
            cands.append(Path(env))
    for c in cands:
        try:
            c = c.resolve()
        except OSError:
            continue
        if c.is_dir() and is_project(c):
            return c, ""
    first = cands[0]
    if not first.is_dir():
        return None, f"project folder not found: {first}"
    return None, f"not a Boardwright project: {first} has neither PROJECT.md nor boardwright.json"


def write_call(proj, tool, fn, snap=True):
    """Run FN() -> (text, rc) while holding the edit lock; save a history step afterwards. -> (text, rc, err)."""
    import history
    try:
        other = history.lock_take(proj, WHO, "boardwright MCP " + tool)
    except OSError as e:
        return f"could not take the edit lock: {e}", 2, True
    if other:
        return ("refused: another editor holds this board: " + history.describe(other)
                + ". Only one editor at a time: wait until it finishes, or read only."), 1, True
    try:
        text, rc = fn()
        if snap:
            try:
                if history.Store(proj).snap("mcp: " + tool) and rc == 0:
                    text += "\n(history step saved)"
            except Exception:
                pass
        return text, rc, rc not in (0, 1)
    finally:
        try:
            history.lock_release(proj, WHO)
        except Exception:
            pass


def bw_edit(proj, ops, dry=False):
    """Run bw_edit.py with OPS through a temp file; (text, rc)."""
    fd, path = tempfile.mkstemp(prefix="bw_ops_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ops, f)
        return run(py("bw_edit.py", proj, "@" + path, *(["--dry-run"] if dry else [])), proj)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------- tools

def t_status(proj, a):
    full = bool(a.get("full"))
    out1, rc1 = run(py("status.py", proj), proj)
    out2, rc2 = run(py("plan.py", proj, *(["--all"] if full else [])), proj)
    if not full and "NEXT AFTER THAT:" in out2:
        out2 = out2.split("NEXT AFTER THAT:")[0].rstrip() + "\n(more steps later: ask with full)"
    return out1 + "\n\n" + out2, max(rc1, rc2), max(rc1, rc2) not in (0, 1)


def _gate_rows(out):
    """[(gate, status, detail)] from run_gates' result table."""
    rows = []
    for ln in out.splitlines():
        c = [x.strip() for x in ln.strip().strip("|").split("|")]
        if ln.startswith("|") and len(c) >= 3 and c[0] not in ("Gate", "---") and set(c[1]) != {"-"}:
            rows.append((c[0], c[1], c[2]))
    return rows


def _summarize(label, rc, out, detail):
    word = {0: "ok", 1: "FAIL", 124: "TIMEOUT", 127: "NOT RUN"}.get(rc, "setup problem")
    last = ""
    rows = _gate_rows(out) if label == "gates" else []
    if rows:
        bad = [r for r in rows if r[1] not in ("pass", "note")]
        head = f"gates: {word} - {sum(r[1] == 'pass' for r in rows)} of {len(rows)} pass"
        if detail:
            return head + "\n" + out
        return head + "".join(f"\n  {g}: {st} ({d[:150]})" for g, st, d in bad)
    for ln in reversed(out.splitlines()):
        s = ln.strip()
        if s and not s.startswith(("|", "#", "-", "[stderr]", "=", "(")):
            last = s[:170]
            break
    head = f"{label}: {word}" + (f" (exit {rc})" if rc not in (0, 1) else "") + (f" - {last}" if last else "")
    if detail:
        return head + "\n" + out
    if rc == 0:
        return head
    if rc == 1:
        bad = [ln.strip()[:200] for ln in out.splitlines() if FAIL_LINE.search(ln)][:10]
    else:
        bad = [ln.strip()[:200] for ln in out.splitlines() if ln.strip()][:3]
    return head + "".join("\n  " + b for b in bad if b != last)


def _has_barrier(proj):
    try:
        cfg = json.loads((proj / "boardwright.json").read_text("utf-8"))
    except (OSError, ValueError):
        return False
    return bool(cfg.get("barrier") or (cfg.get("safety") or {}).get("barriers"))


def t_check(proj, a):
    kind = a.get("kind")
    if kind not in CHECK_KINDS:
        return "kind must be one of: " + ", ".join(CHECK_KINDS), 2, True
    detail = bool(a.get("detail"))
    kinds = CHECK_ORDER if kind == "all" else [kind]
    deadline = time.time() + TIMEOUT
    lines, worst = [], 0
    for k in kinds:
        for label, script, extra in CHECKS[k]:
            left = deadline - time.time()
            if left < 5:
                lines.append(f"{label}: skipped (call time used up; ask for this kind alone)")
                worst = max(worst, 2)
                continue
            if script == "barrier_check.py" and not _has_barrier(proj):
                lines.append(f"{label}: not applicable (no barrier section in boardwright.json)")
                continue
            out, rc = run(py(script, proj, *extra), proj, timeout=left)
            lines.append(_summarize(label, rc, out, detail))
            worst = max(worst, rc if rc in (0, 1) else 2)
    return "\n".join(lines), worst, worst == 2


def t_find(proj, a):
    sel = a.get("selector")
    if not isinstance(sel, dict):
        return 'selector must be an object, e.g. {"kind": "pad", "ref": "C3"}', 2, True
    out, rc = run(py("bw_edit.py", proj, json.dumps({"find": sel})), proj)
    return out, rc, rc not in (0, 1)


def t_edit(proj, a):
    ops = a.get("ops")
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list) or not ops or not all(isinstance(o, dict) for o in ops):
        return "ops must be a non-empty list of objects, e.g. [{\"move\": \"H1\", \"rot\": 45}]", 2, True
    dry = bool(a.get("dry_run"))
    if dry or all(set(o) == {"find"} for o in ops):
        out, rc = bw_edit(proj, ops, dry)
        return out, rc, rc not in (0, 1)
    return write_call(proj, "edit", lambda: bw_edit(proj, ops))


def t_place(proj, a):
    spec = {k: a[k] for k in ("ref", "near", "within", "side", "rot") if a.get(k) is not None}
    if "ref" not in spec or "near" not in spec:
        return "place needs ref and near, e.g. {\"ref\": \"C3\", \"near\": \"U1.17\"}", 2, True
    dry = bool(a.get("dry_run"))
    if dry:
        out, rc = bw_edit(proj, [{"place": spec}], True)
        return out, rc, rc not in (0, 1)
    return write_call(proj, "place", lambda: bw_edit(proj, [{"place": spec}]))


def t_route(proj, a):
    nets = a.get("nets")
    if not isinstance(nets, list) or not nets:
        return "nets must be a non-empty list of net names", 2, True
    op = {"route": nets}
    for k in ("width", "layers", "vias"):
        if a.get(k) is not None:
            op[k] = a[k]
    dry = bool(a.get("dry_run"))
    if dry:
        out, rc = bw_edit(proj, [op], True)
        return out, rc, rc not in (0, 1)
    return write_call(proj, "route", lambda: bw_edit(proj, [op]))


def t_history(proj, a):
    act = a.get("action")
    if act == "restore":
        return "restore is the user's: ask them to type /boardwright:pcb-undo (it needs their decision).", 1, True
    if act not in ("list", "diff"):
        return "action must be list or diff", 2, True
    if not has_history(proj):
        return "no history yet (no design step has been saved in this project)", 0, False
    if act == "list":
        out, rc = run(py("history.py", proj, "list", str(int(a.get("count") or 20))), proj)
    else:
        if not a.get("a"):
            return "diff needs a (a step number from list); b is optional", 2, True
        out, rc = run(py("history.py", proj, "diff", str(a["a"]), *([str(a["b"])] if a.get("b") else [])), proj)
    return out, rc, rc not in (0, 1)


def t_plan(proj, a):
    act = a.get("action")
    if act in ("approve", "reject", "on", "off"):
        return ("approving, rejecting or switching routing-plan mode is the designer's: ask them to type "
                "/boardwright:pcb-plan approve c1 (or reject, on, off)."), 1, True
    if act in ("show", "verify"):
        out, rc = run(py("routing_plan.py", proj, act), proj)
        return out, rc, rc not in (0, 1)
    if act == "draw":
        return write_call(proj, "plan draw", lambda: run(py("routing_plan.py", proj, "draw"), proj))
    if act == "propose":
        plan = a.get("plan")
        if not isinstance(plan, dict):
            return "propose needs plan: {planes: [...], corridors: [{id, nets, layers, path, ...}]}", 2, True

        def go():
            fd, path = tempfile.mkstemp(prefix="bw_plan_", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(plan, f)
                return run(py("routing_plan.py", proj, "propose", "@" + path), proj)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        return write_call(proj, "plan propose", go)
    return "action must be show, propose, draw or verify", 2, True


def t_fab(proj, a):
    act = a.get("action")
    if act not in ("list", "check", "write"):
        return "action must be list, check or write", 2, True
    extra = ["--fab", str(a["factory"])] if a.get("factory") and act != "list" else []
    cmd = py("fab_rules.py", proj, act, *extra)
    if act == "write":
        return write_call(proj, "fab write", lambda: run(cmd, proj))
    out, rc = run(cmd, proj)
    return out, rc, rc not in (0, 1)


def t_lifecycle(proj, a):
    extra = (["--refresh"] if a.get("refresh") else []) + (["--offline"] if a.get("offline") else [])
    out, rc = run(py("lifecycle_check.py", proj, *extra), proj)
    return out, rc, rc not in (0, 1)


def t_diagnostics(proj, a):
    act = a.get("action")
    if act in ("on", "off", "delete", "consent"):
        return ("diagnostics consent is the user's alone: ask them to type /boardwright:pcb-diagnostics on or off."), 1, True
    if act not in ("status", "report", "export"):
        return "action must be status, report or export", 2, True
    out, rc = run(py("diagnostics.py", proj, act), proj)
    return out, rc, rc not in (0, 1)


def t_engine(proj, a):
    act = a.get("action")
    if act not in ("status", "leftovers", "run"):
        return "action must be status, leftovers or run", 2, True
    eng = HERE / "engine.py"
    if not eng.is_file():
        return "the deterministic engine arrives in phase B; nothing to run yet.", 0, False
    extra = [str(x) for x in (a.get("args") or [])]
    cmd = [sys.executable, str(eng), str(proj), act, *extra]
    if act == "run" and "--dry-run" not in extra:
        env = dict(os.environ, BOARDWRIGHT_LOCK_WHO=WHO)     # the engine takes the lock under this server's name
        return write_call(proj, "engine run", lambda: run(cmd, proj, env=env))
    out, rc = run(cmd, proj)
    return out, rc, rc not in (0, 1)


def _init_answer(out, rc, where, what):
    """init_project prints one line per file; answer with the counts and the files it kept."""
    if rc != 0:
        return out, rc
    ls = out.splitlines()
    kept = [x.strip() for x in ls if x.startswith("kept")]
    head = (f"{what} {where}: {sum(x.startswith('created') for x in ls)} files created, "
            f"{sum(x.startswith('copied') for x in ls)} scripts copied, {len(kept)} kept (existing files are never overwritten)")
    more = f"\n  ... {len(kept) - 8} more kept" if len(kept) > 8 else ""
    return head + "".join("\n  " + k[:160] for k in kept[:8]) + more, rc


def setup_new(a):
    """A new project folder; the `project` argument names it. Not a project yet: no lock, no history."""
    given = a.get("project")
    if not given:
        return "new needs project: the folder to create (existing files in it are never overwritten)", 2, True
    target = Path(str(given))
    if not target.is_absolute():
        target = Path.cwd() / target
    if target.exists() and not target.is_dir():
        return f"not a folder: {target}", 2, True
    name = str(a["name"]) if a.get("name") else None
    if name is not None and (not name.strip() or name.startswith("-")):
        return "name must be a plain project name", 2, True
    out, rc = run([sys.executable, str(HERE / "init_project.py"), str(target), *(["--name", name] if name else [])], HERE)
    text, rc = _init_answer(out, rc, str(target), "new project")
    return text, rc, rc not in (0, 1)


def _doctor_short(out, rc):
    rows = [ln for ln in out.splitlines() if " | " in ln][1:]
    bad = [r for r in rows if r.split(" | ")[1].strip() != "ok"]
    head = f"doctor: {len(rows) - len(bad)} ok, {len(bad)} not ok"
    return head + "".join("\n  " + re.sub(r"\s{2,}", " ", b) for b in bad), rc


def t_setup(proj, a):
    act = a.get("action")
    if act == "doctor":
        out, rc = run(py("doctor.py", proj), proj)
        text, rc = _doctor_short(out, rc) if rc in (0, 1) else (out, rc)
        return text, rc, rc not in (0, 1)
    if act == "update":
        def go():
            out, rc = run([sys.executable, str(HERE / "init_project.py"), str(proj), "--update-scripts"], HERE)
            return _init_answer(out, rc, str(proj), "scripts updated in")
        return write_call(proj, "setup update", go)
    return "action must be new, update or doctor", 2, True


def t_digest(proj, a):
    sec = a.get("section") or "summary"
    if sec not in DIGEST_SECTIONS:
        return "section must be one of: " + ", ".join(DIGEST_SECTIONS), 2, True
    extra = [str(x) for x in (a.get("args") or [])] if sec in ("near", "net", "area") else []
    if (sec in ("near", "net") and not extra) or (sec == "area" and len(extra) != 4):
        return "near needs args [REF, mm?], net needs [NAME], area needs [x1, y1, x2, y2]", 2, True
    out, rc = run(py("board_digest.py", proj, "--section", sec, *extra), proj)
    return out, rc, rc not in (0, 1)


def _datasheet_cmd(proj, a, pages):
    script = str(HERE / "datasheet_index.py")
    uv = shutil.which("uv")      # the script's inline metadata pulls pypdf
    base = [uv, "run", script] if uv else [sys.executable, script]
    return [*base, str(proj), *[str(n) for n in (a.get("names") or [])], *(["--all"] if a.get("all") else []),
            *(["--pages", pages] if pages else []), *(["--force"] if a.get("force") else [])]


def t_export(proj, a):
    act = a.get("action")
    if act == "release":
        def go():
            out, rc = run(py("run_gates.py", proj), proj)
            text = _summarize("gates", rc, out, False)
            if rc == 0:
                text += "\nfab files written to fab/ (the release stops here: nothing is sent or ordered)"
            elif rc == 1:
                text += "\nnothing exported: a gate failed. Stop and show reports/gates.md."
            return text, rc
        return write_call(proj, "export release", go)
    if act in ("sim", "precompliance", "parts"):
        script = {"sim": "sim_export.py", "precompliance": "precompliance_pack.py", "parts": "parts_register.py"}[act]
        return write_call(proj, "export " + act, lambda: run(py(script, proj), proj))
    if act == "datasheets":
        pages = str(a["pages"]).replace(" ", "") if a.get("pages") is not None else None
        if pages is not None and not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", pages):
            return "pages must look like 3-5 or 2,7 (1-based PDF page numbers)", 2, True
        names = a.get("names") or []
        if any(str(n).startswith("-") for n in names):
            return "names are PDF name or part number fragments", 2, True
        if not names and not a.get("all"):
            return "datasheets needs names (PDF name or part number fragments) or all=true", 2, True
        if pages:    # follow-up read: prints pages, writes nothing
            out, rc = run(_datasheet_cmd(proj, a, pages), proj)
            return out, rc, rc not in (0, 1)
        return write_call(proj, "export datasheets", lambda: run(_datasheet_cmd(proj, a, None), proj))
    return "action must be release, sim, precompliance, parts or datasheets", 2, True


HANDLERS = {"status": t_status, "check": t_check, "find": t_find, "edit": t_edit, "place": t_place,
            "route": t_route, "history": t_history, "plan": t_plan, "fab": t_fab, "lifecycle": t_lifecycle,
            "diagnostics": t_diagnostics, "engine": t_engine, "setup": t_setup, "digest": t_digest,
            "export": t_export}


def call_tool(name, args):
    """-> (text, is_error, exit_code)."""
    if name not in NAMES:
        return f"unknown tool: {name}", True, 2
    args = args if isinstance(args, dict) else {}
    if name == "setup" and args.get("action") == "new":      # the folder is not a project yet
        text, rc, is_err = setup_new(args)
        text = cap(text.strip() or "(no output)")
        return text + (f"\n[exit {rc}]" if rc else ""), is_err, rc
    proj, err = resolve_project(args)
    if err:
        return err, True, 2
    try:
        text, rc, is_err = HANDLERS[name](proj, args)
    except Exception as e:  # keep the server alive
        return f"{name} failed: {e}", True, 2
    text = cap((text or "").strip() or "(no output)")
    if rc not in (0,) and not text.endswith(f"[exit {rc}]"):
        text += f"\n[exit {rc}]"
    return text, is_err, rc


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        want = (msg.get("params") or {}).get("protocolVersion")
        return {"protocolVersion": want if want in ("2024-11-05", "2025-03-26", PROTOCOL) else PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "boardwright", "version": "0.7.0"},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        tools = []
        for n, d, sc, ro in TOOLS:
            t = {"name": n, "description": d, "inputSchema": sc}
            if ro:
                t["annotations"] = {"readOnlyHint": True}
            tools.append(t)
        return {"tools": tools}
    if method == "tools/call":
        p = msg.get("params") or {}
        text, err, rc = call_tool(p.get("name"), p.get("arguments"))
        return {"content": [{"type": "text", "text": text}], "isError": err,
                "structuredContent": {"ok": rc == 0 and not err, "exit_code": rc}}
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
