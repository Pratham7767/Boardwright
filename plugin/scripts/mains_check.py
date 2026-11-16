#!/usr/bin/env python3
"""Mains topology check: the safety parts on the mains side are of the right kind, in the right order.

Usage:  python scripts/mains_check.py <project_dir>

Reads the schematic netlist (kicad-cli), boardwright.json "safety" (mains.line, mains.neutral, hz,
max_vrms, product_class, earth, domains, barriers; see references/high-voltage.md) and the limits in
spacing_tables.json "mains_parts". Writes reports/mains-check.json/.md. Changes nothing.

A part's role comes from its symbol field "safety_class" (fuse, X1, X2, Y1, Y2, MOV, xcap_discharge),
or else from its reference (F = fuse, RV/VR/MOV = varistor) and its value/description/MPN text ("X2",
"Y1"). Parts marked DNP are left out.

Checks (each FAIL is listed with the parts involved):
  1. The line input net reaches a fuse first: no other part touches it except the inlet connector.
  2. Every capacitor between two different mains nets is X (or Y) class.
  3. Every capacitor across an isolation barrier is Y class; reinforced barriers need Y1 (or two Y2 in
     series, stated with the field y_series=2).
  4. Every varistor sits after the fuse (not on the line input net).
  5. X capacitance at or above the table threshold has a discharge path: the time to fall to the limit
     voltage through the resistor path (or a part marked xcap_discharge) is within the limit.
  6. Touch current through the barrier's Y capacitors is estimated and compared with the table value.
  7. Class I products have a protective-earth net on the inlet connector.
Limits in rows 5 and 6 are 'unverified' in the table until checked against IEC 62368-1:2023, so their
results are reported as estimates.
Exit 0 pass, 1 a check failed, 2 setup problem.
"""
from __future__ import annotations

import heapq
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import (SetupError, board_nets, fmt_si, load_config, md_table, nets_by_class,  # noqa: E402
                        parse_value, project_files, write_report)
from spacing import TABLES  # noqa: E402

ROLE_FIELD = "safety_class"
CONNECTOR = re.compile(r"^(J|P|CN|X|CON)\d", re.I)


def role(c: dict) -> str:
    """fuse | X1 | X2 | Y1 | Y2 | cap | MOV | resistor | inductor | ntc | xcap_discharge | other"""
    f = c["fields"]
    tag = (f.get(ROLE_FIELD) or "").strip()
    if tag:
        t = tag.upper()
        return {"FUSE": "fuse", "MOV": "MOV", "VARISTOR": "MOV", "XCAP_DISCHARGE": "xcap_discharge"}.get(t, t if t in ("X1", "X2", "Y1", "Y2") else tag.lower())
    ref = c["ref"].upper()
    text = " ".join([c["value"], f.get("description", ""), f.get("mpn", ""), f.get("value", "")])
    if re.match(r"^F\d", ref):
        return "fuse"
    if re.match(r"^(RV|VR|MOV|VDR)\d", ref):
        return "MOV"
    if re.match(r"^C\d", ref):
        m = re.search(r"\b([XY][12])\b", text.upper())
        return m.group(1) if m else "cap"
    if re.match(r"^TH\d|^NTC", ref):
        return "ntc"
    if re.match(r"^R\d", ref):
        return "resistor"
    if re.match(r"^(L|FB)\d", ref):
        return "inductor"
    return "other"


def build(comps: list, nets: dict) -> dict:
    """{ref: {comp, role, nets:{pin: net}}} for parts that are fitted."""
    parts = {c["ref"]: {"comp": c, "role": role(c), "pins": {}} for c in comps if not c["skip"]}
    for net, nodes in nets.items():
        for nd in nodes:
            if nd["ref"] in parts:
                parts[nd["ref"]]["pins"][nd["pin"]] = net
    return parts


def two_nets(p: dict) -> tuple | None:
    ns = sorted(set(p["pins"].values()))
    return tuple(ns) if len(ns) == 2 else None


