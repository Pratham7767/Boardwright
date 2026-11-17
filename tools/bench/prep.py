"""Prepare a benchmark copy (run with KiCad's Python: python.exe -I prep.py <folder> <task.json>).

Applies a task's 'prep' steps to the single *.kicad_pcb in <folder> and saves it.
Steps: unroute [nets], unroute_part REF, move {ref, x, y}, stray_track {net, layer, from, to, width}.
"""
import glob
import json
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
    folder, task_file = sys.argv[1], sys.argv[2]
    task = json.loads(open(task_file, encoding="utf-8-sig").read())
    pcb = glob.glob(os.path.join(folder, "*.kicad_pcb"))[0]
    b = pcbnew.LoadBoard(pcb)
    # Removing items leaves KiCad's Python wrappers stale, so every removal is decided first and done last.
    remove = []
    steps = task.get("prep", [])
    for step in steps:
        if "unroute" in step:
            names = set(step["unroute"])
            remove += [t for t in b.GetTracks() if t.GetNetname() in names]
        if "unroute_part" in step:
            fp = fp_by_ref(b, step["unroute_part"])
            nets = {p.GetNetname() for p in fp.Pads()}
            pads = [p for p in fp.Pads()]
            remove += [t for t in b.GetTracks() if t.GetNetname() in nets
                       and any(p.HitTest(t.GetStart()) or p.HitTest(t.GetEnd()) for p in pads)]
    for step in steps:
        if "move" in step:
            m = step["move"]
            fp = fp_by_ref(b, m["ref"])
            fp.SetPosition(pcbnew.VECTOR2I(int(m["x"] * MM), int(m["y"] * MM)))
        if "stray_track" in step:
            s = step["stray_track"]
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(pcbnew.VECTOR2I(int(s["from"][0] * MM), int(s["from"][1] * MM)))
            t.SetEnd(pcbnew.VECTOR2I(int(s["to"][0] * MM), int(s["to"][1] * MM)))
            t.SetWidth(int(s["width"] * MM))
            t.SetLayer(b.GetLayerID(s["layer"]))
            t.SetNet(b.FindNet(s["net"]))
            b.Add(t)
    for t in remove:
        b.Remove(t)
    b.Save(pcb)
    print("prepared", os.path.basename(pcb))


if __name__ == "__main__":
    main()
