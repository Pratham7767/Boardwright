"""KiCad-side helpers for engine.py. Run with KiCad's own Python (it has pcbnew):

    python.exe -I engine_kicad.py dsn    <in.kicad_pcb> <out.dsn>
    python.exe -I engine_kicad.py ses    <in.kicad_pcb> <in.ses> <out.kicad_pcb>     import a Specctra session
    python.exe -I engine_kicad.py merge  <base.kicad_pcb> <result.kicad_pcb> <out.kicad_pcb> <nets.json>
    python.exe -I engine_kicad.py copper <in.kicad_pcb>                              {net: [tracks, vias]} as JSON
    python.exe -I engine_kicad.py open   <in.kicad_pcb>                              open connections per net
    python.exe -I engine_kicad.py rules  <in.kicad_pcb>                              the board's limits (um) as JSON
    python.exe -I engine_kicad.py near   <in.kicad_pcb> <request.json>               nets with copper near spots
    python.exe -I engine_kicad.py refill <in.kicad_pcb>                              refill every zone, save in place
    python.exe -I engine_kicad.py zones  <in.kicad_pcb>                              filled area and islands per zone
    python.exe -I engine_kicad.py audit  <in.kicad_pcb> <request.json>               copper below its net class's sizes,
                                                                                     or tracks on another net's plane
    python.exe -I engine_kicad.py textguard <in.kicad_pcb> <out.kicad_pcb>         keep-outs over copper text
    python.exe -I engine_kicad.py moved  <base.kicad_pcb> <result.kicad_pcb> <nets.json>  other nets the router moved
    python.exe -I engine_kicad.py trim   <in.kicad_pcb> <out.kicad_pcb> <nets.json>   remove undersized single-segment taps
    python.exe -I engine_kicad.py planes <in.kicad_pcb>                              plane layers and the copper layer order

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
                      "width_um": max(um(nc.GetTrackWidth()), um(ds.m_TrackMinWidth)),
                      # the pour nets' own classes: the plane repair must lay their copper at these sizes
                      "pour_classes": {n: [um(c.GetTrackWidth()), um(c.GetViaDiameter()), um(c.GetViaDrill())]
                                       for n in {z.GetNetname() for z in b.Zones()
                                                 if z.GetNetCode() > 0 and not z.GetIsRuleArea()}
                                       for c in [ds.m_NetSettings.GetEffectiveNetClass(n)]}}))
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


def cmd_zones(a):
    """{"<net>@<layer>": [filled mm2, islands]} for every copper zone, from the fill saved in the file."""
    pcbnew, b = load(a[0])
    out = {}
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() <= 0:
            continue
        for layer in z.GetLayerSet().Seq():
            if not z.HasFilledPolysForLayer(layer):
                continue
            polys = z.GetFilledPolysList(layer)
            key = f"{z.GetNetname()}@{b.GetLayerName(layer)}"
            area = polys.Area() / 1e12 if hasattr(polys, "Area") else 0.0
            prev = out.get(key, [0.0, 0])
            out[key] = [round(prev[0] + area, 2), prev[1] + polys.OutlineCount()]
    print(json.dumps(out))
    return 0


NECK_MAX_NM = 2_000_000      # a neck-down is at most 2 mm long


def neck_down(b, pcbnew, t, class_w) -> bool:
    """The owner's rule (2026-11-25): a track may be narrower than its net class where it enters a pad of its
    own net, only as far as needed: no narrower than the smaller of the class width and the pad's short side,
    and at most 2 mm long. A long thin power track still fails."""
    if t.GetLength() > NECK_MAX_NM:
        return False
    for p in (t.GetStart(), t.GetEnd()):
        for pad in b.GetPads():
            if pad.GetNetname() == t.GetNetname() and pad.HitTest(p):
                size = pad.GetBoundingBox()
                need = min(class_w, size.GetWidth(), size.GetHeight())
                if t.GetWidth() + 1000 >= need:
                    return True
    return False


def cmd_audit(a):
    """{net: first problem} for the listed nets whose tracks are narrower than their net class's track width, or
    whose vias are smaller than its via size or drill. KiCad's DRC checks only the board's minimums, so a router
    could lay a power net at the board minimum and still pass it."""
    pcbnew, b = load(a[0])
    req = json.loads(open(a[1], encoding="utf-8").read())
    nets = set(req["nets"] if isinstance(req, dict) else req)
    planes = req.get("planes", {}) if isinstance(req, dict) else {}       # {layer name: the plane's net}
    pairs = set(req.get("pairs", [])) if isinstance(req, dict) else set()  # judged by the pair width
    old = set()                       # the base board's copper: only what a router added is judged
    if isinstance(req, dict) and req.get("base"):
        _p, base = load(req["base"])
        old = {track_sig(x, pcbnew) for x in base.GetTracks()}
    if "*" in nets:                                     # every net with copper
        nets = {t.GetNetname() for t in b.GetTracks()}
    ns = b.GetDesignSettings().m_NetSettings
    smd = [] if isinstance(req, dict) and req.get("via_in_pad_ok") else \
        [p for p in b.GetPads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    bad = {}
    for t in b.GetTracks():
        n = t.GetNetname()
        if n not in nets or n in bad or (old and track_sig(t, pcbnew) in old):
            continue
        lay = b.GetLayerName(t.GetLayer())
        if t.Type() != pcbnew.PCB_VIA_T and lay in planes and planes[lay] != n:
            bad[n] = f"track on {lay}, the {planes[lay]} plane (it would cut the plane)"
            continue
        nc = ns.GetEffectiveNetClass(n)
        tol = 1000                                      # 1 um: file rounding
        if t.Type() == pcbnew.PCB_VIA_T:
            if t.GetWidth(t.TopLayer()) + tol < nc.GetViaDiameter() or t.GetDrillValue() + tol < nc.GetViaDrill():
                bad[n] = (f"via {pcbnew.ToMM(t.GetWidth(t.TopLayer())):.3f}/{pcbnew.ToMM(t.GetDrillValue()):.3f} mm "
                          f"under its class {pcbnew.ToMM(nc.GetViaDiameter()):.3f}/{pcbnew.ToMM(nc.GetViaDrill()):.3f}")
                continue
            # a via in an SMD pad needs a filled, capped via at the fab, or solder wicks into it
            r = t.GetWidth(t.TopLayer()) // 2
            pad = next((p for p in smd if p.HitTest(t.GetPosition(), r)), None)
            if pad is not None:
                bad[n] = f"via in pad {pad.GetParentFootprint().GetReference()}.{pad.GetNumber()}"
            continue
        want = nc.GetDiffPairWidth() if n in pairs and nc.HasDiffPairWidth() else nc.GetTrackWidth()
        if t.GetWidth() + tol < want and not neck_down(b, pcbnew, t, want):
            bad[n] = f"track {pcbnew.ToMM(t.GetWidth()):.3f} mm under its class {pcbnew.ToMM(want):.3f}"
    print(json.dumps(bad))
    return 0


def cmd_planes(a):
    """{"planes": {inner layer: net}, "copper": [copper layers in stack order]}. A plane layer is an inner layer
    where one zone's outline covers at least half of the board's outline box: the designer's plane, which the
    routers must not cut up with signal tracks (Freerouting cut a third out of kit-dev's GND and +3.3V planes)."""
    pcbnew, b = load(a[0])
    box = b.GetBoardEdgesBoundingBox()
    board = float(box.GetWidth()) * float(box.GetHeight())
    stack = list(b.GetEnabledLayers().CuStack())
    copper = [b.GetLayerName(l) for l in stack]                    # the board's own names (the DSN uses these)
    standard = [b.GetStandardLayerName(l) for l in stack]          # F.Cu, In1.Cu ... (KiCadRoutingTools uses these)
    planes = {}
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() <= 0 or board <= 0:
            continue
        for layer in z.GetLayerSet().Seq():
            name = b.GetLayerName(layer)
            if name in (copper[0], copper[-1]) or name not in copper:
                continue
            if z.Outline().Area() >= 0.5 * board:
                planes[name] = z.GetNetname()
    smd = [p for p in b.GetPads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    vip = sum(1 for v in b.GetTracks() if v.Type() == pcbnew.PCB_VIA_T
              and any(p.HitTest(v.GetPosition(), v.GetWidth(v.TopLayer()) // 2) for p in smd))
    print(json.dumps({"planes": planes, "copper": copper, "standard": standard, "via_in_pad": vip}))
    return 0


def cmd_textguard(a):
    """Copy of the board where every board-level text on a copper layer gets a keep-out (no tracks, no vias)
    over its outline. KiCadRoutingTools and Freerouting route over copper text, which KiCad's DRC then rejects
    as a short; the keep-outs live only in the routers' working copy (merge takes tracks and vias only)."""
    pcbnew, b = load(a[0])
    # the nets no router may move (a json list, optional): their copper is locked in this copy
    frozen = set(json.loads(open(a[2], encoding="utf-8").read())) if len(a) > 2 else set()
    locked = 0
    for t in b.GetTracks():
        if t.GetNetname() in frozen and not t.IsLocked():
            t.SetLocked(True)
            locked += 1
    n = 0
    for d in list(b.GetDrawings()):
        if d.Type() not in (pcbnew.PCB_TEXT_T, pcbnew.PCB_TEXTBOX_T) or not pcbnew.IsCopperLayer(d.GetLayer()):
            continue
        box = d.GetBoundingBox()
        z = pcbnew.ZONE(b)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowTracks(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowZoneFills(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetLayer(d.GetLayer())
        o = z.Outline()
        o.NewOutline()
        for x, y in ((box.GetLeft(), box.GetTop()), (box.GetRight(), box.GetTop()),
                     (box.GetRight(), box.GetBottom()), (box.GetLeft(), box.GetBottom())):
            o.Append(x, y)
        b.Add(z)
        n += 1
    b.Save(a[1])
    print(json.dumps({"guarded": n, "locked": locked}))
    return 0


def track_sig(t, pcbnew):
    """A track or via's place and size, to 1 um: the same item on two boards has the same signature."""
    via = t.Type() == pcbnew.PCB_VIA_T
    s, e = t.GetStart(), t.GetEnd()
    return (via, t.GetLayer(), round(s.x / 1000), round(s.y / 1000), round(e.x / 1000), round(e.y / 1000),
            round((t.GetWidth(t.TopLayer()) if via else t.GetWidth()) / 1000))


def cmd_moved(a):
    """The nets, other than the listed ones, whose copper differs between the base board and a router's result:
    a router that moves another net's tracks out of the way (the plane repair does) must have those moves merged
    too, or its new copper lands on the old tracks."""
    pcbnew, base = load(a[0])
    _p, res = load(a[1])
    asked = set(json.loads(open(a[2], encoding="utf-8").read()))

    def sig(b):
        out = {}
        for t in b.GetTracks():
            out.setdefault(t.GetNetname(), set()).add(track_sig(t, pcbnew))
        return out
    sb, sr = sig(base), sig(res)
    print(json.dumps(sorted(n for n in set(sb) | set(sr)
                            if n and n not in asked and sb.get(n, set()) != sr.get(n, set()))))
    return 0


def cmd_trim(a):
    """For the listed nets, remove each track narrower than its net class when it is a single-segment tap (both
    ends on a pad or via of its own net), so the rest of the net's new copper can stay; the tap's pad is then
    open again. Nets with any other undersized copper are reported "untrimmable" (the caller drops them).
    The plane repair necks its tap down to a fine-pitch pad's width (0.3 mm against kit-dev's 0.4 mm class)."""
    pcbnew, b = load(a[0])
    nets = set(json.loads(open(a[2], encoding="utf-8").read()))
    ns = b.GetDesignSettings().m_NetSettings
    tol = 1000

    def anchored(p, net, me):
        for pad in b.GetPads():
            if pad.GetNetname() == net and pad.HitTest(p):
                return True
        return any(v is not me and v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == net and v.HitTest(p)
                   for v in b.GetTracks())
    cut, untrim = {}, set()
    for t in list(b.GetTracks()):
        n = t.GetNetname()
        if n not in nets or n in untrim:
            continue
        nc = ns.GetEffectiveNetClass(n)
        if t.Type() == pcbnew.PCB_VIA_T:
            if t.GetWidth(t.TopLayer()) + tol < nc.GetViaDiameter() or t.GetDrillValue() + tol < nc.GetViaDrill():
                untrim.add(n)
        elif t.GetWidth() + tol < nc.GetTrackWidth():
            if anchored(t.GetStart(), n, t) and anchored(t.GetEnd(), n, t):
                cut.setdefault(n, []).append(t)
            else:
                untrim.add(n)
    done = {}
    for n, ts in cut.items():
        if n in untrim:
            continue
        for t in ts:
            b.Remove(t)
        done[n] = len(ts)
    b.Save(a[1])
    print(json.dumps({"trimmed": done, "untrimmable": sorted(untrim)}))
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
    cmds = {"dsn": cmd_dsn, "ses": cmd_ses, "merge": cmd_merge, "copper": cmd_copper, "open": cmd_open, "rules": cmd_rules, "near": cmd_near, "refill": cmd_refill, "zones": cmd_zones, "audit": cmd_audit, "planes": cmd_planes, "textguard": cmd_textguard, "moved": cmd_moved, "trim": cmd_trim}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