def r_path(parts: dict, a: str, b: str) -> tuple:
    """Lowest-resistance path from net a to net b through resistors, NTCs, inductors and fuses
    (series sum; parallel paths ignored, so the result is conservative). -> (ohms or None, refs)."""
    edges: dict = {}
    for ref, p in parts.items():
        if p["role"] not in ("resistor", "ntc", "inductor", "fuse"):
            continue
        tn = two_nets(p)
        if not tn:
            if p["role"] == "inductor" and len(p["pins"]) == 4:      # common-mode choke: windings 1-2 / 3-4 or 1-4 / 2-3
                continue
            continue
        r = parse_value(p["comp"]["value"], "R") if p["role"] in ("resistor", "ntc") else 0.0
        if r is None:
            r = 10.0 if p["role"] == "ntc" else None
        if r is None:
            continue
        for x, y in (tn, tn[::-1]):
            edges.setdefault(x, []).append((y, r, ref))
    # Common-mode chokes: which pins share a winding cannot be read from the netlist (guessing can join
    # line to neutral). Only a "windings" field such as "1-2,3-4" on the symbol connects them.
    for ref, p in parts.items():
        if p["role"] == "inductor" and len(p["pins"]) == 4:
            spec = str(p["comp"]["fields"].get("windings", ""))
            for pair in re.findall(r"(\w+)\s*-\s*(\w+)", spec):
                if all(x in p["pins"] for x in pair):
                    x, y = p["pins"][pair[0]], p["pins"][pair[1]]
                    if x != y:
                        edges.setdefault(x, []).append((y, 0.0, ref))
                        edges.setdefault(y, []).append((x, 0.0, ref))
    best = {a: 0.0}
    heap = [(0.0, a, [])]
    while heap:
        d, n, path = heapq.heappop(heap)
        if n == b:
            return d, path
        if d > best.get(n, math.inf):
            continue
        for m, r, ref in edges.get(n, []):
            nd = d + r
            if nd < best.get(m, math.inf):
                best[m] = nd
                heapq.heappush(heap, (nd, m, path + [ref]))
    return None, []


def analyse(project: Path) -> tuple:
    f = project_files(project)
    cfg = load_config(project)
    s = cfg.get("safety")
    if not isinstance(s, dict) or not s.get("mains"):
        from safety_class import mains_declared
        has_mains_domain = isinstance(s, dict) and any(d.get("kind") == "mains" for d in s.get("domains") or [])
        if mains_declared(project) or has_mains_domain:
            raise SetupError("the board is mains-connected (PROJECT.md, or a domain of kind 'mains'), but "
                             "boardwright.json has no safety.mains section (see references/high-voltage.md)")
        return None, [], ["no safety.mains section: the board is not mains-connected (nothing to check)"]
    mains = s["mains"]
    line, neutral = mains.get("line"), mains.get("neutral")
    if not line or not neutral:
        raise SetupError("safety.mains.line and safety.mains.neutral (the inlet net names) are required")

    from run_gates import find_kicad_cli
    from sch_check import export_netlist, parse_netlist
    cli = find_kicad_cli()
    if not cli:
        raise SetupError("kicad-cli not found")
    if not f["sch"].is_file():
        raise SetupError(f"{f['sch'].name} not found")
    root, _ = export_netlist(cli, f["sch"])
    comps, _lib, nets = parse_netlist(root)
    for n in (line, neutral):
        if n not in nets:
            raise SetupError(f"mains net {n} is not in the schematic netlist")

    # match the net-class patterns against the schematic's own nets, so the check works at stage 4,
    # before the board has any nets (the board's nets are added when it exists)
    names = sorted(set(nets) | set(board_nets(f["pcb"]) if f["pcb"].is_file() else []))
    by_class = nets_by_class(f["pro"], names)
    return run_checks(comps, nets, s, by_class)


