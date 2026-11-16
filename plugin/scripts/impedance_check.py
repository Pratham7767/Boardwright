#!/usr/bin/env python3
"""Impedance estimate for controlled-impedance net classes (standard library only).

Usage:  python scripts/impedance_check.py <project_dir>

Reads boardwright.json "high_speed.impedance":
    [{"netclass": "USB", "target_diff_ohm": 90, "tolerance_pct": 10, "layer": "outer",
      "source": "USB 2.0 spec 7.1.2 / chip layout guide"},
     {"netclass": "RF", "target_ohm": 50, "layer": "outer", "source": "..."}]
and the widths and gaps of those net classes from the .kicad_pro (track_width, diff_pair_width,
diff_pair_gap). The stackup comes, in order, from the board file's (stackup ...) section,
"high_speed.stackup" {"h_mm", "er", "t_mm", "source"}, or KiCad's default 2-layer stackup (1.51 mm
FR-4, er 4.5, 35 um copper), which the report names as "not the fab's".

Formulas (closed form, cited):
  microstrip  Hammerstad & Jensen, "Accurate Models for Microstrip Computer-Aided Design", IEEE MTT-S 1980,
              with the Wheeler/Hammerstad strip-thickness correction;
  stripline   IPC-2141A symmetric stripline: Z0 = 60/sqrt(er) * ln(4b / (0.67 pi (0.8 w + t)));
  differential edge-coupled microstrip: Zdiff = 2 Z0 (1 - 0.48 exp(-0.96 s/h)) (IPC-2141A), and
              edge-coupled stripline: Zdiff = 2 Z0 (1 - 0.374 exp(-2.9 s/b)).
These are estimates (typically within 5-10% of a field solver for common geometries). The fab's own
calculator for its real materials decides the width: this check catches a width that is clearly wrong.
Writes reports/impedance.json/.md. Exit 0 within tolerance, 1 outside, 2 setup problem.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, load_config, md_table, project_files, write_report  # noqa: E402

ZFREE = 376.730313
KICAD_DEFAULT = {"h_mm": 1.51, "er": 4.5, "t_mm": 0.035,
                 "source": "KiCad's default 2-layer stackup, NOT the fab's: give the fab's in high_speed.stackup"}


def _z01(u: float) -> float:
    f = 6 + (2 * math.pi - 6) * math.exp(-((30.666 / u) ** 0.7528))
    return ZFREE / (2 * math.pi) * math.log(f / u + math.sqrt(1 + (2 / u) ** 2))


def _eeff(u: float, er: float) -> float:
    a = 1 + math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) / 49 + math.log(1 + (u / 18.1) ** 3) / 18.7
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)


def microstrip(w: float, h: float, t: float, er: float) -> tuple:
    """-> (Z0 ohm, effective er). Hammerstad-Jensen with strip-thickness correction."""
    u, tn = w / h, t / h
    if tn > 0:
        coth2 = (1 / math.tanh(math.sqrt(6.517 * u))) ** 2
        du1 = tn / math.pi * math.log(1 + 4 * math.e / (tn * coth2))
        dur = 0.5 * (1 + 1 / math.cosh(math.sqrt(er - 1))) * du1
    else:
        du1 = dur = 0.0
    u1, ur = u + du1, u + dur
    ee = _eeff(ur, er) * (_z01(u1) / _z01(ur)) ** 2
    return _z01(ur) / math.sqrt(_eeff(ur, er)), ee


def stripline(w: float, b: float, t: float, er: float) -> float:
    return 60 / math.sqrt(er) * math.log(4 * b / (0.67 * math.pi * (0.8 * w + t)))


def diff_microstrip(w: float, s: float, h: float, t: float, er: float) -> float:
    z0, _ = microstrip(w, h, t, er)
    return 2 * z0 * (1 - 0.48 * math.exp(-0.96 * s / h))


def diff_stripline(w: float, s: float, b: float, t: float, er: float) -> float:
    return 2 * stripline(w, b, t, er) * (1 - 0.374 * math.exp(-2.9 * s / b))


def board_stackup(pcb: Path) -> dict | None:
    """Outer dielectric (first one under F.Cu) from the board's (stackup ...) section."""
    if not pcb.is_file():
        return None
    text = pcb.read_text("utf-8", errors="replace")
    m = re.search(r"\(stackup(.*?)\n\t\t\)", text, re.S)
    if not m:
        return None
    layers = re.findall(r'\(layer\s+"([^"]+)"(.*?)\n\t\t\t\)', m.group(1), re.S)
    cu_t, h, er = None, None, None
    for name, body in layers:
        th = re.search(r"\(thickness\s+([\d.]+)", body)
        if name == "F.Cu" and th:
            cu_t = float(th.group(1))
        elif "dielectric" in name and th and h is None:
            h = float(th.group(1))
            e = re.search(r"\(epsilon_r\s+([\d.]+)", body)
            er = float(e.group(1)) if e else None
    if cu_t and h and er:
        return {"h_mm": h, "er": er, "t_mm": cu_t, "source": "board file stackup (as entered in KiCad Board Setup)"}
    return None


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        f = project_files(project)
        hs = load_config(project).get("high_speed") or {}
        targets = hs.get("impedance") or []
        if not targets:
            print("impedance_check: no high_speed.impedance in boardwright.json; nothing to check.")
            write_report(project, "impedance", {"pass": True, "errors": 0, "rows": []},
                         ["# Impedance estimate (impedance_check.py)", "", "No targets declared.", "", "Result: PASS"])
            return 0
        classes = {c.get("name"): c for c in json.loads(f["pro"].read_text("utf-8")).get("net_settings", {}).get("classes", [])}
        st = hs.get("stackup") or board_stackup(f["pcb"]) or KICAD_DEFAULT
        h, er, t = float(st["h_mm"]), float(st["er"]), float(st.get("t_mm", 0.035))
    except (SetupError, ValueError, KeyError) as exc:
        print(f"impedance_check: setup problem: {exc}")
        return 2
    rows, problems = [], []
    for tg in targets:
        cls = classes.get(tg.get("netclass"))
        if not cls:
            problems.append(f"net class '{tg.get('netclass')}' is not defined in {f['pro'].name}")
            continue
        tol = float(tg.get("tolerance_pct", 10))
        inner = tg.get("layer", "outer") == "inner"
        b = float(tg.get("plane_spacing_mm", 2 * h))
        if tg.get("target_diff_ohm"):
            w, s = float(cls.get("diff_pair_width") or cls.get("track_width")), float(cls.get("diff_pair_gap"))
            z = diff_stripline(w, s, b, t, er) if inner else diff_microstrip(w, s, h, t, er)
            target, kind, geom = float(tg["target_diff_ohm"]), "differential", f"w {w} / gap {s} mm"
        else:
            w = float(cls.get("track_width"))
            z = stripline(w, b, t, er) if inner else microstrip(w, h, t, er)[0]
            target, kind, geom = float(tg["target_ohm"]), "single-ended", f"w {w} mm"
        dev = 100 * (z - target) / target
        ok = abs(dev) <= tol
        rows.append([tg["netclass"], kind, "stripline" if inner else "microstrip", geom, f"{z:.1f}", f"{target:g}",
                     f"{dev:+.0f}%", "ok" if ok else "FAIL", tg.get("source", "no source given")])
        if not ok:
            problems.append(f"{tg['netclass']}: estimated {z:.1f} ohm {kind} vs target {target:g} ohm ({dev:+.0f}%, "
                            f"tolerance {tol:g}%): ask the fab's calculator for the width and gap on its stackup")
    md = ["# Impedance estimate (impedance_check.py)", "",
          f"Stackup: h {h} mm, er {er}, copper {t} mm. Source: {st.get('source', 'given in boardwright.json')}.", ""]
    md += md_table(["net class", "type", "model", "geometry", "estimate ohm", "target ohm", "deviation", "result",
                    "target from"], rows) + [""]
    md += [f"- FAIL: {p}" for p in problems]
    md += ["", "Closed-form estimate (Hammerstad-Jensen microstrip; IPC-2141A stripline and coupled pairs). "
           "The fab's calculator for its real materials sets the width; order impedance control when the "
           "interface needs it.", "", f"Result: {'FAIL' if problems else 'PASS'}"]
    write_report(project, "impedance", {"pass": not problems, "errors": len(problems), "rows": rows,
                                        "stackup": {"h_mm": h, "er": er, "t_mm": t, "source": st.get("source")},
                                        "problems": problems}, md)
    print("\n".join(md))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
