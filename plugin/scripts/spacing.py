"""Required clearance and creepage for one insulation barrier, by the IEC 60664-1 method.

Library used by creepage_rules.py and safety_class.py (standard library only). Values come from
spacing_tables.json, whose rows carry their source and status. The method follows IEC 60664-1:2020
as summarised by KiCad's calculator (studied, not copied), with one deliberate difference: creepage is
always taken from the next table row up, never interpolated.

    python spacing.py --mains 230 --ovc II --pd 2 --mg IIIb --insulation reinforced [--peak 600] [--altitude 2000]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TABLES = json.loads((Path(__file__).resolve().parent / "spacing_tables.json").read_text("utf-8"))
OVC = ("I", "II", "III", "IV")
INSULATION = ("functional", "basic", "supplementary", "reinforced", "double")
MATERIAL_GROUPS = ("I", "II", "IIIa", "IIIb")


def row_up(rows, x):
    """First [limit, value] row whose limit >= x (the table row that covers x); None if off the table."""
    for lim, val in rows:
        if x <= lim + 1e-9:
            return lim, val
    return None


def material_group(cti: float | None) -> str:
    if cti is None:
        return "IIIb"
    return "I" if cti >= 600 else "II" if cti >= 400 else "IIIa" if cti >= 175 else "IIIb"


def required(mains_vrms: float, ovc: str = "II", pd: int = 2, mg: str = "IIIb",
             insulation: str = "basic", working_vrms: float | None = None, peak_v: float | None = None,
             altitude_m: float = 2000) -> dict:
    """-> dict with clearance_mm, creepage_mm, groove_min_mm and every table row used (for the report)."""
    if ovc not in OVC:
        raise ValueError(f"overvoltage category must be one of {OVC}")
    if pd not in (1, 2, 3):
        raise ValueError("pollution degree must be 1, 2 or 3 (4 is out of scope)")
    if mg not in MATERIAL_GROUPS:
        raise ValueError(f"material group must be one of {MATERIAL_GROUPS}")
    if insulation not in INSULATION:
        raise ValueError(f"insulation must be one of {INSULATION}")
    reinforced = insulation in ("reinforced", "double")
    working_vrms = working_vrms if working_vrms is not None else mains_vrms
    peak_v = peak_v if peak_v is not None else working_vrms * 2 ** 0.5
    used = []

    f1 = TABLES["impulse_voltage_F1"]
    r = row_up([[x["max_v"], x] for x in f1["rows"]], mains_vrms)
    if r is None:
        raise ValueError(f"mains {mains_vrms} V is above Table F.1")
    impulse_v = r[1][ovc]
    used.append(f"F.1: up to {r[0]} V line-neutral, OVC {ovc} -> {impulse_v} V impulse")
    imp_kv = impulse_v / 1000
    if reinforced:
        steps = dict(TABLES["reinforced_impulse_step_5_2_5"]["steps"])
        imp_kv = steps.get(round(imp_kv, 2), imp_kv * 1.6)
        used.append(f"5.2.5: reinforced -> {imp_kv:g} kV")

    f2 = TABLES["clearance_transient_F2"]
    r2 = row_up(f2["rows"], imp_kv)
    if r2 is None:
        raise ValueError("impulse voltage above Table F.2")
    c_transient = max(r2[1], f2["pd_minimum_mm"][str(pd)])
    used.append(f"F.2: up to {r2[0]} kV, PD{pd} -> {c_transient} mm")

    peak_kv = peak_v / 1000 * (1.6 if reinforced else 1.0)
    r8 = row_up(TABLES["clearance_peak_F8"]["rows"], peak_kv)
    if r8 is None:
        raise ValueError("peak voltage above Table F.8")
    c_peak = r8[1]
    used.append(f"F.8: peak {peak_kv:.3g} kV{' (x1.6 reinforced)' if reinforced else ''} -> {c_peak} mm")

    ra = row_up(TABLES["altitude_A2"]["rows"], altitude_m)
    if ra is None:
        raise ValueError("altitude above Table A.2")
    clearance = round(max(c_transient, c_peak) * ra[1], 3)
    if ra[1] != 1.0:
        used.append(f"A.2: {altitude_m:g} m -> x{ra[1]}")

    f5 = TABLES["creepage_F5"]
    pcb_column = pd in (1, 2) and mg != "IIIb"
    col = (f5["printed_board_pd1"] if pd == 1 else f5["printed_board_pd2"]) if pcb_column else \
        (f5["pd2_mg3"] if pd in (1, 2) else f5["pd3_mg3"])
    colname = (f"printed-board PD{pd}" if pcb_column else f"PD{max(pd, 2)} material group III")
    r5 = row_up(col, working_vrms)
    if r5 is None:
        raise ValueError(f"working voltage {working_vrms} V above Table F.5 column {colname}")
    creepage = r5[1] * (2 if reinforced else 1)
    used.append(f"F.5 {colname}: up to {r5[0]} V rms -> {r5[1]} mm{' x2 reinforced' if reinforced else ''}")
    if creepage < clearance:
        used.append(f"creepage raised to the clearance ({clearance} mm)")
        creepage = clearance
    groove = TABLES["groove_6_8"]["min_width_mm"][str(pd)]
    if clearance < 3:
        groove = round(min(groove, clearance / 3), 3)
    return {"clearance_mm": clearance, "creepage_mm": round(creepage, 3), "groove_min_mm": groove,
            "impulse_v": impulse_v, "working_vrms": working_vrms, "peak_v": round(peak_v, 1),
            "inputs": {"mains_vrms": mains_vrms, "ovc": ovc, "pd": pd, "mg": mg, "insulation": insulation,
                       "altitude_m": altitude_m},
            "rows_used": used, "status": "secondary source (IEC 60664-1:2020 tables via summaries; not checked "
                                         "against the purchased standard or the product standard)"}


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Required clearance and creepage (IEC 60664-1 method)")
    ap.add_argument("--mains", type=float, required=True, help="mains line-to-neutral V rms, e.g. 230")
    ap.add_argument("--ovc", default="II", choices=OVC)
    ap.add_argument("--pd", type=int, default=2, choices=(1, 2, 3))
    ap.add_argument("--mg", default="IIIb", choices=MATERIAL_GROUPS)
    ap.add_argument("--insulation", default="basic", choices=INSULATION)
    ap.add_argument("--working", type=float, help="working voltage V rms across the barrier (default: mains)")
    ap.add_argument("--peak", type=float, help="recurring peak V across the barrier")
    ap.add_argument("--altitude", type=float, default=2000)
    a = ap.parse_args(argv)
    try:
        r = required(a.mains, a.ovc, a.pd, a.mg, a.insulation, a.working, a.peak, a.altitude)
    except ValueError as exc:
        print(f"spacing: {exc}. The tables cover mains up to 1000 V, working voltages up to 1000 V rms and "
              "altitudes up to 10000 m; outside them, use the standard directly.")
        return 2
    print(f"clearance >= {r['clearance_mm']} mm, creepage >= {r['creepage_mm']} mm, slots count if >= {r['groove_min_mm']} mm wide")
    for u in r["rows_used"]:
        print("  " + u)
    print("  status: " + r["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
