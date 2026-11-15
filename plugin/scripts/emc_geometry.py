"""Geometry metrics for the EMC review (read-only).

Run with KiCad's bundled Python:
    <kicad>/bin/python.exe -I emc_geometry.py <project_dir>

Reads <project_dir>/boardwright.json ("emc" section) and the single *.kicad_pcb in project_dir.
The board is loaded and zones are refilled IN MEMORY only; nothing is saved.

Entries: loops (shoelace area through pad centres in order), net_copper (exact union area of pads and
tracks, summed over layers), net_distance, pad_distance, track_length, edge_clearance.
A referenced footprint, pad or net that does not exist is a setup error (exit 2), never skipped.
Exit 1 only if a row with severity CRITICAL fails; HIGH/MEDIUM/LOW are reported.
"""
import glob
import json
import math
import os
import sys

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

MM = 1e6
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
HEADER = "Geometry estimates from pad centres and copper outlines; not a field solver, not a compliance result."


def die(msg):
    print("SETUP ERROR: " + msg)
    sys.exit(2)


if len(sys.argv) != 2:
    die("usage: emc_geometry.py <project_dir>")
PROJ = os.path.abspath(sys.argv[1])
if not os.path.isdir(PROJ):
    die("not a directory: " + PROJ)
pcbs = glob.glob(os.path.join(PROJ, "*.kicad_pcb"))
if len(glob.glob(os.path.join(PROJ, "*.kicad_pro"))) != 1:
    die("expected exactly one *.kicad_pro in " + PROJ)
if len(pcbs) != 1:
    die(f"expected exactly one *.kicad_pcb in {PROJ}, found {len(pcbs)}")
CFG_PATH = os.path.join(PROJ, "boardwright.json")
if not os.path.isfile(CFG_PATH):
    die("missing " + CFG_PATH)
try:
    CFG = json.load(open(CFG_PATH, encoding="utf-8"))
except ValueError as e:
    die(f"cannot parse {CFG_PATH}: {e}")
EC = CFG.get("emc")
if not isinstance(EC, dict):
    die("no 'emc' section in boardwright.json")

import pcbnew  # noqa: E402  (only available in KiCad's Python)

B = pcbnew.LoadBoard(pcbs[0])
pcbnew.ZONE_FILLER(B).Fill(B.Zones())     # in memory only; never saved
ERR = B.GetDesignSettings().m_MaxError
COPPER = [L for L in B.GetEnabledLayers().CuStack()]


def sev(entry):
    s = entry.get("severity")
    if s not in SEVERITIES:
        die(f"entry {entry.get('id')}: severity must be one of {SEVERITIES}, got {s!r}")
    return s


def need(entry, *keys):
    for k in keys:
        if k not in entry:
            die(f"entry {entry.get('id', entry)}: missing key '{k}'")


def pad_obj(spec):
    ref, _, num = str(spec).partition(".")
    fp = B.FindFootprintByReference(ref)
    if fp is None:
        die(f"footprint '{ref}' (from '{spec}') does not exist on the board")
    for p in fp.Pads():
        if p.GetNumber() == num:
            return p
    die(f"pad '{spec}' does not exist (footprint {ref} has pads {sorted(p.GetNumber() for p in fp.Pads())})")


def pad_xy(spec):
    q = pad_obj(spec).GetPosition()
    return (q.x / MM, q.y / MM)


def check_nets(nets, where):
    for n in nets:
        if B.FindNet(n) is None:
            die(f"{where}: net '{n}' does not exist on the board")


def loop_area(points):
    s = 0.0
    nxt = points[1:] + points[:1]
    for (x1, y1), (x2, y2) in zip(points, nxt):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2, sum(math.dist(a, b) for a, b in zip(points, nxt))


def net_area(net):
    tot = 0.0
    for L in COPPER:
        ps = pcbnew.SHAPE_POLY_SET()
        for t in B.GetTracks():
            if t.GetNetname() == net and t.IsOnLayer(L):
                t.TransformShapeToPolygon(ps, L, 0, ERR, pcbnew.ERROR_INSIDE)
        for fp in B.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() == net and p.IsOnLayer(L):
                    p.TransformShapeToPolygon(ps, L, 0, ERR, pcbnew.ERROR_INSIDE)
        ps.Simplify()
        tot += ps.Area() / MM ** 2
    return tot


