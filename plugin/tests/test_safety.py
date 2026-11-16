#!/usr/bin/env python3
"""Tests for the Phase 1 safety, EMC and high-speed checks (standard library only; no KiCad needed).

    python plugin/tests/test_safety.py

Each test feeds a small, made-up input and checks that a good design passes and each planted fault fails.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import emc_harmonics  # noqa: E402
import hs_rules  # noqa: E402
import mains_check  # noqa: E402
import safety_class  # noqa: E402
import spacing  # noqa: E402
from bw_project import parse_value, pattern_matches  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# --------------------------------------------------------------- spacing (IEC 60664-1 method)
def test_spacing():
    r = spacing.required(250, "II", 2, "IIIb", "reinforced", 250, 600)
    check("spacing: 250 V reinforced PD2 IIIb = 3.0 / 5.0 mm", (r["clearance_mm"], r["creepage_mm"]) == (3.0, 5.0), str(r))
    r = spacing.required(250, "II", 2, "IIIb", "basic")
    check("spacing: 250 V basic = 1.5 / 2.5 mm", (r["clearance_mm"], r["creepage_mm"]) == (1.5, 2.5), str(r))
    r = spacing.required(230, "II", 2, "IIIb", "basic")
    check("spacing: 230 V takes the 250 V creepage row (no interpolation)", r["creepage_mm"] == 2.5, str(r))
    r = spacing.required(250, "II", 2, "IIIb", "reinforced", altitude_m=3000)
    check("spacing: altitude 3000 m scales clearance x1.14", abs(r["clearance_mm"] - 3.42) < 1e-6, str(r))
    r = spacing.required(250, "II", 2, "IIIa", "reinforced")
    check("spacing: creepage never below clearance", r["creepage_mm"] >= r["clearance_mm"], str(r))
    check("spacing: unknown CTI = material group IIIb", spacing.material_group(None) == "IIIb")
    check("spacing CLI: off-table input gives exit 2, not a crash", spacing.main(["--mains", "2000"]) == 2)
    try:
        spacing.required(250, "V", 2, "IIIb", "basic")
        check("spacing: bad overvoltage category rejected", False)
    except ValueError:
        check("spacing: bad overvoltage category rejected", True)


def test_helpers():
    check("parse: 0.33uF X2 305VAC", abs(parse_value("0.33uF X2 305VAC", "F") - 0.33e-6) < 1e-12)
    check("parse: 4k7", parse_value("4k7", "R") == 4700)
    check("parse: 1.5M 500V", parse_value("1.5M 500V", "R") == 1.5e6)
    check("parse: class tag before the value (X2 0.33uF)", abs(parse_value("X2 0.33uF", "F") - 0.33e-6) < 1e-12)
    check("parse: Y1 1nF", abs(parse_value("Y1 1nF", "F") - 1e-9) < 1e-15)
    check("parse: fuse rating T2A", parse_value("T2A", "A") == 2.0)
    check("pattern: /AC* matches /AC1", pattern_matches("/AC*", "/AC1"))
    check("pattern: /TYPO_X does not match /X", not pattern_matches("/TYPO_X", "/X"))


def test_energy_classes():
    check("ES1: 12 Vdc", safety_class.es_class({"vdc": 12}) == "ES1")
    check("ES2: 100 Vdc", safety_class.es_class({"vdc": 100}) == "ES2")
    check("ES3: 250 Vrms", safety_class.es_class({"vrms": 250}) == "ES3")
    check("ES3: 20 V but mains-referenced", safety_class.es_class({"vdc": 20, "mains_referenced": True}) == "ES3")
    check("PS1: 2.5 W", safety_class.ps_class(2.5) == "PS1")
    check("PS3: 150 W", safety_class.ps_class(150) == "PS3")
    check("PS unverified without a power figure", safety_class.ps_class(None) == "unverified")


# --------------------------------------------------------------- mains topology
def comp(ref, value, **fields):
    return {"ref": ref, "value": value, "footprint": "", "fields": {k.lower(): v for k, v in fields.items()},
            "skip": fields.pop("dnp", False) if "dnp" in fields else False, "lib": "", "part": ""}


def net(*nodes):
    return [{"ref": n.split(".")[0], "pin": n.split(".")[1], "func": "", "type": ""} for n in nodes]


GOOD_COMPS = [comp("J1", "MAINS_IN"), comp("F1", "T1A"), comp("RV1", "S07K275"), comp("C1", "0.47uF X2"),
              comp("R1", "1M"), comp("R2", "1M"), comp("C2", "1nF Y1"), comp("T1", "flyback")]
GOOD_NETS = {"/L_IN": net("J1.1", "F1.1"), "/N_IN": net("J1.2", "RV1.2", "C1.2", "R2.2"),
             "/L_F": net("F1.2", "RV1.1", "C1.1", "R1.1"), "/MID": net("R1.2", "R2.1"),
             "/HV": net("C2.1", "T1.1"), "/GND": net("C2.2", "T1.3")}
SAFETY = {"mains": {"vrms": 230, "max_vrms": 250, "hz": 50, "line": "/L_IN", "neutral": "/N_IN"},
          "product_class": "II",
          "domains": [{"name": "Mains", "nets": ["/L_IN", "/N_IN", "/L_F", "/MID"], "kind": "mains"},
                      {"name": "Primary", "nets": ["/HV"], "mains_referenced": True},
                      {"name": "Secondary", "rest": True, "vdc": 12}],
          "barriers": [{"name": "pri-sec", "between": ["Mains", "Primary"], "and": ["Secondary"],
                        "insulation": "reinforced"}]}


def run(comps, nets, safety=SAFETY):
    rows, problems, notes = mains_check.run_checks(comps, nets, copy.deepcopy(safety), {})
    return problems


def test_mains_good():
    p = run(GOOD_COMPS, GOOD_NETS)
    check("mains: good design passes", not p, "; ".join(p))


def test_mains_faults():
    comps = [c for c in GOOD_COMPS if c["ref"] != "F1"] + [comp("F1", "T1A", safety_class="resistor")]
    check("mains: no fuse on the line fails", any(x.startswith("1.") for x in run(comps, GOOD_NETS)))

    nets = dict(GOOD_NETS, **{"/L_IN": net("J1.1", "F1.1", "RV1.1"), "/L_F": net("F1.2", "C1.1", "R1.1")})
    p = run(GOOD_COMPS, nets)
    check("mains: varistor before the fuse fails (rule 1 and 4)",
          any(x.startswith("4.") for x in p) and any(x.startswith("1.") for x in p), "; ".join(p))

    comps = [c if c["ref"] != "C1" else comp("C1", "0.47uF 275V") for c in GOOD_COMPS]
    check("mains: capacitor across mains without X class fails", any(x.startswith("2.") for x in run(comps, GOOD_NETS)))

    comps = [c if c["ref"] != "C2" else comp("C2", "2.2nF Y2") for c in GOOD_COMPS]
    check("mains: Y2 across reinforced insulation fails", any(x.startswith("3.") for x in run(comps, GOOD_NETS)))
    comps = [c if c["ref"] != "C2" else comp("C2", "2.2nF Y2", y_series="2") for c in GOOD_COMPS]
    check("mains: Y2 with y_series=2 is accepted", not any(x.startswith("3.") for x in run(comps, GOOD_NETS)))

    comps = [c for c in GOOD_COMPS if c["ref"] not in ("R1", "R2")]
    nets = {k: [n for n in v if n["ref"] not in ("R1", "R2")] for k, v in GOOD_NETS.items()}
    check("mains: 0.47 uF X capacitance without a bleeder fails", any(x.startswith("5.") for x in run(comps, nets)))

    comps = [c if c["ref"] not in ("R1", "R2") else comp(c["ref"], "10M") for c in GOOD_COMPS]
    check("mains: bleeder too large (20 Mohm, slow discharge) fails", any(x.startswith("5.") for x in run(comps, GOOD_NETS)))

    s = copy.deepcopy(SAFETY)
    s["product_class"] = "I"
    check("mains: class I without an earth net fails", any(x.startswith("7.") for x in run(GOOD_COMPS, GOOD_NETS, s)))


# --------------------------------------------------------------- high-speed pairs
HS = {"er_eff": 3.3, "max_return_via_mm": 1.5, "pairs": [
    {"name": "USB", "p": "/D_P", "n": "/D_N", "max_skew_mm": 1.0, "max_length_mm": 50, "max_vias_each": 2}]}


def test_hs_pairs():
    rows, p, _ = hs_rules.evaluate(HS, {"/D_P": 30.0, "/D_N": 30.5}, {"/D_P": [(0, 0)], "/D_N": [(1, 0)]}, [(0, 1), (1, 1)])
    check("hs: matched pair with return vias passes", not p, "; ".join(p))
    _, p, _ = hs_rules.evaluate(HS, {"/D_P": 30.0, "/D_N": 32.0}, {"/D_P": [], "/D_N": []}, [])
    check("hs: 2 mm skew over a 1 mm limit fails", any("skew" in x for x in p))
    _, p, _ = hs_rules.evaluate(HS, {"/D_P": 30.0, "/D_N": 30.0}, {"/D_P": [], "/D_N": [(0, 0), (1, 1)]}, [(0, 1), (1, 2)])
    check("hs: unequal via count fails", any("via count" in x for x in p))
    _, p, _ = hs_rules.evaluate(HS, {"/D_P": 30.0, "/D_N": 30.0}, {"/D_P": [(0, 0)], "/D_N": [(1, 0)]}, [(9, 9)])
    check("hs: signal via without a nearby ground via fails", any("ground via" in x for x in p))
    _, p, _ = hs_rules.evaluate(HS, {"/D_P": 60.0, "/D_N": 60.0}, {"/D_P": [], "/D_N": []}, [])
    check("hs: over-length pair fails", any("length" in x for x in p))
    check("hs: KiCad pair names recognised (_P/_N)", hs_rules.kicad_pair_names("/USB_P", "/USB_N"))
    check("hs: DP/DM is not a KiCad pair by name", not hs_rules.kicad_pair_names("/USB_DP", "/USB_DM"))
    block = hs_rules.rule_block(HS)
    check("hs: rule block has skew and length rules", "constraint skew (max 1.0mm)" in block and "constraint length (max 50mm)" in block)


# --------------------------------------------------------------- EMC harmonic plan
def test_harmonics():
    p = emc_harmonics.plan([{"name": "X", "f_hz": 8e6}])
    total = sum(r["count"] for r in p["radiated"])
    check("harmonics: 8 MHz has 122 harmonics from 32 MHz to 1 GHz, each counted once", total == 122, str(total))
    p = emc_harmonics.plan([{"name": "A", "f_hz": 8e6}, {"name": "B", "f_hz": 12e6}])
    check("harmonics: 8 and 12 MHz coincide at 48 MHz", any("48.000 MHz" in c for c in p["coincidences"]))
    p = emc_harmonics.plan([{"name": "SW", "f_hz": 100e3, "kind": "switcher"}])
    check("harmonics: a 100 kHz switcher fills the conducted band", p["conducted"] and p["conducted"][0]["count"] == 299,
          str(p["conducted"]))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"\n{'all passed' if not FAILS else str(len(FAILS)) + ' FAILED'}")
    sys.exit(1 if FAILS else 0)
