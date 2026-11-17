#!/usr/bin/env python3
"""High-speed pairs: generated KiCad rules plus an independent measurement of each pair.

Usage:
    <kicad>/bin/python -I scripts/hs_rules.py <project_dir>            measure (read-only; needs pcbnew)
    python scripts/hs_rules.py <project_dir> --write                   (re)write the generated rule block
                                                                       in the .kicad_dru (a .bak is kept)

Reads boardwright.json "high_speed":
    {"er_eff": 3.3, "er_source": "assumption: FR-4 microstrip, effective", "ground_nets": ["/GND"],
     "max_return_via_mm": 1.5,
     "pairs": [{"name": "USB", "p": "/USB_DP", "n": "/USB_DM", "max_skew_mm": 2.5, "max_length_mm": 40,
                "gap_mm": 0.15, "max_uncoupled_mm": 5, "max_vias_each": 2, "source": "part guide, page"}]}
Every limit should carry its source (the part's layout guide and page); without one the report says
"assumption".

--write adds, per pair, KiCad rules for skew (and length, and the coupled gap / uncoupled length when the
names follow KiCad's pair convention: _P/_N, +/-, P/N) at the END of the .kicad_dru between marker lines.
KiCad's own skew rule is known to group nets oddly on some versions, so this script also measures each
pair itself:
  - routed length of each member (tracks, arcs and via barrels) and the skew in mm and ps (at er_eff);
  - the via count of each member (the two must match, and stay within max_vias_each);
  - for every signal via, the distance to the nearest ground via (a return path when the pair changes layer).
Writes reports/hs-check.json/.md. Exit 0 pass, 1 a limit is exceeded, 2 setup problem.
"""
from __future__ import annotations

import math
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, load_config, md_table, project_files, write_report  # noqa: E402

BEGIN = "# >>> boardwright generated high-speed rules (hs_rules.py --write; do not edit by hand) >>>"
END = "# <<< boardwright generated high-speed rules <<<"
C_MM_PER_PS = 0.299792458


def kicad_pair_names(p: str, n: str) -> bool:
    for a, b in (("_P", "_N"), ("+", "-"), ("P", "N")):
        if p.endswith(a) and n.endswith(b) and p[:-len(a)] == n[:-len(b)]:
            return True
    return False


def rule_block(hs: dict) -> str:
    lines = [BEGIN]
    for pr in hs.get("pairs") or []:
        cond = f"A.NetName == '{pr['p']}' || A.NetName == '{pr['n']}'"
        tag = re.sub(r"[^A-Za-z0-9]+", "_", pr["name"]).strip("_").lower()
        lines.append(f"# pair '{pr['name']}': limits from {pr.get('source', 'assumption (no source given)')}")
        if pr.get("max_skew_mm") is not None:
            lines += [f'(rule "bw_hs_{tag}_skew"', f"\t(constraint skew (max {pr['max_skew_mm']}mm))", f'\t(condition "{cond}"))']
        if pr.get("max_length_mm") is not None:
            lines += [f'(rule "bw_hs_{tag}_length"', f"\t(constraint length (max {pr['max_length_mm']}mm))", f'\t(condition "{cond}"))']
        if kicad_pair_names(pr["p"], pr["n"]):
            if pr.get("gap_mm") is not None:
                lines += [f'(rule "bw_hs_{tag}_gap"', f"\t(constraint diff_pair_gap (opt {pr['gap_mm']}mm))",
                          f'\t(condition "A.inDiffPair(\'*\') && ({cond})"))']
            if pr.get("max_uncoupled_mm") is not None:
                lines += [f'(rule "bw_hs_{tag}_uncoupled"', f"\t(constraint diff_pair_uncoupled (max {pr['max_uncoupled_mm']}mm))",
                          f'\t(condition "A.inDiffPair(\'*\') && ({cond})"))']
        else:
            lines.append(f"# (no diff_pair_gap/uncoupled rule: KiCad does not see {pr['p']}/{pr['n']} as a pair by name)")
    lines.append(END)
    return "\n".join(lines) + "\n"


def write_rules(dru: Path, hs: dict) -> None:
    text = dru.read_text("utf-8") if dru.is_file() else "(version 1)\n"
    if dru.is_file():
        shutil.copy2(dru, dru.with_suffix(".kicad_dru.bak"))
    text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S).rstrip() + "\n\n"
    dru.write_text(text + rule_block(hs), "utf-8")


def measure(pcb: Path, hs: dict) -> tuple:
    import pcbnew
    board = pcbnew.LoadBoard(str(pcb))
    nets = set()
    for pr in hs["pairs"]:
        nets |= {pr["p"], pr["n"]}
    gnd = set(hs.get("ground_nets") or ["/GND", "GND"])
    length = {n: 0.0 for n in nets}
    vias = {n: [] for n in nets}
    gvias = []
    # a via adds its barrel to the path (KiCad's length and skew rules count it too); for through vias
    # that is the board thickness
    thick = pcbnew.ToMM(board.GetDesignSettings().GetBoardThickness())
    for t in board.GetTracks():
        name = t.GetNetname()
        cls = t.GetClass()
        if cls == "PCB_VIA":
            xy = (pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y))
            if name in nets:
                vias[name].append(xy)
                length[name] += thick
            elif name in gnd:
                gvias.append(xy)
        elif name in nets:
            length[name] += pcbnew.ToMM(t.GetLength())
    found = {n for n in nets if length[n] > 0 or vias[n]}
    return length, vias, gvias, found


