#!/usr/bin/env python3
"""One short "where is this project" answer (at most 25 lines, read-only).

Usage:  python status.py [project_dir]

project_dir defaults to the current working directory. Exit 0 always, 2 if project_dir does not exist.
Quotes what the files say (gates.json, stage report headline lines, PROJECT.md); it decides nothing
and never claims a gate passed beyond that.
"""
import datetime
import json
import re
import sys
from pathlib import Path

MAX_LINES = 25
STAGES = [("01", "spec"), ("02", "parts"), ("03", "power"), ("04", "schematic"),
          ("05", "layout"), ("06", "emc"), ("07", "bom"), ("08", "release")]
NEWER_THAN = {"04": ".kicad_sch", "05": ".kicad_pcb", "06": ".kicad_pcb", "08": ".kicad_pcb"}


def read(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def day(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def clip(s, n):
    s = s.replace("**", "").replace("`", "").strip()
    return s if len(s) <= n else s[:n - 3] + "..."


def section_value(text, heading):
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lower() == heading.lower():
            for nxt in lines[i + 1:]:
                if nxt.startswith("#"):
                    return None
                if nxt.strip():
                    return clip(nxt, 80)
    return None


def newest(project, ext):
    files = list(project.glob("*" + ext))
    return max((f.stat().st_mtime for f in files), default=None)


def main():
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    if not project.is_dir():
        print(f"not a directory: {project}")
        return 2
    reports = project / "reports"
    out = [f"project: {project.name}"]

    # gates.json
    gj = reports / "gates.json"
    if gj.exists():
        try:
            g = json.loads(read(gj))
            rows = [f"{r.get('name')}={r.get('status')}" for r in g.get("results", [])]
            out.append(f"gates.json {clip(str(g.get('timestamp', '?')), 25)}: " + "; ".join(rows))
            for r in g.get("results", []):
                if r.get("detail") and r.get("name") in ("ERC", "DRC", "DRC after zone refill"):
                    out.append(f"  {r['name']}: {clip(r['detail'], 90)}")
        except ValueError:
            out.append("gates.json: unreadable")
    else:
        out.append("gates.json: none (gates not run yet)")

    # stage reports
    first_missing = None
    for num, label in STAGES:
        found = sorted(reports.glob(f"{num}-*.md")) if reports.is_dir() else []
        if not found:
            out.append(f"{num} {label}: no report")
            first_missing = first_missing or num
            continue
        p = found[0]
        text = read(p)
        head = ""
        for ln in text.splitlines():
            if re.search(r"result|status|gate", ln, re.I):
                head = clip(re.sub(r"^[#>\s*-]+", "", ln), 110)
                break
        unv = len(re.findall("unverified", text, re.I))
        asm = text.count("ASSUMPTION")
        stale = ""
        ext = NEWER_THAN.get(num)
        if ext:
            dm = newest(project, ext)
            if dm is not None and p.stat().st_mtime < dm:
                stale = " [older than design file]"
        out.append(f"{num} {label}: {day(p.stat().st_mtime)} unv={unv} asm={asm}{stale} | {head or '-'}")

    # release checklist
    rel = reports / "08-release.md"
    if rel.exists():
        t = read(rel)
        todo = len(re.findall(r"- \[ \]", t))
        done = len(re.findall(r"- \[[xX]\]", t))
        out.append(f"08 checklist: {todo} unchecked, {done} checked")

    # boardwright.json
    cfg = project / "boardwright.json"
    if cfg.exists():
        try:
            c = json.loads(read(cfg))
            names = [k for k in ("expect_netclass_patterns", "barrier", "emc") if k in c]
            out.append("boardwright.json sections: " + (", ".join(names) or "none of the known ones"))
        except ValueError:
            out.append("boardwright.json: unreadable")
    else:
        out.append("boardwright.json: missing")

    # PROJECT.md
    pm = project / "PROJECT.md"
    if pm.exists():
        t = read(pm)
        out.append(f"PROJECT.md: Mode={section_value(t, '## Mode') or '-'}; "
                   f"Entry point={section_value(t, '## Entry point') or '-'}")
    else:
        out.append("PROJECT.md: missing")

    out.append(f"next stage: {first_missing}" if first_missing else "next stage: none (all 8 reports exist)")
    print("\n".join(out[:MAX_LINES]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
