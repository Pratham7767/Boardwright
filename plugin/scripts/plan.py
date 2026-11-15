#!/usr/bin/env python3
"""Deterministic "what do I do next" planner for the boardwright pipeline.

Usage:  python plan.py [project_dir] [--all] [--json] [--mermaid]
                       [--done NODE [--note TEXT]] [--undone NODE]

Reads pipeline.json (next to this script) and the project folder, and prints which steps are ready
(and which can run together), which wait on the user, which were reopened because a design file
changed, and which gates failed. It never edits design files. The only file it writes is
<project>/reports/plan-state.json, and only for --done / --undone.

A node is DONE when its evidence holds (a report, a gates.json row, a json file ...), or when it has
no evidence and was marked with --done, or when it has no evidence and a later node that needs it
(transitively) is done by evidence. A GATE node is done only by evidence; --done refuses it.
Staleness is computed strictly from file modified times.

Exit 0 normally, 2 on setup problems or a refused --done / --undone.
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent
PIPELINE = HERE / "pipeline.json"
MAX_LINES = 30
KINDS = ("model", "script", "helper", "user", "gate")
WHENS = ("hazardous", "fast", "machine_assembly", "review")
DESIGN_KINDS = {"sch": "*.kicad_sch", "pcb": "*.kicad_pcb", "dru": "*.kicad_dru", "pro": "*.kicad_pro"}
EVIDENCE_KEYS = ("file", "file_contains", "gate", "json_ok", "glob_min", "config_key")
STAGE_NAMES = {1: "spec", 2: "parts", 3: "power budget", 4: "schematic", 5: "layout", 6: "EMC / SI",
               7: "BOM", 8: "release"}


class SetupError(Exception):
    pass


# ---------------------------------------------------------------- graph loading and validation

def load_graph(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise SetupError(f"cannot read {path}: {e}")
    except ValueError as e:
        raise SetupError(f"{path.name} is not valid JSON: {e}")
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("nodes"), list):
        raise SetupError(f'{path.name}: expected {{"version": 1, "nodes": [...]}}')
    nodes = {}
    for i, n in enumerate(data["nodes"]):
        if not isinstance(n, dict) or not isinstance(n.get("id"), str) or not n["id"]:
            raise SetupError(f"{path.name}: node #{i} has no string id")
        nid = n["id"]
        if nid in nodes:
            raise SetupError(f"{path.name}: duplicate node id {nid}")
        for key in ("stage", "title", "kind"):
            if key not in n:
                raise SetupError(f"{path.name}: node {nid} has no '{key}'")
        if not isinstance(n["stage"], int):
            raise SetupError(f"{path.name}: node {nid}: stage must be an integer")
        if n["kind"] not in KINDS:
            raise SetupError(f"{path.name}: node {nid}: kind '{n['kind']}' not in {KINDS}")
        if n.get("when") is not None and n["when"] not in WHENS:
            raise SetupError(f"{path.name}: node {nid}: when '{n['when']}' not in {WHENS}")
        n.setdefault("needs", [])
        if not isinstance(n["needs"], list):
            raise SetupError(f"{path.name}: node {nid}: needs must be a list")
        for k in n.get("invalidated_by", []):
            if k not in DESIGN_KINDS:
                raise SetupError(f"{path.name}: node {nid}: invalidated_by '{k}' not in {tuple(DESIGN_KINDS)}")
        ev = n.get("evidence")
        if ev is not None:
            known = [k for k in ev if k in EVIDENCE_KEYS]
            if len(known) != 1:
                raise SetupError(f"{path.name}: node {nid}: evidence needs exactly one of {EVIDENCE_KEYS}")
            if known[0] == "json_ok" and not ("true_key" in ev or "zero_key" in ev):
                raise SetupError(f"{path.name}: node {nid}: json_ok needs true_key or zero_key")
            for p in _evidence_paths(ev):
                if os.path.isabs(p) or ".." in Path(p).parts:
                    raise SetupError(f"{path.name}: node {nid}: evidence path '{p}' must be relative, inside the project")
        elif n["kind"] == "gate":
            raise SetupError(f"{path.name}: gate node {nid} has no evidence (a gate can only pass by evidence)")
        nodes[nid] = n
    for nid, n in nodes.items():
        for d in n["needs"]:
            if d not in nodes:
                raise SetupError(f"{path.name}: node {nid} needs unknown node '{d}'")
            if d == nid:
                raise SetupError(f"{path.name}: node {nid} needs itself")
        lt = n.get("loop_to")
        if lt is not None and lt not in nodes:
            raise SetupError(f"{path.name}: node {nid}: loop_to refers to unknown node '{lt}'")
    cyc = find_cycle(nodes)
    if cyc:
        raise SetupError(f"{path.name}: needs cycle: " + " -> ".join(cyc))
    order = topo_order(nodes)
    anc = ancestors(nodes, order)
    for nid, n in nodes.items():
        lt = n.get("loop_to")
        if lt is not None and lt not in anc[nid]:
            raise SetupError(f"{path.name}: node {nid}: loop_to '{lt}' is not an earlier step of {nid}")
    groups = {}
    for nid, n in nodes.items():
        if n.get("parallel"):
            groups.setdefault(n["parallel"], []).append(nid)
    for g, members in groups.items():
        for a in members:
            for b in members:
                if a != b and b in anc[a]:
                    raise SetupError(f"{path.name}: parallel group '{g}': {a} depends on {b}, they cannot run together")
    return nodes, order, anc


def _evidence_paths(ev):
    if "file" in ev:
        return [ev["file"]]
    if "file_contains" in ev:
        return [ev["file_contains"][0]]
    if "json_ok" in ev:
        return [ev["json_ok"]]
    if "glob_min" in ev:
        return [ev["glob_min"][0]]
    return []


def find_cycle(nodes):
    color = {}
    stack = []

    def visit(u):
        color[u] = 1
        stack.append(u)
        for v in nodes[u]["needs"]:
            if color.get(v) == 1:
                return stack[stack.index(v):] + [v]
            if color.get(v) is None:
                found = visit(v)
                if found:
                    return found
        stack.pop()
        color[u] = 2
        return None

    for u in nodes:
        if color.get(u) is None:
            found = visit(u)
            if found:
                return found
    return None


def topo_order(nodes):
    done, order = set(), []
    pending = list(nodes)
    while pending:
        rest = []
        for n in pending:
            if all(d in done for d in nodes[n]["needs"]):
                done.add(n)
                order.append(n)
            else:
                rest.append(n)
        pending = rest
    return order


def ancestors(nodes, order):
    anc = {}
    for n in order:
        s = set()
        for d in nodes[n]["needs"]:
            s.add(d)
            s |= anc[d]
        anc[n] = s
    return anc


# ---------------------------------------------------------------- project facts

def read_text(p):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def design_files(project):
    """kind -> (newest mtime, file name) for the design files in the project root."""
    out = {}
    for kind, pat in DESIGN_KINDS.items():
        best = None
        for f in project.glob(pat):
            if f.name.startswith("_autosave") or not f.is_file():
                continue
            m = f.stat().st_mtime
            if best is None or m > best[0]:
                best = (m, f.name)
        if best:
            out[kind] = best
    return out


def project_properties(project, cfg):
    """hazardous / fast / machine_assembly from the project files; "review" (an independent
    reviewer at stages 2, 5 and 6) when the board is hazardous or fast, or when boardwright.json
    has "reviewer": true (set it when the main session does not run on the strongest model)."""
    props = _base_properties(project, cfg)
    if props & {"hazardous", "fast"} or (isinstance(cfg, dict) and cfg.get("reviewer") is True):
        props.add("review")
    return props


def _base_properties(project, cfg):
    props = set()
    if isinstance(cfg, dict) and "barrier" in cfg:
        props.add("hazardous")
    pm = project / "PROJECT.md"
    if not pm.is_file():
        return props
    text = read_text(pm)
    # "yes / no" is the template's unanswered placeholder, not an answer
    if re.search(r"(?i)(mains-connected|hazardous voltage|isolation barrier)[\s*:|`]*yes\b(?!\s*/)", text):
        props.add("hazardous")
    for line in text.splitlines():
        key = val = None
        if "|" in line:
            cells = [c.strip().strip("*` ") for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2:
                key, val = cells[0].lower(), cells[1].lower()
        else:
            m = re.match(r"\s*[-*]?\s*\**([A-Za-z][^:*]{0,60})\**\s*:\**\s*(.*)$", line)
            if m:
                key, val = m.group(1).strip().lower(), m.group(2).strip("*` ").lower()
        if not key:
            continue
        if " / " in val or val.startswith("/"):      # an unanswered template choice such as "hand / machine"
            continue
        if key.startswith("assembly") and "machine" in val:
            props.add("machine_assembly")
        if key.startswith("fast interfaces") and val and not val.startswith("none") and not val.startswith("-"):
            props.add("fast")
    return props


# ---------------------------------------------------------------- evidence

def eval_evidence(node, project, cfg):
    """-> (state, detail, evidence_mtime). state: ok | fail | none."""
    ev = node.get("evidence")
    if not ev:
        return "none", "", None
    if "file" in ev:
        p = project / ev["file"]
        if p.is_file():
            return "ok", ev["file"], p.stat().st_mtime
        return "none", f"missing {ev['file']}", None
    if "file_contains" in ev:
        rel, needle = ev["file_contains"]
        p = project / rel
        if not p.is_file():
            return "none", f"missing {rel}", None
        pat = re.compile(r"\b" + re.escape(needle) + r"(ED)?\b", re.I)
        bad = re.compile(r"NOT\s+PASS|\bFAIL", re.I)
        failed = None
        for ln in read_text(p).splitlines():
            if bad.search(ln):
                failed = failed or ln.strip()
                continue
            if pat.search(ln):
                return "ok", f"{rel} has a {needle} line", p.stat().st_mtime
        if failed:
            return "fail", f"{rel}: " + clip(failed, 70), p.stat().st_mtime
        return "none", f"{rel} has no {needle} line yet", p.stat().st_mtime
    if "gate" in ev:
        gp = project / "reports" / "gates.json"
        g = read_json(gp) if gp.is_file() else None
        if not isinstance(g, dict):
            return "none", "no reports/gates.json", None
        for r in g.get("results", []):
            if str(r.get("name", "")).lower() == ev["gate"].lower():
                st = str(r.get("status", "")).lower()
                detail = f"{ev['gate']}={r.get('status')}"
                if r.get("detail"):
                    detail += f" ({clip(str(r['detail']), 60)})"
                return ("ok" if st == "pass" else "fail"), detail, gp.stat().st_mtime
        return "none", f"gates.json has no '{ev['gate']}' row", gp.stat().st_mtime
    if "json_ok" in ev:
        p = project / ev["json_ok"]
        if not p.is_file():
            return "none", f"missing {ev['json_ok']}", None
        d = read_json(p)
        if not isinstance(d, dict):
            return "none", f"{ev['json_ok']} unreadable", p.stat().st_mtime
        if "zero_key" in ev:
            k = ev["zero_key"]
            good = d.get(k) == 0
            return ("ok" if good else "fail"), f"{ev['json_ok']}: {k}={d.get(k)}", p.stat().st_mtime
        k = ev["true_key"]
        good = d.get(k) is True
        return ("ok" if good else "fail"), f"{ev['json_ok']}: {k}={d.get(k)}", p.stat().st_mtime
    if "glob_min" in ev:
        pat, n = ev["glob_min"]
        files = [f for f in project.glob(pat) if f.is_file()]
        if len(files) >= n:
            return "ok", f"{len(files)} x {pat}", max(f.stat().st_mtime for f in files)
        return "none", f"{len(files)} of {n} x {pat}", None
    if "config_key" in ev:
        cp = project / "boardwright.json"
        if isinstance(cfg, dict) and ev["config_key"] in cfg:
            return "ok", f"boardwright.json has '{ev['config_key']}'", cp.stat().st_mtime
        return "none", f"boardwright.json has no '{ev['config_key']}'", None
    return "none", "", None


def describe_evidence(ev):
    if "file" in ev:
        return f"file {ev['file']}"
    if "file_contains" in ev:
        return f"{ev['file_contains'][0]} with a {ev['file_contains'][1]} line"
    if "gate" in ev:
        return f"reports/gates.json row '{ev['gate']}' = pass"
    if "json_ok" in ev:
        return f"{ev['json_ok']} ({ev.get('zero_key') or ev.get('true_key')} ok)"
    if "glob_min" in ev:
        return f"{ev['glob_min'][1]}+ files {ev['glob_min'][0]}"
    return f"boardwright.json key '{ev.get('config_key')}'"


def clip(s, n):
    s = " ".join(str(s).replace("**", "").replace("`", "").split())
    return s if len(s) <= n else s[:n - 3] + "..."


# ---------------------------------------------------------------- state file

def state_path(project):
    return project / "reports" / "plan-state.json"


def load_state(project):
    p = state_path(project)
    if not p.is_file():
        return {"done": {}}
    d = read_json(p)
    if not isinstance(d, dict) or not isinstance(d.get("done", {}), dict):
        raise SetupError(f"{p} is not a valid plan state file; fix or delete it")
    d.setdefault("done", {})
    return d


def save_state(project, state):
    p = state_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def parse_at(s):
    try:
        d = datetime.datetime.fromisoformat(str(s))
        return d.timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------- planning

def compute(nodes, order, anc, project):
    cfg = read_json(project / "boardwright.json") if (project / "boardwright.json").is_file() else None
    props = project_properties(project, cfg)
    design = design_files(project)
    state = load_state(project)
    mdone = state["done"]

    skip_override, override_notes = set(), []
    ov = cfg.get("pipeline_overrides") if isinstance(cfg, dict) else None
    if isinstance(ov, dict):
        for nid in ov.get("skip", []) or []:
            if nid not in nodes:
                override_notes.append(f"override ignored, unknown node {nid}")
            elif nodes[nid]["kind"] == "gate":
                override_notes.append(f"override ignored, {nid} is a gate")
            else:
                skip_override.add(nid)

    info = {}
    for nid in order:
        n = nodes[nid]
        i = {"skipped": None, "state": "todo", "how": None, "detail": "", "reason": None, "ev_state": "none",
             "ev_time": None}
        if n.get("when") and n["when"] not in props:
            i["skipped"] = f"when {n['when']} is false"
        elif nid in skip_override:
            i["skipped"] = "skipped by pipeline_overrides"
        info[nid] = i

    # evidence
    for nid in order:
        n, i = nodes[nid], info[nid]
        if i["skipped"] or not n.get("evidence"):
            continue
        st, detail, t = eval_evidence(n, project, cfg)
        i["ev_state"], i["detail"], i["ev_time"] = st, detail, t
        stale = None
        if t is not None:
            for k in n.get("invalidated_by", []):
                if k in design and design[k][0] > t:
                    stale = design[k][1]
                    break
        if st == "ok" and stale:
            i["state"], i["reason"] = "reopened", f"{stale} changed after the evidence"
        elif st == "ok":
            i["state"], i["how"] = "done", "evidence"
        elif st == "fail" and stale:
            i["state"], i["detail"] = "todo", i["detail"] + f" (old, {stale} changed since)"
        elif st == "fail":
            i["state"] = "failed"
    # proof that a step happened at some time: evidence holds (even if a design change made it stale)
    ev_done = {nid for nid in order if info[nid]["ev_state"] == "ok" and not info[nid]["skipped"]}

    # children, descendants done by evidence
    children = {nid: [] for nid in nodes}
    for nid in nodes:
        for d in nodes[nid]["needs"]:
            children[d].append(nid)
    desc_ev = {}
    for nid in reversed(order):
        desc_ev[nid] = any(c in ev_done or desc_ev[c] for c in children[nid])

    # nodes without evidence: manual mark, inferred, staleness
    for nid in order:
        n, i = nodes[nid], info[nid]
        if i["skipped"] or n["kind"] == "gate":
            continue
        if n.get("evidence") and i["ev_state"] != "none":
            continue
        # no evidence rule (or evidence not found): hand mark, then inference for old projects
        mark = None if n.get("evidence") else mdone.get(nid)
        at = parse_at(mark.get("at")) if isinstance(mark, dict) else None
        if at is not None:
            stale = None
            for k in n.get("invalidated_by", []):
                if k in design and design[k][0] > at:
                    stale = design[k][1]
                    break
            if stale:
                i["state"], i["reason"] = "reopened", f"{stale} changed after it was marked done"
            else:
                i["state"], i["how"] = "done", "manual"
                i["detail"] = str(mark.get("note") or "")
            i["at"] = at
        elif desc_ev[nid]:
            i["state"], i["how"] = "done", "inferred"

    # failed gates send work back to loop_to (only to nodes that have no evidence)
    for nid in order:
        i = info[nid]
        if i["state"] != "failed":
            continue
        lt = nodes[nid].get("loop_to")
        if not lt:
            continue
        tgt, ti = nodes[lt], info[lt]
        if ti["skipped"] or tgt.get("evidence") or tgt["kind"] == "gate":
            continue
        redone_at = ti.get("at")
        if ti["state"] == "done" and (redone_at is None or i["ev_time"] > redone_at):
            ti["state"], ti["how"] = "reopened", None
            ti["reason"] = f"gate {nid} failed"
        elif ti["state"] == "done":
            i["loop_redone"] = True

    done_set = {nid for nid in order if info[nid]["skipped"] or info[nid]["state"] == "done"}
    for nid in order:
        i = info[nid]
        if nid in done_set:
            i["status"] = "skipped" if i["skipped"] else "done"
            continue
        blockers = [d for d in nodes[nid]["needs"] if d not in done_set]
        i["blockers"] = blockers
        i["status"] = "blocked" if blockers else "ready"

    active = [nid for nid in order if not info[nid]["skipped"]]
    ndone = [nid for nid in active if info[nid]["state"] == "done"]
    open_stage = min((nodes[nid]["stage"] for nid in active if info[nid]["state"] != "done"), default=None)

    ready = [nid for nid in order if info[nid]["status"] == "ready"]
    ready_set = set(ready)
    nxt = [nid for nid in order
           if info[nid]["status"] == "blocked" and all(d in done_set or d in ready_set for d in nodes[nid]["needs"])]
    return {"info": info, "props": props, "design": design, "done_set": done_set, "active": active,
            "ndone": ndone, "stage": open_stage, "ready": ready, "next": nxt, "notes": override_notes,
            "skipped_override": sorted(skip_override), "state": state}


def run_text(n):
    r = n.get("run", "")
    if n.get("fanout"):
        r = (r + " " if r else "") + f"[fanout: {n['fanout']}]"
    return r


def node_line(n, extra=""):
    parts = [n["id"], n["kind"], clip(n["title"], 78)]
    r = run_text(n)
    if r:
        parts.append(r)
    s = " | ".join(parts)
    return s + extra


def render_default(project, nodes, plan):
    info = plan["info"]
    ready = plan["ready"]
    failed = [nid for nid in plan["info"] if info[nid]["state"] == "failed"]
    reopened = [nid for nid in plan["info"] if info[nid]["state"] == "reopened"]
    how = {"evidence": 0, "manual": 0, "inferred": 0}
    for nid in plan["ndone"]:
        how[info[nid]["how"]] += 1
    stage = plan["stage"]
    head = (f"{project.name} | done {len(plan['ndone'])} / {len(plan['active'])} "
            f"(evidence {how['evidence']}, marked {how['manual']}, inferred {how['inferred']}) | "
            + (f"stage {stage} {STAGE_NAMES.get(stage, '')}".strip() if stage else "all nodes done"))
    if plan["props"]:
        head += " | " + ",".join(sorted(plan["props"]))
    out = [head]

    tag = lambda m: " [reopened]" if info[m]["state"] == "reopened" else ""
    show_ready = [nid for nid in ready if nodes[nid]["kind"] != "user" and info[nid]["state"] != "failed"]
    out.append("READY NOW:" + ("" if show_ready else " none"))
    groups = {}
    for nid in show_ready:
        g = nodes[nid].get("parallel")
        if g:
            groups.setdefault(g, []).append(nid)
    printed = set()
    for nid in show_ready:
        g = nodes[nid].get("parallel")
        if g and len(groups[g]) > 1:
            if g in printed:
                continue
            printed.add(g)
            out.append("  can run together:")
            for m in groups[g]:
                out.append("    " + node_line(nodes[m], tag(m)))
        else:
            out.append("  " + node_line(nodes[nid], tag(nid)))

    users = [nid for nid in ready if nodes[nid]["kind"] == "user"]
    out.append("WAITING ON USER:" + ("" if users else " none"))
    for nid in users:
        out.append("  " + f"{nid} | {clip(nodes[nid]['title'], 100)}")

    if reopened:
        out.append("REOPENED (design changed since):")
        by_reason = {}
        for nid in reopened:
            by_reason.setdefault(info[nid]["reason"], []).append(nid)
        for reason, ids in by_reason.items():
            out.append(f"  {', '.join(ids)}  <- {reason}")
    if failed:
        out.append("FAILED GATES:")
        for nid in failed:
            lt = nodes[nid].get("loop_to")
            if lt and info[nid].get("loop_redone"):
                go = f"{lt} was redone, rerun this gate"
            elif lt:
                go = f"go back to {lt}"
            else:
                go = "fix the cause and rerun"
            out.append(f"  {nid}: {clip(info[nid]['detail'], 70)} -> {go}")
    for note in plan["notes"]:
        out.append("  note: " + note)
    if plan["skipped_override"]:
        out.append("skipped by override: " + ", ".join(plan["skipped_override"]))

    nxt = plan["next"][:5]
    tail = []
    if nxt:
        tail.append("NEXT AFTER THAT:")
        for nid in nxt:
            tail.append(f"  {nid} | {nodes[nid]['kind']} | {clip(nodes[nid]['title'], 80)}")
    if len(out) + len(tail) > MAX_LINES:
        keep = max(0, MAX_LINES - len(out))
        tail = tail[:keep]
    out += tail
    if len(out) > MAX_LINES:
        extra = len(out) - (MAX_LINES - 1)
        out = out[:MAX_LINES - 1] + [f"... {extra} more lines, use --all or --json"]
    return "\n".join(out)


def status_text(nid, nodes, plan):
    i = plan["info"][nid]
    if i["skipped"]:
        return f"skipped ({i['skipped']})"
    st = i["status"]
    if st == "done":
        return "done (" + i["how"] + (f", {i['detail']}" if i["how"] == "manual" and i["detail"] else "") + ")"
    base = {"reopened": "REOPENED", "failed": "FAILED", "todo": ""}[i["state"]]
    if i["state"] == "reopened":
        base += f" ({i['reason']})"
    elif i["state"] == "failed":
        base += f" ({i['detail']})"
    if st == "ready":
        return ("ready; " + base) if base else "ready"
    blk = "blocked by " + ", ".join(i["blockers"])
    return (base + "; " + blk) if base else blk


def render_all(project, nodes, order, plan):
    rows = [f"{project.name}: {len(plan['ndone'])} / {len(plan['active'])} done"]
    for nid in order:
        n = nodes[nid]
        rows.append(f"{n['stage']} {nid:<24} {n['kind']:<6} {status_text(nid, nodes, plan)}")
    return "\n".join(rows)


def render_json(project, nodes, order, plan):
    info = plan["info"]

    def item(nid):
        n = nodes[nid]
        return {"id": nid, "kind": n["kind"], "title": n["title"], "run": run_text(n) or None,
                "parallel": n.get("parallel"), "stage": n["stage"]}

    ready = plan["ready"]
    groups = {}
    for nid in ready:
        g = nodes[nid].get("parallel")
        if g and nodes[nid]["kind"] != "user" and info[nid]["state"] != "failed":
            groups.setdefault(g, []).append(nid)
    data = {
        "project": project.name,
        "done": len(plan["ndone"]), "total": len(plan["active"]),
        "stage": plan["stage"], "properties": sorted(plan["props"]),
        "ready": [item(n) for n in ready if nodes[n]["kind"] != "user" and info[n]["state"] != "failed"],
        "can_run_together": [v for v in groups.values() if len(v) > 1],
        "waiting_on_user": [item(n) for n in ready if nodes[n]["kind"] == "user"],
        "reopened": [{"id": n, "reason": info[n]["reason"]} for n in info if info[n]["state"] == "reopened"],
        "failed_gates": [{"id": n, "detail": info[n]["detail"], "loop_to": nodes[n].get("loop_to")}
                         for n in info if info[n]["state"] == "failed"],
        "next_after_that": [item(n) for n in plan["next"][:5]],
        "notes": plan["notes"],
        "nodes": {n: status_text(n, nodes, plan) for n in order},
    }
    return json.dumps(data, indent=1)


def mermaid(nodes, order, plan):
    info = plan["info"]
    sid = lambda n: n.replace(".", "_")
    lines = ["flowchart LR"]
    stages = sorted({nodes[n]["stage"] for n in order})
    for s in stages:
        lines.append(f'  subgraph S{s}["{s} {STAGE_NAMES.get(s, "")}"]')
        for nid in order:
            if nodes[nid]["stage"] == s:
                lines.append(f'    {sid(nid)}["{nid}<br/>{nodes[nid]["kind"]}"]')
        lines.append("  end")
    nedges = 0
    for nid in order:
        for d in nodes[nid]["needs"]:
            lines.append(f"  {sid(d)} --> {sid(nid)}")
            nedges += 1
    for nid in order:
        if nodes[nid].get("loop_to"):
            lines.append(f"  {sid(nid)} -.->|fail| {sid(nodes[nid]['loop_to'])}")
            nedges += 1
    lines += ["  classDef done fill:#cfe8cf,stroke:#3a7d3a",
              "  classDef ready fill:#fff3b0,stroke:#a08000",
              "  classDef failed fill:#f4b6b6,stroke:#a02020",
              "  classDef skipped fill:#eeeeee,stroke:#999999,stroke-dasharray: 3 3"]
    buckets = {"done": [], "ready": [], "failed": [], "skipped": []}
    for nid in order:
        i = info[nid]
        if i["skipped"]:
            buckets["skipped"].append(sid(nid))
        elif i["state"] in ("failed", "reopened"):
            buckets["failed"].append(sid(nid))
        elif i["status"] == "done":
            buckets["done"].append(sid(nid))
        elif i["status"] == "ready":
            buckets["ready"].append(sid(nid))
    for cls, ids in buckets.items():
        if ids:
            lines.append(f"  class {','.join(ids)} {cls}")
    return "\n".join(lines), len(order), nedges


# ---------------------------------------------------------------- commands

def cmd_done(project, nodes, plan, nid, note):
    if nid not in nodes:
        print(f"unknown node: {nid}")
        return 2
    n, i = nodes[nid], plan["info"][nid]
    if n["kind"] == "gate":
        print(f"refused: {nid} is a gate. It is done only when its evidence holds: "
              f"{describe_evidence(n['evidence'])}.")
        return 2
    if n.get("evidence"):
        print(f"refused: {nid} completes by evidence, not by hand: {describe_evidence(n['evidence'])}. "
              f"Now: {i['detail'] or i['ev_state']}.")
        return 2
    if i["skipped"]:
        print(f"refused: {nid} is skipped ({i['skipped']}).")
        return 2
    missing = [d for d in n["needs"] if d not in plan["done_set"]]
    if missing:
        print(f"refused: {nid} needs these first: {', '.join(missing)}")
        return 2
    if i["state"] == "done" and i["how"] == "inferred":
        print(f"{nid} is already done (inferred from a later step done by evidence); nothing recorded.")
        return 0
    state = plan["state"]
    state["done"][nid] = {"at": datetime.datetime.now().astimezone().isoformat(timespec="microseconds"),
                          "note": note or ""}
    save_state(project, state)
    print(f"marked done: {nid}")
    return 0


def cmd_undone(project, nodes, plan, nid):
    if nid not in nodes:
        print(f"unknown node: {nid}")
        return 2
    state = plan["state"]
    if nid not in state["done"]:
        why = " (gates and evidence nodes are never marked by hand)" if nodes[nid].get("evidence") or nodes[nid]["kind"] == "gate" else ""
        print(f"{nid} has no manual mark; nothing to undo{why}.")
        return 2
    del state["done"][nid]
    save_state(project, state)
    print(f"mark removed: {nid}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="boardwright planner: what to do next")
    ap.add_argument("project_dir", nargs="?", default=".")
    ap.add_argument("--all", action="store_true", help="every node with its status")
    ap.add_argument("--json", action="store_true", help="same data as JSON")
    ap.add_argument("--mermaid", action="store_true", help="flowchart of the whole graph")
    ap.add_argument("--done", metavar="NODE", help="mark a non-gate node done by hand")
    ap.add_argument("--note", default="", help="note stored with --done")
    ap.add_argument("--undone", metavar="NODE", help="remove a manual mark")
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"not a directory: {project}")
        return 2
    try:
        nodes, order, anc = load_graph(PIPELINE)
        plan = compute(nodes, order, anc, project)
    except SetupError as e:
        print(f"setup problem: {e}")
        return 2

    if args.done:
        return cmd_done(project, nodes, plan, args.done, args.note)
    if args.undone:
        return cmd_undone(project, nodes, plan, args.undone)
    if args.mermaid:
        text, nn, ne = mermaid(nodes, order, plan)
        print(text)
        print(f"%% {nn} nodes, {ne} edges")
        return 0
    if args.json:
        print(render_json(project, nodes, order, plan))
    elif args.all:
        print(render_all(project, nodes, order, plan))
    else:
        print(render_default(project, nodes, plan))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