def evaluate(hs: dict, length: dict, vias: dict, gvias: list) -> tuple:
    er = float(hs.get("er_eff", 3.3))
    ps_per_mm = math.sqrt(er) / C_MM_PER_PS
    maxret = float(hs.get("max_return_via_mm", 1.5))
    rows, problems, notes = [], [], []
    for pr in hs["pairs"]:
        p, n, name = pr["p"], pr["n"], pr["name"]
        lp, ln = length.get(p, 0.0), length.get(n, 0.0)
        skew = abs(lp - ln)
        vp, vn = len(vias.get(p, [])), len(vias.get(n, []))
        src = pr.get("source") or "assumption (no source given)"
        res = []
        if pr.get("max_skew_mm") is not None and skew > pr["max_skew_mm"] + 1e-6:
            res.append(f"skew {skew:.2f} mm > {pr['max_skew_mm']} mm")
        for net_, L in ((p, lp), (n, ln)):
            if pr.get("max_length_mm") is not None and L > pr["max_length_mm"] + 1e-6:
                res.append(f"{net_} length {L:.1f} mm > {pr['max_length_mm']} mm")
        if vp != vn:
            res.append(f"via count differs: {p} {vp}, {n} {vn}")
        if pr.get("max_vias_each") is not None and max(vp, vn) > pr["max_vias_each"]:
            res.append(f"{max(vp, vn)} vias on one member > {pr['max_vias_each']}")
        far = []
        for net_ in (p, n):
            for (x, y) in vias.get(net_, []):
                d = min((math.hypot(x - gx, y - gy) for gx, gy in gvias), default=math.inf)
                if d > maxret:
                    far.append(f"{net_} via at ({x:.2f}, {y:.2f}): nearest ground via {'none' if d == math.inf else f'{d:.2f} mm'}")
        if far:
            res.append(f"{len(far)} signal via(s) without a ground via within {maxret} mm")
            notes += far
        rows.append([name, f"{lp:.2f}", f"{ln:.2f}", f"{skew:.2f} mm / {skew * ps_per_mm:.0f} ps",
                     f"{vp} / {vn}", "FAIL" if res else "ok", src])
        problems += [f"pair '{name}': {r}" for r in res]
    return rows, problems, notes


def main(argv: list) -> int:
    args = [a for a in argv if not a.startswith("--")]
    project = Path(args[0]).resolve() if args else Path.cwd()
    try:
        f = project_files(project)
        hs = load_config(project).get("high_speed")
        if not isinstance(hs, dict) or not hs.get("pairs"):
            print("hs_rules: no high_speed.pairs in boardwright.json; nothing to check.")
            write_report(project, "hs-check", {"pass": True, "errors": 0, "pairs": []},
                         ["# High-speed pairs (hs_rules.py)", "", "No pairs declared.", "", "Result: PASS"])
            return 0
        for pr in hs["pairs"]:
            for k in ("name", "p", "n"):
                if not pr.get(k):
                    raise SetupError(f"every high_speed.pairs entry needs '{k}'")
    except SetupError as exc:
        print(f"hs_rules: setup problem: {exc}")
        return 2
    if "--write" in argv:
        write_rules(f["dru"], hs)
        print(f"wrote high-speed rules for {len(hs['pairs'])} pair(s) to {f['dru'].name} (backup: {f['dru'].name}.bak)")
        return 0
    try:
        import pcbnew  # noqa: F401
    except ImportError:
        print("hs_rules: setup problem: run with KiCad's bundled Python (it has pcbnew): <kicad>/bin/python -I scripts/hs_rules.py .")
        return 2
    length, vias, gvias, found = measure(f["pcb"], hs)
    missing = sorted({x for pr in hs["pairs"] for x in (pr["p"], pr["n"])} - found)
    rows, problems, notes = evaluate(hs, length, vias, gvias)
    if missing:
        problems.insert(0, f"not routed or not on the board: {', '.join(missing)}")
    md = ["# High-speed pairs (hs_rules.py)", "",
          f"Propagation: er_eff {hs.get('er_eff', 3.3)} ({hs.get('er_source', 'assumption: FR-4 microstrip')}); "
          "skew in ps is an estimate.", ""]
    md += md_table(["pair", "P length mm", "N length mm", "skew", "vias P / N", "result", "limits from"], rows) + [""]
    md += [f"- FAIL: {p}" for p in problems] + [f"- note: {n}" for n in notes]
    md += ["", "Not covered: impedance (stackup and fab data), coupling over the whole length, crosstalk and "
           "reference-plane changes; those need the fab's stackup and, for fast links, a field solver.",
           "", f"Result: {'FAIL' if problems else 'PASS'}"]
    write_report(project, "hs-check", {"pass": not problems, "errors": len(problems), "rows": rows,
                                       "problems": problems, "notes": notes}, md)
    print("\n".join(md))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    import kicad_python  # under any Python: rerun with KiCad's own, which has pcbnew
    kicad_python.ensure(__file__)
    sys.exit(main(sys.argv[1:]))
