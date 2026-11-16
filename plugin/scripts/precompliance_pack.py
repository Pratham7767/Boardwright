#!/usr/bin/env python3
"""Pre-compliance pack: one document for the person who signs off and the test lab.

Usage:  python scripts/precompliance_pack.py <project_dir>

Collects the results the pipeline already produced (reports/*.json) into reports/precompliance.md:
the safety classification and insulation barriers, required against measured spacing, the mains
topology results, the safety-critical parts register, the EMC harmonic plan and layout findings, the
high-speed, impedance and PDN estimates, and a list of the tests that only a lab can do. Every number
keeps the status its own report gave it (secondary source, unverified, estimate). A report that was
not produced is listed as "not run". The pack is evidence for a responsible person; it is not a test
report or a declaration of conformity. Always exit 0 (2 = setup problem).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, load_config, project_files  # noqa: E402

SECTIONS = [("safety-class", "Voltage domains and energy classes"),
            ("creepage", "Insulation barriers: required and enforced spacing"),
            ("barrier", "Independent barrier measurement"),
            ("mains-check", "Mains topology"),
            ("parts-register", "Safety-critical parts"),
            ("emc-harmonics", "EMC harmonic plan"),
            ("emc-rules", "EMC layout rules"),
            ("emc-geometry", "EMC loop and distance measurements"),
            ("hs-check", "High-speed pairs"),
            ("impedance", "Impedance estimate"),
            ("pdn", "Power-distribution estimate")]

LAB_SAFETY = ["Electric strength (hipot) across every barrier at the standard's test voltage",
              "Touch current, normal and single-fault conditions",
              "X-capacitor discharge time after unplugging",
              "Abnormal and single-fault operation (shorted and open parts, blocked outputs)",
              "Temperature rise of parts, windings and touchable surfaces at full load",
              "Insulation and creepage inspection of the built board and enclosure"]
LAB_EMC = ["Conducted emissions on the mains or DC input with a LISN (150 kHz - 30 MHz)",
           "Radiated emissions (30 MHz - 1 GHz and above, by the standard) with the real cables attached",
           "ESD on connectors and enclosure (IEC 61000-4-2)",
           "Radiated and conducted immunity, EFT and surge as the product standard requires",
           "Pre-compliance first: near-field probe scan at the frequencies in the harmonic plan"]


def load(project: Path, name: str):
    p = project / "reports" / f"{name}.json"
    try:
        return json.loads(p.read_text("utf-8")), p.stat().st_mtime
    except (OSError, ValueError):
        return None, None


def summary(name: str, d: dict) -> list:
    if name == "safety-class":
        out = [f"- standard: {d.get('standard') or 'not named'}; product class: {d.get('product_class') or 'not stated'}"]
        out += [f"- {x['name']}: {x['es']} ({x['nets']} nets)" for x in d.get("domains", [])]
        out += [f"- supply {x['name']}: {x['ps']}" for x in d.get("supplies", [])]
        return out
    if name == "creepage":
        return [f"- {b['name']} ({b['insulation']}): required clearance {b['required']['clearance_mm']} mm, creepage "
                f"{b['required']['creepage_mm']} mm; rule {b['rule_mm']} mm ({b['required']['status']})"
                for b in d.get("barriers", [])]
    if name == "barrier":
        return [f"- closest primary-to-secondary copper: {d.get('minimum_all_mm')} mm (limit {d.get('min_mm')} mm)"]
    if name == "mains-check":
        return [f"- {r[0]}: {r[1]} ({r[2]})" for r in d.get("rows", [])] or ["- not mains-connected"]
    if name == "parts-register":
        return [f"- {r[0]} {r[1]}: {r[3]}; cert {r[4]}, standard {r[5]}, rating {r[6]}" for r in d.get("rows", [])]
    if name == "emc-harmonics":
        out = [f"- {c['name']}: {c['f_hz'] / 1e6:g} MHz" for c in d.get("clocks", [])]
        out += [f"- coinciding harmonics: {len(d.get('coincidences', []))}; probe first at: "
                f"{', '.join(d.get('ports', [])) or 'no connectors'}"]
        return out
    if name == "emc-rules":
        c = d.get("counts", {})
        return [f"- {c.get('HIGH', 0)} HIGH, {c.get('MEDIUM', 0)} MEDIUM, {c.get('LOW', 0)} LOW"] + \
            [f"- {x['rule']} {x['severity']} {x['item']}: {x['detail']}" for x in d.get("findings", [])[:10]]
    if name in ("hs-check", "impedance", "pdn"):
        return [f"- {' | '.join(str(c) for c in r)}" for r in d.get("rows", [])] or ["- nothing declared"]
    if name == "emc-geometry":
        return [f"- {d.get('summary') or 'see reports/emc-geometry.md'}"]
    return []


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        f = project_files(project)
        cfg = load_config(project)
    except SetupError as exc:
        print(f"precompliance_pack: setup problem: {exc}")
        return 2
    board_t = f["pcb"].stat().st_mtime if f["pcb"].is_file() else 0
    md = [f"# Pre-compliance pack: {f['stem']}", "",
          f"Assembled {time.strftime('%Y-%m-%d %H:%M')} from the pipeline's reports. This is evidence for a "
          "responsible person and a plan for the test lab. It is not a test report, a safety certificate or a "
          "declaration of conformity.", ""]
    missing, stale = [], []
    for name, title in SECTIONS:
        d, t = load(project, name)
        md.append(f"## {title}")
        if d is None:
            md += ["- not run", ""]
            missing.append(name)
            continue
        if t < board_t:
            stale.append(name)
        res = d.get("pass")
        gate = isinstance(res, bool) and name not in ("parts-register", "emc-harmonics")
        md += ([f"- result: {'PASS' if res else 'FAIL'}"] if gate else []) + summary(name, d) + [""]
    hazardous = bool((cfg.get("safety") or {}).get("barriers"))
    md += ["## Tests only a lab can do", ""]
    if hazardous:
        md += ["Safety (hazardous voltage present):"] + [f"- {x}" for x in LAB_SAFETY] + [""]
    md += ["EMC:"] + [f"- {x}" for x in LAB_EMC] + [""]
    md += ["## Where the product is sold",
           "- India: notified products need BIS CRS registration with test reports from a BIS-recognised lab "
           "(IS/IEC 62368-1:2023 for new registrations from 1 Nov 2028; research notes, secondary). Telecom "
           "equipment also needs TEC MTCTE. Check the current notification for your product.",
           "- US: FCC Part 15 (SDoC for unintentional radiators). EU: the EMC and Low Voltage directives (CE).", ""]
    if stale:
        md += [f"Reports older than the board (rerun them): {', '.join(stale)}.", ""]
    if missing:
        md += [f"Not run: {', '.join(missing)}.", ""]
    out = project / "reports" / "precompliance.md"
    out.write_text("\n".join(md).rstrip() + "\n", "utf-8")
    print(f"Pre-compliance pack: {out} ({len(SECTIONS) - len(missing)} of {len(SECTIONS)} sections"
          + (f"; stale: {', '.join(stale)}" if stale else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