def run_checks(comps: list, nets: dict, s: dict, by_class: dict) -> tuple:
    """The checks themselves, on a parsed netlist (separate from file loading so tests can feed it)."""
    mains = s["mains"]
    line, neutral = mains.get("line"), mains.get("neutral")
    parts = build(comps, nets)
    tables = TABLES["mains_parts"]
    domains = s.get("domains") or []

    def domain_nets(names: list) -> set:
        out = set()
        for d in domains:
            if d.get("name") in names:
                for c in d.get("netclasses") or []:
                    out |= set(by_class.get(c, []))
                out |= set(d.get("nets") or [])
        return out

    mains_nets = domain_nets([d["name"] for d in domains if d.get("kind") == "mains"]) | {line, neutral}
    problems, notes, rows = [], [], []

    # 1. fuse first
    on_line = [r for r, p in parts.items() if line in p["pins"].values()]
    fuses = [r for r in on_line if parts[r]["role"] == "fuse"]
    others = [r for r in on_line if parts[r]["role"] != "fuse" and not CONNECTOR.match(r)]
    if not fuses:
        problems.append(f"1. no fuse on the line input net {line} (parts on it: {', '.join(sorted(on_line))})")
    if others:
        problems.append(f"1. parts on {line} before the fuse: {', '.join(sorted(others))} (only the inlet and the fuse belong there)")
    rows.append(["1 fuse first", "FAIL" if not fuses or others else "ok", ", ".join(fuses) or "none"])

    # 2. capacitors across mains nets
    xcaps, bad = [], []
    for r, p in parts.items():
        tn = two_nets(p)
        if p["role"] in ("X1", "X2", "Y1", "Y2", "cap") and tn and tn[0] in mains_nets and tn[1] in mains_nets:
            if p["role"] == "cap":
                bad.append(r)
            else:
                xcaps.append(r)
    if bad:
        problems.append(f"2. capacitors across mains nets without an X/Y class: {', '.join(sorted(bad))} "
                        "(state the class in the value or the safety_class field)")
    rows.append(["2 X class across mains", "FAIL" if bad else "ok", ", ".join(sorted(xcaps)) or "none"])

    # 3. Y capacitors across barriers
    ycaps_all, need = [], tables["y_for_insulation"]
    bridging_other = set()
    for b in s.get("barriers") or []:
        hot = domain_nets(b.get("between") or [])
        rest = any(d.get("rest") and d.get("name") in (b.get("and") or []) for d in domains)
        cold = domain_nets([n for n in (b.get("and") or [])])
        allowed = need.get(b.get("insulation", "basic"), ["Y1", "Y2"])
        for r, p in parts.items():
            pn = set(p["pins"].values())
            crosses = (pn & hot) and ((pn & cold) or (rest and (pn - hot - mains_nets)))
            if not crosses:
                continue
            if p["role"] in ("X1", "X2", "Y1", "Y2", "cap"):
                ok = p["role"] in allowed or (p["role"] == "Y2" and str(p["comp"]["fields"].get("y_series", "")) == "2")
                if not ok:
                    problems.append(f"3. {r} ({p['role']}) bridges the {b.get('insulation', 'basic')} barrier "
                                    f"'{b.get('name')}'; it needs {' or '.join(allowed)}")
                ycaps_all.append((r, b))
            else:
                bridging_other.add(r)
    rows.append(["3 Y class across barriers", "FAIL" if any(p.startswith("3.") for p in problems) else "ok",
                 ", ".join(sorted({r for r, _ in ycaps_all})) or "none"])
    if bridging_other:
        notes.append("parts bridging a barrier that need an insulation rating and certificate checked by hand "
                     f"(transformer, optocoupler ...): {', '.join(sorted(bridging_other))}")

    # 4. varistors after the fuse
    movs = [r for r, p in parts.items() if p["role"] == "MOV"]
    early = [r for r in movs if line in parts[r]["pins"].values()]
    if early:
        problems.append(f"4. varistor(s) on the line input before the fuse: {', '.join(early)}")
    rows.append(["4 varistor after fuse", "FAIL" if early else "ok", ", ".join(sorted(movs)) or "none"])

    # 5. X capacitor discharge
    xd = tables["xcap_discharge"]
    total_x = sum(parse_value(parts[r]["comp"]["value"], "F") or 0 for r in xcaps)
    vpk = (mains.get("max_vrms") or mains.get("vrms") or 0) * math.sqrt(2)
    ics = [r for r, p in parts.items() if p["role"] == "xcap_discharge"]
    if total_x * 1e6 + 1e-12 < xd["applies_from_uF"]:
        rows.append(["5 X discharge", "n/a", f"total X {fmt_si(total_x, 'F') if total_x else '0'} < {xd['applies_from_uF']} uF"])
    elif ics:
        rows.append(["5 X discharge", "check by hand", f"discharge part(s) {', '.join(ics)}: confirm its datasheet timing"])
    else:
        # each X capacitor discharges through the resistive path across its own two nets; the slowest
        # path decides (conservative: all X capacitance is assumed to discharge through it)
        r_ohm, path, missing = None, [], []
        for r in xcaps:
            tn = two_nets(parts[r])
            rr, pp = r_path(parts, tn[0], tn[1])
            if rr is None:
                missing.append(r)
            elif r_ohm is None or rr > r_ohm:
                r_ohm, path = rr, pp
        if missing:
            r_ohm = None
            notes.append(f"5. no resistive path across {', '.join(missing)} (a common-mode choke between them "
                         "needs a 'windings' field such as 1-2,3-4 on its symbol)")
        if r_ohm is not None and r_ohm < 1000:
            problems.append(f"5. the 'discharge path' across the X capacitors is only {fmt_si(r_ohm, 'ohm')} "
                            f"({'+'.join(path)}): that is a short across the mains, check the netlist")
            r_ohm = None
        if r_ohm is None or vpk <= xd["limit_v"]:
            problems.append(f"5. {fmt_si(total_x, 'F')} of X capacitance and no resistive discharge path between the mains "
                            "nets (add a bleeder or a part with safety_class=xcap_discharge)")
            rows.append(["5 X discharge", "FAIL", "no path"])
        else:
            t = r_ohm * total_x * math.log(vpk / xd["limit_v"])
            st = "ok" if t <= xd["time_s"] else "FAIL"
            if st == "FAIL":
                problems.append(f"5. X capacitors discharge to {xd['limit_v']} V in {t:.2f} s through {fmt_si(r_ohm, 'ohm')} "
                                f"({'+'.join(path)}); limit {xd['time_s']} s ({tables['status']})")
            rows.append(["5 X discharge", st, f"{fmt_si(total_x, 'F')} via {'+'.join(path)} = {fmt_si(r_ohm, 'ohm')}: "
                                              f"{t:.2f} s to {xd['limit_v']} V (limit {xd['time_s']} s, unverified)"])

    # 6. touch current estimate
    tc = tables["touch_current"]
    cy = sum(parse_value(parts[r]["comp"]["value"], "F") or 0 for r, _ in ycaps_all)
    hz = mains.get("hz", 50)
    i_ma = 2 * math.pi * hz * cy * (mains.get("max_vrms") or mains.get("vrms") or 0) * 1000
    rows.append(["6 touch current (estimate)", "ok" if i_ma <= tc["limit_ma"] else "over",
                 f"{fmt_si(cy, 'F')} Y at {hz} Hz -> {i_ma:.3f} mA (limit {tc['limit_ma']} mA, unverified)"])
    if i_ma > tc["limit_ma"]:
        notes.append(f"6. estimated touch current {i_ma:.3f} mA is above {tc['limit_ma']} mA (limit unverified; measure it)")

    # 7. protective earth
    pclass = str(s.get("product_class", "")).upper()
    if pclass == "I":
        earth = mains.get("earth")
        if not earth or earth not in nets:
            problems.append("7. product class I but safety.mains.earth names no net in the schematic")
        elif not any(CONNECTOR.match(nd["ref"]) for nd in nets[earth]):
            problems.append(f"7. earth net {earth} does not reach a connector")
        rows.append(["7 protective earth", "FAIL" if any(p.startswith("7.") for p in problems) else "ok", earth or "none"])
    else:
        rows.append(["7 protective earth", "n/a", f"product class {pclass or 'not stated'}"])
    dnp = sorted(c["ref"] for c in comps if c["skip"] and role(c) in ("X1", "X2", "Y1", "Y2", "fuse", "MOV"))
    if dnp:
        notes.append(f"safety parts marked DNP were left out: {', '.join(dnp)}")
    return rows, problems, notes


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        rows, problems, notes = analyse(project)
    except SetupError as exc:
        print(f"mains_check: setup problem: {exc}")
        return 2
    md = ["# Mains topology (mains_check.py)", ""]
    if rows is None:
        md += [notes[0], "", "Result: PASS (not mains-connected)"]
        write_report(project, "mains-check", {"pass": True, "errors": 0, "applies": False}, md)
        print("\n".join(md))
        return 0
    md += md_table(["check", "result", "detail"], rows) + [""]
    md += [f"- FAIL: {p}" for p in problems] + [f"- note: {n}" for n in notes]
    md += ["", f"Limits for rows 5 and 6: {TABLES['mains_parts']['source']} ({TABLES['mains_parts']['status']}). "
           "Measured discharge time and touch current on the built board are the evidence.",
           "", f"Result: {'FAIL' if problems else 'PASS'}"]
    write_report(project, "mains-check", {"pass": not problems, "errors": len(problems), "applies": True,
                                          "rows": rows, "problems": problems, "notes": notes}, md)
    print("\n".join(md))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
