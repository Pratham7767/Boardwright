#!/usr/bin/env python3
"""Automatic EMC layout rules, on the routed board (read-only; needs KiCad's pcbnew).

Usage:  <kicad>/bin/python -I scripts/emc_rules.py <project_dir>

Geometric EMC checks in the spirit of the rule lists that commercial checkers publish (HyperLynx DRC's
EMC rules: net crossing gaps, vertical reference change, filter placement, net near plane edge,
exposed length). Written from those public rule descriptions and from the design references in this
plugin; no code was taken from any tool. Zones are refilled in memory only; nothing is saved.

Settings (all optional) in boardwright.json "emc_rules":
    {"ground_nets": ["/GND"], "fast_netclasses": ["USB"], "fast_nets": [], "all_signals": false,
     "return_via_mm": 1.5, "edge_mm": 1.0, "void_min_mm": 2.0, "min_ground_cover_pct": 50}
Fast nets also include every net in boardwright.json "high_speed.pairs".

Rules (severity in brackets):
  R1 track over a gap in the ground pour on the adjacent copper layer        [HIGH fast, MEDIUM other]
  R2 signal via (layer change) with no ground via within return_via_mm       [HIGH fast, LOW other]
     R1 and R2 cover the fast nets; set "all_signals": true to include every signal net. Nets on the
     hazardous side of a safety barrier are never checked against the secondary ground. One row per net.
  R3 cable-port net going from a connector straight to an IC, no filter or
     protection part on the net                                               [MEDIUM]
  R4 fast-net track within edge_mm of the board edge                          [MEDIUM]
  R5 ground pour covers less than min_ground_cover_pct of the board on a layer
     that carries reference for signals                                        [MEDIUM]
  info: outer-layer length of each fast net
Limits are working defaults (labelled as such in the report), not values from a standard.
Writes reports/emc-rules.json/.md. Exit 0 no HIGH finding, 1 a HIGH finding, 2 setup problem.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, load_config, md_table, nets_by_class, board_nets, project_files, write_report  # noqa: E402

CONNECTOR = re.compile(r"^(J|P|CN|USB|X)\d", re.I)
IC = re.compile(r"^(U|IC)\d", re.I)
FILTERISH = re.compile(r"^(R|C|L|FB|D|TVS|F|RV|VR|Z)\d", re.I)
POWER = re.compile(r"(?i)(^|/)(\+?\d+V\d*|VCC|VDD|VBUS|VIN|VBAT|V\+|3V3|5V|12V|PWR)")


def segs(t, pcbnew):
    """Sample points (mm-resolution) along a track/arc as VECTOR2I."""
    a, b = t.GetStart(), t.GetEnd()
    L = max(1, int(pcbnew.ToMM(t.GetLength()) / 0.25))
    return [pcbnew.VECTOR2I(int(a.x + (b.x - a.x) * i / L), int(a.y + (b.y - a.y) * i / L)) for i in range(L + 1)]


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        f = project_files(project)
        cfg = load_config(project)
    except SetupError as exc:
        print(f"emc_rules: setup problem: {exc}")
        return 2
    try:
        import pcbnew
    except ImportError:
        print("emc_rules: setup problem: run with KiCad's bundled Python: <kicad>/bin/python -I scripts/emc_rules.py .")
        return 2
    rc = cfg.get("emc_rules") or {}
    gnd = set(rc.get("ground_nets") or ["/GND", "GND"])
    ret_mm = float(rc.get("return_via_mm", 1.5))
    edge_mm = float(rc.get("edge_mm", 1.0))
    void_min = float(rc.get("void_min_mm", 2.0))
    all_signals = bool(rc.get("all_signals", False))
    min_cover = float(rc.get("min_ground_cover_pct", 50))
    fast = set(rc.get("fast_nets") or [])
    for pr in (cfg.get("high_speed") or {}).get("pairs") or []:
        fast |= {pr.get("p"), pr.get("n")}
    if rc.get("fast_netclasses"):
        by_class = nets_by_class(f["pro"], board_nets(f["pcb"]))
        for c in rc["fast_netclasses"]:
            fast |= set(by_class.get(c, []))
    fast.discard(None)
    # nets on the hazardous side of a safety barrier have no secondary ground under them by design
    hazard_nets = set()
    s = cfg.get("safety") or {}
    if s.get("barriers"):
        hot_domains = {n for b in s["barriers"] for n in b.get("between") or []}
        hot_classes = {c for d in s.get("domains") or [] if d.get("name") in hot_domains for c in d.get("netclasses") or []}
        if hot_classes:
            bc = nets_by_class(f["pro"], board_nets(f["pcb"]))
            for c in hot_classes:
                hazard_nets |= set(bc.get(c, []))

    def checked(net: str) -> bool:
        return bool(net) and net not in gnd and net not in hazard_nets and not POWER.search(net)             and (net in fast or all_signals)

    board = pcbnew.LoadBoard(str(f["pcb"]))
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    cu = list(board.GetEnabledLayers().CuStack())
    gfill = {lid: [] for lid in cu}
    for z in board.Zones():
        if z.GetIsRuleArea() or z.GetNetname() not in gnd:
            continue
        for lid in z.GetLayerSet().Seq():
            if lid in gfill:
                gfill[lid].append(z.GetFilledPolysList(lid))

    def grounded(lid, pt):
        return any(p.Contains(pt) for p in gfill.get(lid, []))

    def neighbours(lid):
        i = cu.index(lid)
        return [cu[j] for j in (i - 1, i + 1) if 0 <= j < len(cu)]

    findings = []

    def add(rule, sev, item, where, detail):
        findings.append({"rule": rule, "severity": sev, "item": item,
                         "where": f"({where[0]:.2f}, {where[1]:.2f}) mm" if where else "", "detail": detail})

    # R1: track over a gap in the reference pour
    tracks = [t for t in board.GetTracks() if t.GetClass() in ("PCB_TRACK", "PCB_ARC")]
    r1 = {}                               # net -> [total mm over gaps, worst piece mm, worst point, layers]
    for t in tracks:
        net = t.GetNetname()
        if not checked(net):
            continue
        refs = [lid for lid in neighbours(t.GetLayer()) if gfill.get(lid)]
        if not refs:
            continue
        pts = segs(t, pcbnew)
        bad = [p for p in pts if not any(grounded(lid, p) for lid in refs)]
        gap = len(bad) * 0.25
        if gap >= void_min:
            m = bad[len(bad) // 2]
            rec = r1.setdefault(net, [0.0, 0.0, None, set()])
            rec[0] += gap
            if gap > rec[1]:
                rec[1], rec[2] = gap, (pcbnew.ToMM(m.x), pcbnew.ToMM(m.y))
            rec[3].add(board.GetLayerName(t.GetLayer()))
    for net, (total, worst, where, layers) in sorted(r1.items()):
        add("R1", "HIGH" if net in fast else "MEDIUM", net, where,
            f"{total:.1f} mm of track on {'/'.join(sorted(layers))} over gaps in the adjacent ground pour "
            f"(longest piece {worst:.1f} mm; gaps under {void_min} mm ignored)")

    # R2: layer change without a nearby ground via
    vias = [v for v in board.GetTracks() if v.GetClass() == "PCB_VIA"]
    gvias = [(pcbnew.ToMM(v.GetPosition().x), pcbnew.ToMM(v.GetPosition().y)) for v in vias if v.GetNetname() in gnd]
    r2 = {}
    for v in vias:
        net = v.GetNetname()
        if not checked(net):
            continue
        x, y = pcbnew.ToMM(v.GetPosition().x), pcbnew.ToMM(v.GetPosition().y)
        d = min((math.hypot(x - gx, y - gy) for gx, gy in gvias), default=math.inf)
        if d > ret_mm:
            r2.setdefault(net, []).append((d, (x, y)))
    for net, lst in sorted(r2.items()):
        d, where = max(lst)
        add("R2", "HIGH" if net in fast else "LOW", net, where,
            f"{len(lst)} layer change(s) without a ground via within {ret_mm} mm (working default); farthest "
            f"{'none' if d == math.inf else f'{d:.2f} mm'}")

    # R3: connector straight to an IC with nothing on the net to filter or protect it
    pads_by_net = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname():
                pads_by_net.setdefault(pad.GetNetname(), set()).add(fp.GetReference())
    for net, refs in sorted(pads_by_net.items()):
        if net in gnd or net.startswith("unconnected-"):
            continue
        conns = sorted(r for r in refs if CONNECTOR.match(r))
        ics = sorted(r for r in refs if IC.match(r))
        others = [r for r in refs if FILTERISH.match(r)]
        # exactly one IC and nothing else: a second IC on the net is usually an ESD/filter part (U refs too)
        if conns and len(ics) == 1 and not others and len(refs) == len(conns) + 1:
            add("R3", "MEDIUM", net, None, f"{', '.join(conns)} to {', '.join(ics)} with no series part, filter or "
                f"protection on the net: a cable on this port carries the IC's noise out and ESD in")

    # R4: fast net near the board edge
    edges = [s for s in board.GetDrawings() if s.GetClass() == "PCB_SHAPE" and s.GetLayer() == pcbnew.Edge_Cuts]
    elines = []
    for s in edges:
        a, b = s.GetStart(), s.GetEnd()
        elines.append(((pcbnew.ToMM(a.x), pcbnew.ToMM(a.y)), (pcbnew.ToMM(b.x), pcbnew.ToMM(b.y))))

    def dist_seg(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        u = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
        return math.hypot(px - (ax + u * dx), py - (ay + u * dy))

    outer = {cu[0], cu[-1]}
    exposed = {}
    for t in tracks:
        net = t.GetNetname()
        if net not in fast:
            continue
        if t.GetLayer() in outer:
            exposed[net] = exposed.get(net, 0.0) + pcbnew.ToMM(t.GetLength())
        if elines:
            pts = [(pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)) for p in segs(t, pcbnew)]
            d = min(dist_seg(p, a, b) for p in pts for a, b in elines)
            half_w = pcbnew.ToMM(t.GetWidth()) / 2
            if d - half_w < edge_mm:
                add("R4", "MEDIUM", net, pts[0], f"track {d - half_w:.2f} mm from the board edge (limit {edge_mm} mm, "
                                                 "working default): fields fringe off the edge")

    # R5: ground coverage per layer
    outline = pcbnew.SHAPE_POLY_SET()
    board_area = outline.Area() / 1e12 if board.GetBoardPolygonOutlines(outline, True) else 0
    cover = {}
    for lid in cu:
        area = sum(p.Area() for p in gfill[lid]) / 1e12
        cover[board.GetLayerName(lid)] = round(100 * area / board_area, 1) if board_area else None
    best = max((v for v in cover.values() if v is not None), default=0)
    if board_area and best < min_cover:
        if hazard_nets:
            add("R5", "LOW", "ground pour", None, f"the best-covered layer has {best:.0f}% ground pour, measured over "
                "the whole board including the hazardous side, which has no ground pour by design")
        else:
            add("R5", "MEDIUM", "ground pour", None, f"the best-covered layer has {best:.0f}% ground pour "
                f"(limit {min_cover:.0f}%, working default): return currents spread and loops grow")

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    findings.sort(key=lambda x: (order[x["severity"]], x["rule"], x["item"]))
    counts = {s: sum(1 for x in findings if x["severity"] == s) for s in order}
    md = ["# EMC layout rules (emc_rules.py)", "",
          f"Fast nets: {', '.join(sorted(fast)) or 'none declared (set emc_rules.fast_netclasses or high_speed.pairs)'}",
          f"Ground nets: {', '.join(sorted(gnd))}. Ground pour cover by layer: "
          + ", ".join(f"{k} {v}%" for k, v in cover.items()), ""]
    if findings:
        md += md_table(["rule", "severity", "net / item", "where", "finding"],
                       [[x["rule"], x["severity"], x["item"], x["where"], x["detail"]] for x in findings[:60]])
        if len(findings) > 60:
            md.append(f"... {len(findings) - 60} more in reports/emc-rules.json")
    else:
        md.append("No findings.")
    if exposed:
        md += ["", "Outer-layer length of fast nets: " + ", ".join(f"{k} {v:.1f} mm" for k, v in sorted(exposed.items()))]
    md += ["", "These are layout risks found from geometry, not emission levels. Limits marked 'working default' "
           "come from design practice, not from a standard; rate each finding in the stage 6 report.",
           "", f"Result: {counts['HIGH']} HIGH, {counts['MEDIUM']} MEDIUM, {counts['LOW']} LOW"]
    write_report(project, "emc-rules", {"pass": counts["HIGH"] == 0, "counts": counts, "findings": findings,
                                        "ground_cover_pct": cover, "fast_nets": sorted(fast),
                                        "exposed_mm": exposed}, md)
    # compact on screen; the full table is in reports/emc-rules.md
    print(f"EMC layout rules: {counts['HIGH']} HIGH, {counts['MEDIUM']} MEDIUM, {counts['LOW']} LOW "
          f"(details: reports/emc-rules.md)")
    for x in findings[:8]:
        print(f"- {x['rule']} {x['severity']} {x['item']} {x['where']}: {x['detail']}")
    if len(findings) > 8:
        print(f"- ... {len(findings) - 8} more")
    return 1 if counts["HIGH"] else 0


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    import kicad_python  # under any Python: rerun with KiCad's own, which has pcbnew
    kicad_python.ensure(__file__)
    sys.exit(main(sys.argv[1:]))
