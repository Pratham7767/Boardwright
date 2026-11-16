#!/usr/bin/env python3
"""EMC harmonic plan for stage 6: where the board's clocks and switchers land in the emission bands.

Usage:  python scripts/emc_harmonics.py <project_dir>

Reads boardwright.json "emc.clocks": a list of
    {"name": "HSE crystal", "f_hz": 8e6, "kind": "clock", "edge_ns": 2, "source": "U1 datasheet p.12"}
    {"name": "flyback", "f_hz": 65e3, "kind": "switcher", "source": "U101 datasheet p.5"}
kind: clock (default) or switcher. edge_ns (optional) gives the rise time, which sets the knee frequency
1/(pi*tr) above which a square wave's harmonics fall at 40 dB/decade instead of 20.

Writes reports/emc-harmonics.md/.json:
  - radiated (30 MHz - 1 GHz): harmonics per FCC Part 15.109 band and CISPR 32 band, odd ones marked
    (a 50% square wave has mostly odd harmonics), harmonics above the knee marked as weaker;
  - conducted (150 kHz - 30 MHz, FCC 15.107 / CISPR 32): harmonics of switchers and clocks in the band;
  - coincidences: harmonics of different sources within 1% of each other (they add);
  - cable ports to probe first: the board's connectors (J/P/CN/USB references).
This is a plan for pre-compliance measurement, not a prediction of emission levels: those depend on
the layout, the cables and the enclosure. It never fails a design. Exit 0, or 2 for a setup problem.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, load_config, md_table, project_files, write_report  # noqa: E402

# Limits, with sources. FCC: 47 CFR 15.109(a) and 15.107(a), eCFR (primary). CISPR 32: Class B values
# via TI application note summaries (secondary; read the standard before relying on them).
RADIATED = [
    {"band": (30e6, 88e6), "fcc_b_3m_dbuv_m": 40.0, "cispr32_b_10m_dbuv_m": 30.0},
    {"band": (88e6, 216e6), "fcc_b_3m_dbuv_m": 43.5, "cispr32_b_10m_dbuv_m": 30.0},
    {"band": (216e6, 230e6), "fcc_b_3m_dbuv_m": 46.0, "cispr32_b_10m_dbuv_m": 30.0},
    {"band": (230e6, 960e6), "fcc_b_3m_dbuv_m": 46.0, "cispr32_b_10m_dbuv_m": 37.0},
    {"band": (960e6, 1000e6), "fcc_b_3m_dbuv_m": 54.0, "cispr32_b_10m_dbuv_m": 37.0},
]
SOURCES = {"fcc": "47 CFR 15.109(a) Class B at 3 m and 15.107(a) conducted, eCFR (primary)",
           "cispr": "CISPR 32 Class B at 10 m, via TI application-note summaries (secondary source)"}
CONDUCTED = (150e3, 30e6)
PORT = re.compile(r"^(J|P|CN|USB|X)\d+", re.I)


def fmt_f(f: float) -> str:
    return f"{f / 1e6:.3f} MHz" if f >= 1e6 else f"{f / 1e3:.1f} kHz"


def harmonics(f0: float, lo: float, hi: float, cap: int = 4000, last: bool = True) -> list:
    """Harmonics in [lo, hi) (or [lo, hi] for the last band), so a frequency on a band edge counts once."""
    n0 = max(1, math.ceil(lo / f0 - 1e-9))
    return [(n, n * f0) for n in range(n0, cap) if n * f0 < hi or (last and n * f0 <= hi)]


def board_ports(pcb: Path) -> list:
    if not pcb.is_file():
        return []
    refs = set(re.findall(r'\(property\s+"Reference"\s+"([^"]+)"', pcb.read_text("utf-8", errors="replace")))
    return sorted(r for r in refs if PORT.match(r))


def plan(clocks: list) -> dict:
    out = {"radiated": [], "conducted": [], "coincidences": []}
    allh = []
    for c in clocks:
        f0 = float(c["f_hz"])
        knee = 1 / (math.pi * c["edge_ns"] * 1e-9) if c.get("edge_ns") else None
        for b in RADIATED:
            hs = harmonics(f0, b["band"][0], b["band"][1], last=b is RADIATED[-1])
            if hs:
                odd = sum(1 for n, _ in hs if n % 2)
                above = sum(1 for _, f in hs if knee and f > knee)
                out["radiated"].append({"source": c["name"], "band": [fmt_f(b["band"][0]), fmt_f(b["band"][1])],
                                        "count": len(hs), "odd": odd, "first": f"{hs[0][0]} x = {fmt_f(hs[0][1])}",
                                        "above_knee": above, "fcc_b_3m_dbuv_m": b["fcc_b_3m_dbuv_m"],
                                        "cispr32_b_10m_dbuv_m": b["cispr32_b_10m_dbuv_m"]})
        hs = harmonics(f0, *CONDUCTED)
        if hs:
            out["conducted"].append({"source": c["name"], "kind": c.get("kind", "clock"), "count": len(hs),
                                     "first": f"{hs[0][0]} x = {fmt_f(hs[0][1])}",
                                     "note": "the switcher's harmonics fill this band: plan the input filter and a LISN "
                                             "measurement" if c.get("kind") == "switcher" else ""})
        allh += [(f, c["name"], n) for n, f in harmonics(f0, 30e6, 1e9)]
    allh.sort()
    for (f1, s1, n1), (f2, s2, n2) in zip(allh, allh[1:]):
        if s1 != s2 and abs(f2 - f1) <= 0.01 * f1:
            out["coincidences"].append(f"{s1} x{n1} ({fmt_f(f1)}) and {s2} x{n2} ({fmt_f(f2)})")
    return out


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        f = project_files(project)
        clocks = (load_config(project).get("emc") or {}).get("clocks") or []
        for c in clocks:
            if not c.get("name") or not c.get("f_hz"):
                raise SetupError("every emc.clocks entry needs a name and f_hz")
    except SetupError as exc:
        print(f"emc_harmonics: setup problem: {exc}")
        return 2
    ports = board_ports(f["pcb"])
    md = ["# EMC harmonic plan (emc_harmonics.py)", ""]
    if not clocks:
        md += ["No emc.clocks in boardwright.json: list every crystal, oscillator, PLL output and switching "
               "regulator with its frequency and source, then rerun."]
        p = {"radiated": [], "conducted": [], "coincidences": []}
    else:
        p = plan(clocks)
        md += ["Sources declared:"] + [f"- {c['name']}: {fmt_f(float(c['f_hz']))} ({c.get('kind', 'clock')}"
                                       + (f", edge {c['edge_ns']} ns, knee {fmt_f(1 / (math.pi * c['edge_ns'] * 1e-9))}"
                                          if c.get("edge_ns") else "") + f"; {c.get('source', 'source not given')})"
                                       for c in clocks] + [""]
        if p["radiated"]:
            md += ["## Radiated band (30 MHz - 1 GHz)", ""] + md_table(
                ["source", "band", "harmonics", "odd", "first", "above knee", "FCC B 3 m dBuV/m", "CISPR 32 B 10 m dBuV/m"],
                [[r["source"], " - ".join(r["band"]), r["count"], r["odd"], r["first"], r["above_knee"] or "",
                  r["fcc_b_3m_dbuv_m"], r["cispr32_b_10m_dbuv_m"]] for r in p["radiated"]]) + [""]
        if p["conducted"]:
            md += ["## Conducted band (150 kHz - 30 MHz)", ""] + md_table(
                ["source", "kind", "harmonics in band", "first", "note"],
                [[r["source"], r["kind"], r["count"], r["first"], r["note"]] for r in p["conducted"]]) + [""]
        if p["coincidences"]:
            md += ["## Coinciding harmonics (within 1%, they add)", ""] + [f"- {x}" for x in p["coincidences"][:30]] + [""]
    md += ["## Cable ports to probe first", "", ", ".join(ports) if ports else "no connectors found on the board", "",
           f"Limits: {SOURCES['fcc']}; {SOURCES['cispr']}.",
           "This is a measurement plan, not an emission prediction: levels depend on the layout, cables and "
           "enclosure, and are known only from a measurement."]
    write_report(project, "emc-harmonics", {"clocks": clocks, "ports": ports, **p, "sources": SOURCES}, md)
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