def shapes(nets):
    out = []
    for t in B.GetTracks():
        if t.GetNetname() in nets:
            q = t.GetPosition() if t.GetClass() == "PCB_VIA" else t.GetStart()
            kind = "via" if t.GetClass() == "PCB_VIA" else "track"
            for L in COPPER:
                if t.IsOnLayer(L):
                    out.append((L, t.GetEffectiveShape(L), f"{kind} {t.GetNetname()} @{q.x/MM:.1f},{q.y/MM:.1f}"))
    for fp in B.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() in nets:
                for L in COPPER:
                    if p.IsOnLayer(L):
                        out.append((L, p.GetEffectiveShape(L), f"{fp.GetReference()}.{p.GetNumber()}"))
    return out


def bisect(sa, sb, hi_mm):
    """Distance between two shapes in mm, capped at hi_mm."""
    if sa.Collide(sb, 0):
        return 0.0
    lo, hi = 0, int(hi_mm * MM)
    if not sa.Collide(sb, hi):
        return hi_mm
    while hi - lo > 100:
        m = (lo + hi) // 2
        if sa.Collide(sb, m):
            hi = m
        else:
            lo = m
    return hi / MM


def min_dist(A, Bs, same_layer, hi_mm=30.0):
    best = (hi_mm, "none within %g mm" % hi_mm, "")
    for la, sa, na in A:
        ba = sa.BBox()
        for lb, sb, nb in Bs:
            if same_layer and la != lb:
                continue
            bb = sb.BBox()
            dx = max(ba.GetLeft() - bb.GetRight(), bb.GetLeft() - ba.GetRight(), 0)
            dy = max(ba.GetTop() - bb.GetBottom(), bb.GetTop() - ba.GetBottom(), 0)
            if math.hypot(dx, dy) / MM >= best[0]:
                continue
            d = bisect(sa, sb, best[0])
            if d < best[0]:
                best = (d, na, nb)
    return best


ROWS = []


def row(i, name, measured, unit, limit, ok, severity, detail=""):
    ROWS.append({"id": i, "item": name, "measured": round(measured, 3), "unit": unit, "limit": limit,
                 "result": "ok" if ok else severity, "severity_if_fail": severity, "detail": detail})


# loops
for e in EC.get("loops", []):
    need(e, "id", "pads", "max_mm2", "severity")
    s = sev(e)
    if len(e["pads"]) < 3:
        die(f"loop {e['id']}: needs at least 3 pads")
    a, p = loop_area([pad_xy(x) for x in e["pads"]])
    row(e["id"], e.get("name", "loop"), a, "mm2", f"<= {e['max_mm2']} mm2", a <= e["max_mm2"], s,
        f"perimeter {p:.0f} mm; pads {' > '.join(e['pads'])}")

# net copper
for e in EC.get("net_copper", []):
    need(e, "id", "net", "max_mm2", "severity")
    s = sev(e)
    check_nets([e["net"]], e["id"])
    a = net_area(e["net"])
    row(e["id"], e.get("name", f"{e['net']} copper (pads + tracks, all layers)"), a, "mm2",
        f"<= {e['max_mm2']} mm2", a <= e["max_mm2"], s)

# net distance
for e in EC.get("net_distance", []):
    need(e, "id", "a", "b", "min_mm", "severity")
    s = sev(e)
    check_nets(e["a"] + e["b"], e["id"])
    sl = bool(e.get("same_layer", True))
    A, Bs = shapes(set(e["a"])), shapes(set(e["b"]))
    if not A or not Bs:
        die(f"{e['id']}: one side of the net_distance has no copper")
    d = min_dist(A, Bs, sl)
    row(e["id"], e.get("name", "net distance"), d[0], "mm", f">= {e['min_mm']} mm", d[0] >= e["min_mm"], s,
        f"{d[1]} - {d[2]}; {'same layer' if sl else 'any layer'}")

