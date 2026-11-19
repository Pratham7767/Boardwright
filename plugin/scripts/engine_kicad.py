"""KiCad-side helpers for engine.py. Run with KiCad's own Python (it has pcbnew):

    python.exe -I engine_kicad.py dsn    <in.kicad_pcb> <out.dsn>
    python.exe -I engine_kicad.py ses    <in.kicad_pcb> <in.ses> <out.kicad_pcb>     import a Specctra session
    python.exe -I engine_kicad.py merge  <base.kicad_pcb> <result.kicad_pcb> <out.kicad_pcb> <nets.json>
    python.exe -I engine_kicad.py copper <in.kicad_pcb>                              {net: [tracks, vias]} as JSON
    python.exe -I engine_kicad.py open   <in.kicad_pcb>                              open connections per net
    python.exe -I engine_kicad.py rules  <in.kicad_pcb>                              the board's limits (um) as JSON
    python.exe -I engine_kicad.py near   <in.kicad_pcb> <request.json>               nets with copper near spots
    python.exe -I engine_kicad.py refill <in.kicad_pcb>                              refill every zone, save in place

open: by KiCad's own connectivity, not capped like the DRC's unconnected list (499 items). For each net,
the pads fall into islands of copper joined to each other; a net with k islands needs k-1 connections.
Also lists the nets that own a copper zone (planes and pours). Prints one JSON line:
{"open": {net: connections}, "total": n, "zone_nets": [...]}.

merge: the output is the base board with the copper (tracks and vias) of the listed nets replaced by the
copper of the same nets in the result board. Every other net keeps exactly the copper it had in the base,
whatever the router did to it. Zones are refilled. Prints one JSON line.
"""
from __future__ import annotations

import json
import sys


def load(path):
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kicad_python
    kicad_python.quiet()                  # no message box that waits for a click (e.g. a missing font)
    import pcbnew
    return pcbnew, pcbnew.LoadBoard(path)


def cmd_dsn(a):
    pcbnew, b = load(a[0])
    ok = pcbnew.ExportSpecctraDSN(b, a[1])
    print(json.dumps({"ok": bool(ok)}))
    return 0 if ok else 1


def cmd_ses(a):
    pcbnew, b = load(a[0])
    ok = pcbnew.ImportSpecctraSES(b, a[1])
    if ok:
        b.Save(a[2])
    print(json.dumps({"ok": bool(ok)}))
    return 0 if ok else 1


def copper_of(b, pcbnew):
    out = {}
    for t in b.GetTracks():
        k = 1 if t.Type() == pcbnew.PCB_VIA_T else 0
        out.setdefault(t.GetNetname(), [0, 0])[k] += 1
    return out


def cmd_copper(a):
    pcbnew, b = load(a[0])
    print(json.dumps(copper_of(b, pcbnew)))
    return 0


def open_nets(b, pcbnew):
    b.BuildConnectivity()
    c = b.GetConnectivity()
    by_net = {}
    for fp in b.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() > 0:
                by_net.setdefault(pad.GetNetname(), []).append(pad)
    out = {}
    for net, pads in by_net.items():
        if len(pads) < 2:
            continue
        left = {p.m_Uuid.AsString(): p for p in pads}
        islands = 0
        while left:
            _k, p = left.popitem()
            islands += 1
            for q in c.GetConnectedItems(p):        # the whole copper island (pads, tracks, vias, zones)
                if q.Type() == pcbnew.PCB_PAD_T:
                    left.pop(q.m_Uuid.AsString(), None)
        if islands > 1:
            out[net] = islands - 1
    return out


def cmd_open(a):
    pcbnew, b = load(a[0])
    o = open_nets(b, pcbnew)
    zones = sorted({z.GetNetname() for z in b.Zones() if z.GetNetCode() > 0 and not z.GetIsRuleArea()})
    print(json.dumps({"open": o, "total": sum(o.values()), "zone_nets": zones}))
    return 0


def cmd_rules(a):
    pcbnew, b = load(a[0])
    ds = b.GetDesignSettings()

    def um(v):
        return round(pcbnew.ToMM(v) * 1000, 1)
    nc = ds.m_NetSettings.GetDefaultNetclass()
    print(json.dumps({"edge_um": um(ds.m_CopperEdgeClearance), "hole_um": um(ds.m_HoleClearance),
                      "min_width_um": um(ds.m_TrackMinWidth), "min_clearance_um": um(ds.m_MinClearance),
                      "hole_to_hole_um": um(ds.m_HoleToHoleMin),
                      # the default net class's via, never smaller than the board's minimums
                      "via_um": max(um(nc.GetViaDiameter()), um(ds.m_ViasMinSize)),
                      "drill_um": max(um(nc.GetViaDrill()), um(ds.m_MinThroughDrill)),
                      "clearance_um": max(um(nc.GetClearance()), um(ds.m_MinClearance)),
                      "width_um": max(um(nc.GetTrackWidth()), um(ds.m_TrackMinWidth))}))
    return 0


def cmd_near(a):
    """request: {"spots": [[x, y] mm ...], "nets": [...], "radius": mm} -> the nets (of those) that have a track
    or via within radius of a spot."""
    pcbnew, b = load(a[0])
    req = json.loads(open(a[1], encoding="utf-8").read())
    nets, r = set(req["nets"]), float(req.get("radius", 1.5))
    spots = [(float(x), float(y)) for x, y in req["spots"]]
    hit = set()
    for t in b.GetTracks():
        n = t.GetNetname()
        if n not in nets or n in hit:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            pts = [t.GetPosition()]
        else:
            pts = [t.GetStart(), t.GetEnd(), (t.GetStart() + t.GetEnd()) / 2]
        for p in pts:
            px, py = pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)
            if any((px - x) ** 2 + (py - y) ** 2 <= r * r for x, y in spots):
                hit.add(n)
                break
    print(json.dumps(sorted(hit)))
    return 0


def cmd_refill(a):
    pcbnew, b = load(a[0])
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(a[0])
    print(json.dumps({"ok": True}))
    return 0


def cmd_merge(a):
    pcbnew, base = load(a[0])
    _p, res = load(a[1])
    nets = set(json.loads(open(a[3], encoding="utf-8").read()))
    # decide first, remove last: removing items leaves the wrappers stale
    old = [t for t in base.GetTracks() if t.GetNetname() in nets]
    new = [t for t in res.GetTracks() if t.GetNetname() in nets]
    for t in old:
        base.Remove(t)
    added = {}
    for t in new:
        c = t.Duplicate()
        net = base.FindNet(t.GetNetname())
        if net is None:
            continue
        c.SetNet(net)
        base.Add(c)
        k = 1 if t.Type() == pcbnew.PCB_VIA_T else 0
        added.setdefault(t.GetNetname(), [0, 0])[k] += 1
    pcbnew.ZONE_FILLER(base).Fill(base.Zones())
    base.Save(a[2])
    print(json.dumps({"ok": True, "copper": added}))
    return 0


def main(argv):
    cmds = {"dsn": cmd_dsn, "ses": cmd_ses, "merge": cmd_merge, "copper": cmd_copper, "open": cmd_open, "rules": cmd_rules, "near": cmd_near, "refill": cmd_refill}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
