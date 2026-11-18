#!/usr/bin/env python3
"""Creepage and clearance gate, version 2: required distances per barrier, KiCad rules generated from
them, and two independent distance checks that must agree.

Usage:
    python scripts/creepage_rules.py <project_dir>            check (read-only)
    python scripts/creepage_rules.py <project_dir> --write    (re)write the generated rule block in the
                                                              .kicad_dru (a .bak copy is kept first)

Inputs: boardwright.json "safety" (mains, pollution_degree, altitude_m, laminate_cti, domains, barriers;
see references/high-voltage.md), spacing_tables.json, the .kicad_pro net classes, and after DRC:
reports/drc.json (run_gates.py) and reports/barrier.json (barrier_check.py).

For every barrier it computes the required clearance and creepage (spacing.py, IEC 60664-1 method),
takes the larger of that and the barrier's "use_mm" (a stricter value the designer chose), and writes
two KiCad rules (clearance + creepage) at the END of the .kicad_dru, between marker lines, so they win
over earlier rules for the same items (in KiCad the last matching rule wins).

The check fails when:
  - a barrier has no generated rules, or a rule is below the required distance (rerun with --write);
  - KiCad is older than 10.0.6 (earlier creepage DRC had geometry bugs: false and missing violations);
  - reports/drc.json is missing or older than the board or rules (rerun run_gates.py first);
  - KiCad's DRC reports a violation of a generated rule;
  - the two checks disagree: barrier_check.py measured copper closer than the rule, but KiCad's DRC
    reported nothing for that rule (a rule that silently matches nothing looks exactly like this).
Exit 0 pass, 1 fail, 2 setup problem.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, load_config, md_table, project_files, write_report  # noqa: E402
from spacing import material_group, required  # noqa: E402

BEGIN = "# >>> boardwright generated spacing rules (creepage_rules.py --write; do not edit by hand) >>>"
END = "# <<< boardwright generated spacing rules <<<"
MIN_KICAD = (10, 0, 6)


def kicad_version() -> tuple | None:
    try:
        from run_gates import find_kicad_cli
        cli = find_kicad_cli()
        if not cli:
            return None
        out = subprocess.run([cli, "version"], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=60).stdout
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
        return tuple(int(x) for x in m.groups()) if m else None
    except Exception:
        return None


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower() or "barrier"


def classes_of(domains: list, names: list) -> list:
    out = []
    for d in domains:
        if d.get("name") in names:
            out += [c for c in d.get("netclasses") or [] if c not in out]
    return out


def side_expr(item: str, classes: list) -> str:
    return "(" + " || ".join(f"{item}.hasNetclass('{c}')" for c in classes) + ")"


def plan_barriers(s: dict) -> list:
    mains = s.get("mains") or {}
    mvrms = mains.get("max_vrms") or mains.get("vrms")
    if not mvrms:
        raise SetupError("safety.mains.vrms (or max_vrms) is needed to compute spacing")
    pd = int(s.get("pollution_degree", 2))
    mg = s.get("material_group") or material_group(s.get("laminate_cti"))
    domains = s.get("domains") or []
    rest_names = [d["name"] for d in domains if d.get("rest")]
    plans = []
    for b in s.get("barriers") or []:
        name = b.get("name") or "barrier"
        hot = classes_of(domains, b.get("between") or [])
        if not hot:
            raise SetupError(f"barrier '{name}': its 'between' domains have no net classes")
        other_names = b.get("and") or []
        other = classes_of(domains, [n for n in other_names if n not in rest_names])
        to_rest = any(n in rest_names for n in other_names) or not other_names
        req = required(mvrms, mains.get("ovc", "II"), pd, mg, b.get("insulation", "basic"),
                       b.get("working_vrms"), b.get("peak_v"), float(s.get("altitude_m", 2000)))
        use = b.get("use_mm")
        val = max(req["creepage_mm"], req["clearance_mm"], float(use) if use else 0.0)
        a = side_expr("A", hot)
        if to_rest:
            cond = f"{a} && !{side_expr('B', hot)}"
        else:
            cond = f"{a} && {side_expr('B', other)}"
        plans.append({"name": name, "slug": slug(name), "insulation": b.get("insulation", "basic"),
                      "required": req, "use_mm": use, "rule_mm": round(val, 2),
                      "clearance_rule_mm": round(max(req["clearance_mm"], float(use) if use else 0.0), 2),
                      "condition": cond, "hot_classes": hot})
    return plans


def rule_block(plans: list) -> str:
    lines = [BEGIN]
    for p in plans:
        r = p["required"]
        lines += [f"# barrier '{p['name']}' ({p['insulation']}): required clearance {r['clearance_mm']} mm, creepage "
                  f"{r['creepage_mm']} mm ({r['status']})" + (f"; designer's value {p['use_mm']} mm" if p["use_mm"] else ""),
                  f"(rule \"bw_{p['slug']}_clearance\"",
                  f"\t(constraint clearance (min {p['clearance_rule_mm']}mm))",
                  f"\t(condition \"{p['condition']}\"))",
                  f"(rule \"bw_{p['slug']}_creepage\"",
                  f"\t(constraint creepage (min {p['rule_mm']}mm))",
                  f"\t(condition \"{p['condition']}\"))"]
    lines.append(END)
    return "\n".join(lines) + "\n"


def write_rules(dru: Path, plans: list) -> None:
    text = dru.read_text("utf-8") if dru.is_file() else "(version 1)\n"
    if dru.is_file():
        shutil.copy2(dru, dru.with_suffix(".kicad_dru.bak"))
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S).rstrip() + "\n\n"
    dru.write_text(text + rule_block(plans), "utf-8")


def existing_rules(dru: Path) -> dict:
    """{rule name: (constraint, min_mm)} from the generated block."""
    if not dru.is_file():
        return {}
    text = dru.read_text("utf-8", errors="replace")
    m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), text, flags=re.S)
    if not m:
        return {}
    return {name: (con, float(v)) for name, con, v in
            re.findall(r'\(rule\s+"([^"]+)"\s*\(constraint\s+(\w+)\s+\(min\s+([\d.]+)mm\)\)', m.group(1))}


def drc_hits(drc: dict) -> dict:
    """{rule name: count} for violations whose description names a rule."""
    hits: dict = {}
    for v in drc.get("violations") or []:
        m = re.search(r"rule '([^']+)'", v.get("description", ""))
        if m:
            hits[m.group(1)] = hits.get(m.group(1), 0) + 1
    return hits


def check(project: Path, f: dict, plans: list) -> tuple:
    problems, notes, rows = [], [], []
    have = existing_rules(f["dru"])
    for p in plans:
        for kind, need in (("clearance", p["clearance_rule_mm"]), ("creepage", p["rule_mm"])):
            rn = f"bw_{p['slug']}_{kind}"
            got = have.get(rn)
            if not got:
                problems.append(f"rule {rn} is missing from {f['dru'].name}: run creepage_rules.py --write")
            elif got[1] + 1e-6 < need:
                problems.append(f"rule {rn} is {got[1]} mm, below the required {need} mm: run --write")
        rows.append([p["name"], p["insulation"], p["required"]["clearance_mm"], p["required"]["creepage_mm"],
                     p["use_mm"] or "", p["rule_mm"], p["required"]["groove_min_mm"]])

    ver = kicad_version()
    if ver is None:
        notes.append("KiCad version unknown (kicad-cli not found); creepage DRC results cannot be trusted yet")
        problems.append("kicad-cli not found: the creepage DRC cannot run")
    elif ver < MIN_KICAD:
        problems.append(f"KiCad {'.'.join(map(str, ver))} is older than 10.0.6; its creepage DRC had geometry bugs "
                        "(missing and false violations). Update KiCad.")

    drc_path = project / "reports" / "drc.json"
    newest = max((x.stat().st_mtime for x in (f["pcb"], f["dru"], f["pro"]) if x.is_file()), default=0)
    if not drc_path.is_file():
        problems.append("reports/drc.json is missing: run python scripts/run_gates.py . --no-export first")
        return rows, problems, notes
    if drc_path.stat().st_mtime < newest:
        problems.append("reports/drc.json is older than the board or rules: rerun run_gates.py")
    drc = json.loads(drc_path.read_text("utf-8", errors="replace"))
    hits = drc_hits(drc)
    for p in plans:
        for kind in ("clearance", "creepage"):
            rn = f"bw_{p['slug']}_{kind}"
            if hits.get(rn):
                problems.append(f"KiCad DRC: {hits[rn]} violation(s) of {rn}")

    bpath = project / "reports" / "barrier.json"
    if bpath.is_file():
        b = json.loads(bpath.read_text("utf-8"))
        if bpath.stat().st_mtime < f["pcb"].stat().st_mtime:
            problems.append("reports/barrier.json is older than the board: rerun barrier_check.py")
        bmin = b.get("minimum_all_mm")
        bclasses = set(b.get("hazard_netclasses") or [])
        for p in plans:
            if not (bclasses & set(p["hot_classes"])):
                problems.append(f"barrier_check.py measured classes {sorted(bclasses)}, none of which is on the hazardous "
                                f"side of '{p['name']}' ({', '.join(p['hot_classes'])}): the cross-check did not cover it")
                continue
            if bmin is None:          # 0.0 mm (copper touching) is the worst case and must be checked
                continue
            rn_c, rn_k = f"bw_{p['slug']}_clearance", f"bw_{p['slug']}_creepage"
            if bmin + 1e-6 < p["clearance_rule_mm"] and not (hits.get(rn_c) or hits.get(rn_k)):
                problems.append(f"the checks disagree on '{p['name']}': barrier_check.py measured {bmin:.2f} mm "
                                f"(< {p['clearance_rule_mm']} mm) but KiCad's DRC reported no violation of its rules. "
                                "The rule may match nothing: check the net classes.")
            elif bmin + 1e-6 >= p["rule_mm"] and (hits.get(rn_c) or hits.get(rn_k)):
                notes.append(f"'{p['name']}': KiCad reports a violation that the 2-D check does not see "
                             "(expected for creepage around slots or edges; KiCad's result stands)")
    else:
        notes.append("reports/barrier.json is missing: the independent cross-check did not run "
                     "(KiCad python: scripts/barrier_check.py .)")
        problems.append("independent barrier check (barrier_check.py) has not run")
    return rows, problems, notes


def main(argv: list) -> int:
    args = [a for a in argv if not a.startswith("--")]
    project = Path(args[0]).resolve() if args else Path.cwd()
    try:
        f = project_files(project)
        s = load_config(project).get("safety")
        if not isinstance(s, dict) or not s.get("barriers"):
            print("creepage_rules: no safety.barriers in boardwright.json; nothing to check (low-voltage board).")
            write_report(project, "creepage", {"pass": True, "barriers": [], "errors": 0},
                         ["# Creepage and clearance (creepage_rules.py)", "", "No barriers declared.", "",
                          "Result: PASS"])
            return 0
        plans = plan_barriers(s)
    except (SetupError, ValueError) as exc:
        print(f"creepage_rules: setup problem: {exc}")
        return 2
    if "--write" in argv:
        write_rules(f["dru"], plans)
        print(f"wrote {len(plans) * 2} rules to {f['dru'].name} (backup: {f['dru'].name}.bak)")
        for p in plans:
            print(f"  {p['name']}: clearance {p['clearance_rule_mm']} mm, creepage {p['rule_mm']} mm")
        print("Next: run_gates.py (DRC), then barrier_check.py, then this script without --write.")
        return 0
    rows, problems, notes = check(project, f, plans)
    md = ["# Creepage and clearance (creepage_rules.py)", "",
          md_table(["barrier", "insulation", "req. clearance mm", "req. creepage mm", "designer mm", "rule mm",
                    "slot counts if >= mm"], rows)]
    md = [md[0], md[1]] + md[2] + [""]
    for p in plans:
        md += [f"Rows used for '{p['name']}':"] + [f"- {u}" for u in p["required"]["rows_used"]]
        md += [f"- status: {p['required']['status']}", ""]
    md += [f"- FAIL: {x}" for x in problems] + [f"- note: {x}" for x in notes]
    md += ["", "Not covered: 3-D clearance over part bodies, inner-layer and coated-board rules, distance through "
           "insulation, and the product standard's own tables. A qualified person reviews the insulation diagram.",
           "", f"Result: {'FAIL' if problems else 'PASS'}"]
    write_report(project, "creepage", {"pass": not problems, "errors": len(problems), "problems": problems,
                                       "notes": notes, "barriers": [{k: v for k, v in p.items() if k != "condition"}
                                                                     for p in plans]}, md)
    print("\n".join(md))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
