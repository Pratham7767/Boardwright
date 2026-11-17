"""Check a benchmark run (run with KiCad's Python: python.exe -I check.py <folder> <task.json> <drc.json> <base_errors>).

Prints one JSON line: {"pass": bool, "why": [...], "drc_errors": n, "unconnected": n}.
DRC: no more errors than the untouched board (base_errors), and nothing unconnected.
"""
import glob
import json
import math
import os
import sys

import pcbnew

MM = 1e6


def fp_by_ref(b, ref):
    for fp in b.GetFootprints():
        if fp.GetReference() == ref:
            return fp
    raise SystemExit('no footprint ' + ref)


def main():
    folder, task_file, drc_file, base = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    task = json.loads(open(task_file, encoding="utf-8-sig").read())
    why = []
    pcb = glob.glob(os.path.join(folder, "*.kicad_pcb"))[0]
    b = pcbnew.LoadBoard(pcb)
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    c = task["check"]
    for p in c.get("pose", []):
        fp = fp_by_ref(b, p["ref"])
        pos = fp.GetPosition()
        if abs(pos.x / MM - p["x"]) > 0.01 or abs(pos.y / MM - p["y"]) > 0.01:
            why.append(f"{p['ref']} at ({pos.x / MM:.3f}, {pos.y / MM:.3f})")
        rot = fp.GetOrientationDegrees() % 360
        if abs(rot - p["rot"] % 360) > 0.1:
            why.append(f"{p['ref']} rotated {rot}")
    if "netclass" in c:
        n = c["netclass"]
        pro = json.loads(open(glob.glob(os.path.join(folder, "*.kicad_pro"))[0], encoding="utf-8").read())
        ns = pro.get("net_settings", {})
        cls = [k for k in ns.get("classes", []) if k.get("name") == n["name"]]
        if not cls:
            why.append("no class " + n["name"])
        else:
            k = cls[0]
            if abs(k.get("track_width", 0) - n["track_width"]) > 1e-6 or abs(k.get("clearance", 0) - n["clearance"]) > 1e-6:
                why.append(f"class values {k.get('track_width')} / {k.get('clearance')}")
        import fnmatch
        pats = ns.get("netclass_patterns") or []
        assigned = ns.get("netclass_assignments") or {}
        for net in n["nets"]:
            ok = any(fnmatch.fnmatchcase(net, x.get("pattern", "")) and x.get("netclass") == n["name"] for x in pats)
            ok = ok or assigned.get(net) == n["name"] or n["name"] in (assigned.get(net) or [])
            if not ok:
                why.append(net + " not in " + n["name"])
    for net in c.get("routed", []):
        code = b.FindNet(net).GetNetCode()
        if not any(t.GetNetCode() == code for t in b.GetTracks()):
            why.append(net + " has no tracks")
    if "near_pin" in c:
        q = c["near_pin"]
        fp = fp_by_ref(b, q["ref"])
        pad = fp.FindPadByNumber(q["pad"])
        u1 = [p for p in fp_by_ref(b, "U1").Pads() if p.GetNetCode() == pad.GetNetCode()]
        if not fp.IsOnLayer(pcbnew.F_Cu):
            why.append(q["ref"] + " not on front")
        cen = fp.GetPosition()
        d = min(math.hypot((p.GetPosition().x - cen.x) / MM, (p.GetPosition().y - cen.y) / MM) for p in u1) if u1 else 99
        if d > q["max_mm"]:
            why.append(f"{q['ref']} is {d:.2f} mm from the nearest U1 pad on its net")
    if "routed_part" in c:
        fp = fp_by_ref(b, c["routed_part"])
        for p in fp.Pads():
            if p.GetNetCode() and not any(t.GetNetCode() == p.GetNetCode() and (p.HitTest(t.GetStart()) or p.HitTest(t.GetEnd()))
                                          for t in b.GetTracks()) and p.GetNetname() != "/GND":
                why.append(f"{c['routed_part']}.{p.GetNumber()} has no track")
    if "no_stray" in c:
        s = c["no_stray"]
        for t in b.GetTracks():
            if (t.GetNetname() == s["net"] and abs(t.GetStart().x / MM - s["from"][0]) < 0.01
                    and abs(t.GetStart().y / MM - s["from"][1]) < 0.01):
                why.append("stray track still there")
    drc = json.loads(open(drc_file, encoding="utf-8-sig").read())
    errors = sum(1 for v in drc.get("violations", []) if v.get("severity") == "error")
    uncon = len(drc.get("unconnected_items", []))
    if errors > base:
        why.append(f"DRC errors {errors} > {base}")
    if uncon:
        why.append(f"{uncon} unconnected")
    del conn
    print(json.dumps({"pass": not why, "why": why, "drc_errors": errors, "unconnected": uncon}))


if __name__ == "__main__":
    main()
