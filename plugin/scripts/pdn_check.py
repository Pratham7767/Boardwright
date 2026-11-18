#!/usr/bin/env python3
"""Power-distribution estimate: does each rail's decoupling keep its impedance under the target?

Usage:  python scripts/pdn_check.py <project_dir>

Reads boardwright.json "pdn":
    [{"rail": "/+3V3", "v": 3.3, "ripple_pct": 3, "i_step_a": 0.15, "f_max_mhz": 20,
      "source": "03-power.md (MCU datasheet peak current, p.48)"}]
and the capacitors between each rail and ground in the schematic netlist.

Target impedance (the usual method, e.g. Altium/Sandler notes): Z_target = V * ripple / I_step.
Each capacitor is a series R-L-C: C from its value; ESL by package size and ESR by type are typical
values (assumptions, listed in the report) unless the symbol has "esl_nh" / "esr_mohm" fields from the
part's own data. The capacitors are summed in parallel; mounting inductance, planes and the regulator's
own output impedance are not modelled, so the result is an estimate of the capacitor bank only.
Fails when the estimated impedance exceeds Z_target anywhere from 100 kHz to f_max_mhz.
Writes reports/pdn.json/.md. Exit 0 pass, 1 over target, 2 setup problem.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, fmt_si, load_config, md_table, parse_value, project_files, write_report  # noqa: E402

# Typical mounted ESL by package (nH) and ESR (mohm): working assumptions, not part data.
ESL_NH = {"0201": 0.3, "0402": 0.4, "0603": 0.6, "0805": 0.8, "1206": 1.0, "1210": 1.2}
ESR_MOHM = {"ceramic": 10, "electrolytic": 100, "tantalum": 300}


def cap_model(c: dict) -> tuple:
    """-> (C farad, L henry, R ohm, note)."""
    C = parse_value(c["value"], "F")
    fp = (c.get("footprint") or "") + " " + c["value"]
    f = c["fields"]
    pkg = next((p for p in ESL_NH if p in fp), None)
    kind = "electrolytic" if re.search(r"(?i)CP_|elec|alum|polar", fp) else \
        "tantalum" if re.search(r"(?i)tant", fp) else "ceramic"
    L = float(f["esl_nh"]) * 1e-9 if f.get("esl_nh") else (ESL_NH.get(pkg, 2.0 if kind != "ceramic" else 1.0) * 1e-9)
    R = float(f["esr_mohm"]) * 1e-3 if f.get("esr_mohm") else ESR_MOHM[kind] * 1e-3
    note = "part data" if f.get("esl_nh") else f"typical {pkg or kind}"
    return C, L, R, note


def z_bank(caps: list, freq: float) -> float:
    y = 0j
    for C, L, R, _ in caps:
        w = 2 * math.pi * freq
        y += 1 / complex(R, w * L - 1 / (w * C))
    return abs(1 / y) if y else math.inf


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        f = project_files(project)
        cfg = load_config(project)
        rails = cfg.get("pdn") or []
        if not rails:
            print("pdn_check: no pdn rails in boardwright.json; nothing to check.")
            write_report(project, "pdn", {"pass": True, "errors": 0, "rows": []},
                         ["# PDN estimate (pdn_check.py)", "", "No rails declared.", "", "Result: PASS"])
            return 0
        for r in rails:
            try:
                fm = float(r.get("f_max_mhz", 20))
            except (TypeError, ValueError):
                raise SetupError(f"rail {r.get('rail')}: f_max_mhz must be a number of MHz")
            if not fm >= 0.1:
                raise SetupError(f"rail {r.get('rail')}: f_max_mhz is {r.get('f_max_mhz')}; the estimate starts at "
                                 "0.1 MHz, so give a value of 0.1 or more")
        gnd = set((cfg.get("emc_rules") or {}).get("ground_nets") or ["/GND", "GND"])
        from run_gates import find_kicad_cli
        from sch_check import export_netlist, parse_netlist
        cli = find_kicad_cli()
        if not cli:
            raise SetupError("kicad-cli not found")
        root, _ = export_netlist(cli, f["sch"])
        comps, _lib, nets = parse_netlist(root)
    except (SetupError, ValueError) as exc:
        print(f"pdn_check: setup problem: {exc}")
        return 2
    by_ref = {c["ref"]: c for c in comps if not c["skip"]}
    pins = {}
    for net, nodes in nets.items():
        for nd in nodes:
            pins.setdefault(nd["ref"], set()).add(net)
    freqs = [10 ** (5 + i / 20) for i in range(61)]          # 100 kHz .. 100 MHz
    rows, problems, notes = [], [], []
    for r in rails:
        rail = r.get("rail")
        try:
            zt = float(r["v"]) * float(r["ripple_pct"]) / 100 / float(r["i_step_a"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            problems.append(f"rail {rail}: v, ripple_pct and i_step_a are all needed")
            continue
        caps = []
        for ref, c in by_ref.items():
            if ref.upper().startswith("C") and pins.get(ref) == {rail} | (pins.get(ref) & gnd) and len(pins.get(ref, ())) == 2 \
                    and pins[ref] & gnd:
                m = cap_model(c)
                if m[0]:
                    caps.append(m + (ref,))
        if not caps:
            problems.append(f"rail {rail}: no capacitor between it and ground in the schematic")
            continue
        fmax = float(r.get("f_max_mhz", 20)) * 1e6
        zs = [(fr, z_bank([c[:4] for c in caps], fr)) for fr in freqs if fr <= fmax]
        worst_f, worst_z = max(zs, key=lambda x: x[1])
        ok = worst_z <= zt
        rows.append([rail, f"{zt * 1000:.1f}", len(caps), fmt_si(sum(c[0] for c in caps), "F"),
                     f"{worst_z * 1000:.1f} at {worst_f / 1e6:.2f} MHz", "ok" if ok else "FAIL", r.get("source", "no source")])
        if not ok:
            over = [fr for fr, z in zs if z > zt]
            problems.append(f"rail {rail}: estimated {worst_z * 1000:.1f} mohm above the {zt * 1000:.1f} mohm target from "
                            f"{over[0] / 1e6:.2f} to {over[-1] / 1e6:.2f} MHz: add capacitance or lower-ESL parts there")
        typ = sorted({c[3] for c in caps if c[3] != "part data"})
        if typ:
            notes.append(f"rail {rail}: ESL/ESR assumed ({', '.join(typ)}); add esl_nh / esr_mohm fields from the parts' data")
    md = ["# PDN estimate (pdn_check.py)", ""]
    md += md_table(["rail", "Z target mohm", "caps", "total C", "worst estimated Z mohm", "result", "current from"], rows) + [""]
    md += [f"- FAIL: {p}" for p in problems] + [f"- note: {n}" for n in notes]
    md += ["", "Estimate of the capacitor bank only (no mounting inductance, planes or regulator output impedance). "
           "Measure the rail's ripple on the built board.", "", f"Result: {'FAIL' if problems else 'PASS'}"]
    write_report(project, "pdn", {"pass": not problems, "errors": len(problems), "rows": rows, "problems": problems,
                                  "notes": notes}, md)
    print("\n".join(md))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