# pad distance
for e in EC.get("pad_distance", []):
    need(e, "id", "a", "b", "max_mm", "severity")
    s = sev(e)
    d = math.dist(pad_xy(e["a"]), pad_xy(e["b"]))
    row(e["id"], e.get("name", f"{e['a']} to {e['b']}"), d, "mm", f"<= {e['max_mm']} mm", d <= e["max_mm"], s,
        "centre to centre")

# track length (+ optional clearance of that net from other nets)
for e in EC.get("track_length", []):
    need(e, "id", "net", "max_mm", "severity")
    s = sev(e)
    check_nets([e["net"]] + e.get("clear_of", []), e["id"])
    ln = sum(t.GetLength() for t in B.GetTracks() if t.GetNetname() == e["net"] and t.GetClass() != "PCB_VIA") / MM
    ok, detail, limit = ln <= e["max_mm"], "", f"<= {e['max_mm']} mm"
    if e.get("clear_of"):
        need(e, "clear_min_mm")
        d = min_dist(shapes({e["net"]}), shapes(set(e["clear_of"])), False)
        ok = ok and d[0] >= e["clear_min_mm"]
        detail = f"closest {d[0]:.1f} mm to {d[2]} (need >= {e['clear_min_mm']} mm)"
        limit += f"; clear >= {e['clear_min_mm']} mm"
    row(e["id"], e.get("name", f"{e['net']} track length"), ln, "mm", limit, ok, s, detail)

# edge clearance: copper track/via to Edge.Cuts
ed = EC.get("edge_clearance")
if ed:
    need(ed, "id", "min_mm", "severity")
    s = sev(ed)
    edge = [(d.GetEffectiveShape(), d) for d in B.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    edge += [(g.GetEffectiveShape(), g) for f in B.GetFootprints() for g in f.GraphicalItems()
             if g.GetLayer() == pcbnew.Edge_Cuts]
    if not edge:
        die("edge_clearance: the board has no Edge.Cuts outline")
    best = (1e9, "", 0, 0)
    for t in B.GetTracks():
        isvia = t.GetClass() == "PCB_VIA"
        for L in COPPER:
            if not t.IsOnLayer(L):
                continue
            st = t.GetEffectiveShape(L)
            for es, _ in edge:
                d = bisect(st, es, min(best[0], 50.0)) if best[0] > 0 else 0.0
                if d < best[0]:
                    q = t.GetPosition() if isvia else t.GetStart()
                    best = (d, ("via " if isvia else "track ") + t.GetNetname() + f" ({B.GetLayerName(L)})",
                            q.x / MM, q.y / MM)
    if best[0] > 1e8:
        die("edge_clearance: no track or via found")
    row(ed["id"], ed.get("name", "Closest track edge to board edge (Edge.Cuts)"), best[0], "mm",
        f">= {ed['min_mm']} mm", best[0] >= ed["min_mm"], s,
        f"{best[1]} near {best[2]:.1f},{best[3]:.1f}")

# output
print(f"# EMC geometry: {os.path.basename(pcbs[0])}")
print(f"\n{HEADER}\n")
print("| ID | Item | Measured | Limit | Result | Detail |")
print("|---|---|---|---|---|---|")
for r in ROWS:
    print(f"| {r['id']} | {r['item']} | {r['measured']:g} {r['unit']} | {r['limit']} | "
          f"{r['result']} | {r['detail']} |")
fails = [r for r in ROWS if r["result"] == "CRITICAL"]
counts = {k: sum(1 for r in ROWS if r["result"] == k) for k in SEVERITIES}
print(f"\nRows: {len(ROWS)}; ok: {sum(1 for r in ROWS if r['result'] == 'ok')}; "
      + ", ".join(f"{k}: {v}" for k, v in counts.items()))
print("Gate (no CRITICAL): " + ("FAIL" if fails else "PASS"))

os.makedirs(os.path.join(PROJ, "reports"), exist_ok=True)
with open(os.path.join(PROJ, "reports", "emc-geometry.json"), "w", encoding="utf-8") as f:
    json.dump({"board": os.path.basename(pcbs[0]), "disclaimer": HEADER, "rows": ROWS,
               "gate_no_critical": not fails}, f, indent=1)
sys.exit(1 if fails else 0)
