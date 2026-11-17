"""Compact text digest of a KiCad board (read-only, token-saving).

Run with KiCad's bundled Python:
    <kicad>/bin/python.exe -I board_digest.py <project_dir> [--section SECTION [ARGS]]

SECTION (default summary):
    all | summary | parts | nets | unrouted | near REF [MM=10] | net NAME | area X1 Y1 X2 Y2

Plain text, mm with at most 2 decimals, one item per line, one legend line per section.
The board is loaded from the single *.kicad_pcb in project_dir and is never saved; zones are
NOT refilled (stored fills are used), so connectivity can differ from a DRC run after edits.
Y grows downward as in KiCad (N = smaller y).
Exit 0 ok, 2 setup problem or unknown REF / net / bad arguments.
"""
import fnmatch
import glob
import json
import math
import os
import re
import sys

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

MM = 1e6
SECTIONS = ("all", "summary", "parts", "nets", "unrouted", "near", "net", "area")


def die(msg):
    print("ERROR: " + msg)
    sys.exit(2)


def usage():
    die("usage: board_digest.py <project_dir> [--section all|summary|parts|nets|unrouted|"
        "near REF [MM]|net NAME|area X1 Y1 X2 Y2]")


# ------------------------------------------------------------------ arguments
argv = sys.argv[1:]
if not argv or argv[0].startswith("--"):
    usage()
PROJ = os.path.abspath(argv[0])
rest = argv[1:]
if rest and rest[0] == "--section":
    rest = rest[1:]
SEC = rest[0] if rest else "summary"
SARGS = rest[1:]
if SEC not in SECTIONS:
    usage()
if not os.path.isdir(PROJ):
    die("not a directory: " + PROJ)
if SEC == "near" and not 1 <= len(SARGS) <= 2:
    usage()
if SEC == "net" and len(SARGS) != 1:
    usage()
if SEC == "area" and len(SARGS) != 4:
    usage()
try:
    NEAR_MM = float(SARGS[1]) if SEC == "near" and len(SARGS) == 2 else 10.0
    AREA = [float(a) for a in SARGS] if SEC == "area" else None
except ValueError:
    usage()

pcbs = glob.glob(os.path.join(PROJ, "*.kicad_pcb"))
if len(pcbs) != 1:
    die(f"expected exactly one *.kicad_pcb in {PROJ}, found {len(pcbs)}")
pros = glob.glob(os.path.join(PROJ, "*.kicad_pro"))

if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    import kicad_python  # under any Python: rerun with KiCad's own, which has pcbnew
    kicad_python.ensure(__file__)
import pcbnew  # noqa: E402  (only available in KiCad's Python)

B = pcbnew.LoadBoard(pcbs[0])
B.BuildConnectivity()
CONN = B.GetConnectivity()
F_CU, B_CU = pcbnew.F_Cu, pcbnew.B_Cu
LNAME = {}


# --------------------------------------------------------------------- helpers
def mm(v):
    return v / MM


def f(x):
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def lname(layer):
    if layer not in LNAME:
        LNAME[layer] = B.GetLayerName(layer)
    return LNAME[layer]


def nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def tok(s):
    return str(s).replace(" ", "_")


def side(fp):
    return "F" if fp.GetLayer() == F_CU else "B"


def pad_layers(p):
    f_, b_ = p.IsOnLayer(F_CU), p.IsOnLayer(B_CU)
    return "FB" if f_ and b_ else ("F" if f_ else ("B" if b_ else "-"))


def is_via(t):
    return t.Type() == pcbnew.PCB_VIA_T


def pad_id(p):
    return f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}"


def fp_bbox(fp):
    r = fp.GetBoundingBox(False)
    return (mm(r.GetLeft()), mm(r.GetTop()), mm(r.GetRight()), mm(r.GetBottom()))


def rect_of(item):
    r = item.GetBoundingBox()
    return (mm(r.GetLeft()), mm(r.GetTop()), mm(r.GetRight()), mm(r.GetBottom()))


def rect_gap(a, b):
    """Edge-to-edge distance between two rectangles and the direction from a to b."""
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    if dx >= dy and dx > 0:
        d = "E" if b[0] >= a[2] else "W"
    elif dy > 0:
        d = "S" if b[1] >= a[3] else "N"
    else:
        d = "-"
    return math.hypot(dx, dy), d


def seg_rect_dist(x1, y1, x2, y2, r):
    """Distance from segment to rectangle (0 if they touch or overlap)."""
    def clip():       # Liang-Barsky: does the segment intersect the rectangle?
        t0, t1 = 0.0, 1.0
        dx, dy = x2 - x1, y2 - y1
        for p, q in ((-dx, x1 - r[0]), (dx, r[2] - x1), (-dy, y1 - r[1]), (dy, r[3] - y1)):
            if p == 0:
                if q < 0:
                    return False
            else:
                t = q / p
                if p < 0:
                    if t > t1:
                        return False
                    t0 = max(t0, t)
                else:
                    if t < t0:
                        return False
                    t1 = min(t1, t)
        return True
    if clip():
        return 0.0
    best = min(pt_rect_dist(x1, y1, r), pt_rect_dist(x2, y2, r))
    for cx, cy in ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])):
        best = min(best, pt_seg_dist(cx, cy, x1, y1, x2, y2))
    return best


def pt_rect_dist(x, y, r):
    return math.hypot(max(r[0] - x, x - r[2], 0.0), max(r[1] - y, y - r[3], 0.0))


def pt_seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def trk_pts(t):
    s, e = t.GetStart(), t.GetEnd()
    return mm(s.x), mm(s.y), mm(e.x), mm(e.y)


def trk_width(t):
    return mm(t.GetWidth(F_CU)) if is_via(t) else mm(t.GetWidth())


# -------------------------------------------------------------- netclass lookup
PATTERNS, CLASSES = [], []
if len(pros) == 1:
    try:
        _ns = json.load(open(pros[0], encoding="utf-8")).get("net_settings") or {}
        PATTERNS = [(p.get("pattern", ""), p.get("netclass", "")) for p in _ns.get("netclass_patterns") or []]
        CLASSES = [c.get("name") for c in _ns.get("classes") or [] if c.get("name")]
    except (OSError, ValueError):
        pass


def net_class(name):
    bare = name.lstrip("/")
    for pat, cls in PATTERNS:
        pb = pat.lstrip("/")
        if fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(bare, pat) or fnmatch.fnmatchcase(bare, pb):
            return cls
    return "Default"


# --------------------------------------------------------------------- indexes
FPS = sorted(B.GetFootprints(), key=lambda x: nat(x.GetReference()))
TRACKS = list(B.GetTracks())
NETNAMES = {}
for _name, _n in B.GetNetInfo().NetsByName().items():
    if _n.GetNetCode() > 0 and str(_name):
        NETNAMES[str(_name)] = _n.GetNetCode()
PADS_BY_NET = {}
for _p in B.GetPads():
    if _p.GetNetname():
        PADS_BY_NET.setdefault(_p.GetNetname(), []).append(_p)
for _l in PADS_BY_NET.values():
    _l.sort(key=lambda p: nat(pad_id(p)))
TRK_BY_NET = {}
for _t in TRACKS:
    TRK_BY_NET.setdefault(_t.GetNetname(), []).append(_t)
OUT = B.GetBoardEdgesBoundingBox()
OUTR = (mm(OUT.GetLeft()), mm(OUT.GetTop()), mm(OUT.GetRight()), mm(OUT.GetBottom()))


def find_fp(ref):
    for fp in FPS:
        if fp.GetReference() == ref:
            return fp
    die(f"no footprint with reference '{ref}' (board has {len(FPS)} footprints)")


def find_net(name):
    for cand in (name, "/" + name, name.lstrip("/")):
        if cand in NETNAMES:
            return cand
    die(f"no net named '{name}' ({len(NETNAMES)} nets)")


def courtyard(fp):
    cy = fp.GetCourtyard(pcbnew.F_CrtYd if fp.GetLayer() == F_CU else pcbnew.B_CrtYd)
    if cy.OutlineCount() == 0:
        return None
    bb = cy.BBox()
    return mm(bb.GetWidth()), mm(bb.GetHeight())


def length_of(tracks):
    return sum(mm(t.GetLength()) for t in tracks if not is_via(t))


# --------------------------------------------------------------------- unrouted
def unrouted_pairs():
    """Cluster each net's pads by copper connectivity, then join clusters nearest-first (MST)."""
    pairs = []
    for net, pads in PADS_BY_NET.items():
        if len(pads) < 2:
            continue
        key = {}
        for p in pads:
            key[p.m_Uuid.AsString()] = p
        cl = {}                                  # pad uuid -> cluster id
        groups = []
        for p in pads:
            u = p.m_Uuid.AsString()
            if u in cl:
                continue
            members = {u}
            for it in CONN.GetConnectedItems(p):
                if it.GetClass() == "PAD":
                    members.add(it.m_Uuid.AsString())
            # pads of one footprint sharing a number are one electrical node
            for q in pads:
                if pad_id(q) in {pad_id(key[m]) for m in members if m in key}:
                    members.add(q.m_Uuid.AsString())
            gid = len(groups)
            groups.append([key[m] for m in members if m in key])
            for m in members:
                cl.setdefault(m, gid)
        n = len(groups)
        if n < 2:
            continue
        parent = list(range(n))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        cand = []
        for i in range(n):
            for j in range(i + 1, n):
                best = None
                for a in groups[i]:
                    for b in groups[j]:
                        d = math.hypot(a.GetPosition().x - b.GetPosition().x,
                                       a.GetPosition().y - b.GetPosition().y)
                        if best is None or d < best[0]:
                            best = (d, a, b)
                cand.append((best[0], i, j, best[1], best[2]))
        cand.sort(key=lambda c: c[0])
        for d, i, j, a, b in cand:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
                pairs.append((mm(d), net, pad_id(a), pad_id(b)))
    pairs.sort(key=lambda x: -x[0])
    return pairs


def unrouted_count():
    try:
        return int(CONN.GetUnconnectedCount(False))
    except Exception:
        return None


# --------------------------------------------------------------------- sections
def sec_summary():
    out = ["# summary (mm)"]
    out.append(f"outline bbox: ({f(OUTR[0])},{f(OUTR[1])})-({f(OUTR[2])},{f(OUTR[3])}) "
               f"size {f(OUTR[2] - OUTR[0])} x {f(OUTR[3] - OUTR[1])}")
    out.append(f"copper layers: {B.GetCopperLayerCount()}")
    nf = sum(1 for x in FPS if x.GetLayer() == F_CU)
    tht = sum(1 for x in FPS if x.GetAttributes() & pcbnew.FP_THROUGH_HOLE)
    smd = sum(1 for x in FPS if x.GetAttributes() & pcbnew.FP_SMD)
    out.append(f"footprints: {len(FPS)} (front {nf}, back {len(FPS) - nf}; THT {tht}, SMD {smd}, "
               f"other {len(FPS) - tht - smd})")
    vias = sum(1 for t in TRACKS if is_via(t))
    zones = [z for z in B.Zones()]
    out.append(f"tracks: {len(TRACKS) - vias}  vias: {vias}  zones: {len(zones)}  "
               f"track length: {f(length_of(TRACKS))}")
    out.append(f"nets: {len(NETNAMES)}")
    n = unrouted_count()
    out.append(f"unrouted: {n if n is not None else 'unknown'}")
    counts = {}
    for name in NETNAMES:
        c = net_class(name)
        counts[c] = counts.get(c, 0) + 1
    out.append(f"netclasses ({len(PATTERNS)} patterns, {len(CLASSES)} defined): " +
               (" ".join(f"{c}={counts[c]}" for c in sorted(counts)) or "none"))
    outside, nocy = [], []
    for fp in FPS:
        r = fp_bbox(fp)
        if r[0] < OUTR[0] or r[1] < OUTR[1] or r[2] > OUTR[2] or r[3] > OUTR[3]:
            outside.append(fp.GetReference())
        if courtyard(fp) is None:
            nocy.append(fp.GetReference())
    out.append(f"outside outline bbox: {fmt_refs(outside)}")
    out.append(f"no courtyard: {fmt_refs(nocy)}")
    return out


def fmt_refs(refs, cap=15):
    if not refs:
        return "none"
    return " ".join(refs[:cap]) + (f" +{len(refs) - cap}" if len(refs) > cap else "")


def sec_parts():
    out = ["# parts: ref value footprint layer x y rot pads courtyardWxH"]
    for fp in FPS:
        c = courtyard(fp)
        pos = fp.GetPosition()
        out.append(" ".join([fp.GetReference(), tok(fp.GetValue())[:18] or "-",
                             tok(str(fp.GetFPID().GetLibItemName()))[:28], side(fp),
                             f(mm(pos.x)), f(mm(pos.y)), f(fp.GetOrientationDegrees()),
                             str(len(fp.Pads())), f"{f(c[0])}x{f(c[1])}" if c else "none"]))
    return out


def sec_nets():
    out = ["# nets: name class pads trackmm vias pads(ref.pin, max 8)"]
    for name in sorted(NETNAMES, key=nat):
        pads = PADS_BY_NET.get(name, [])
        if len(pads) < 2:
            continue
        trk = TRK_BY_NET.get(name, [])
        ids = [pad_id(p) for p in pads]
        shown = " ".join(ids[:8]) + (f" +{len(ids) - 8}" if len(ids) > 8 else "")
        out.append(f"{name} {net_class(name)} {len(pads)} {f(length_of(trk))} "
                   f"{sum(1 for t in trk if is_via(t))} {shown}")
    return out


def sec_unrouted():
    pairs = unrouted_pairs()
    n = unrouted_count()
    out = [f"# unrouted: {n if n is not None else 'unknown'} by connectivity API, "
           f"{len(pairs)} listed. net refA.pin -> refB.pin distance_mm"]
    for d, net, a, b in pairs[:80]:
        out.append(f"{net} {a} -> {b} {f(d)}")
    if len(pairs) > 80:
        out.append(f"+{len(pairs) - 80} more")
    return out


def sec_near():
    ref = SARGS[0]
    fp = find_fp(ref)
    r = fp_bbox(fp)
    mine = {p.GetNetname() for p in fp.Pads() if p.GetNetname()}
    out = [f"# near {ref} within {f(NEAR_MM)} mm of its bbox ({f(r[0])},{f(r[1])})-({f(r[2])},{f(r[3])}) "
           f"on {side(fp)}. parts: ref dist dir | copper: net layer dist (edge to edge)"]
    parts = []
    for o in FPS:
        if o is fp or o.GetReference() == ref:
            continue
        d, dr = rect_gap(r, fp_bbox(o))
        if d <= NEAR_MM:
            parts.append((d, o.GetReference(), dr))
    parts.sort(key=lambda x: (x[0], nat(x[1])))
    out.append(f"parts: {len(parts)}")
    out += [f"{ref_} {f(d)} {dr}" for d, ref_, dr in parts]
    best = {}
    for t in TRACKS:
        nn = t.GetNetname()
        if nn in mine:
            continue
        x1, y1, x2, y2 = trk_pts(t)
        hw = trk_width(t) / 2
        d = max(0.0, seg_rect_dist(x1, y1, x2, y2, r) - hw)
        if d > NEAR_MM:
            continue
        lay = "via" if is_via(t) else lname(t.GetLayer())
        k = (nn or "(no net)", lay)
        if k not in best or d < best[k]:
            best[k] = d
    items = sorted(best.items(), key=lambda kv: (kv[1], kv[0]))
    out.append(f"copper of other nets: {len(items)}")
    out += [f"{k[0]} {k[1]} {f(d)}" for k, d in items[:40]]
    if len(items) > 40:
        out.append(f"+{len(items) - 40} more")
    out.append("board edge (to outline bbox): " +
               f"N {f(r[1] - OUTR[1])} E {f(OUTR[2] - r[2])} S {f(OUTR[3] - r[3])} W {f(r[0] - OUTR[0])}")
    return out


def sec_net():
    name = find_net(SARGS[0])
    pads = PADS_BY_NET.get(name, [])
    trk = [t for t in TRK_BY_NET.get(name, []) if not is_via(t)]
    vias = [t for t in TRK_BY_NET.get(name, []) if is_via(t)]
    out = [f"# net {name} class {net_class(name)}. pads: ref.pin x y layers | tracks: layer width "
           f"x1 y1 -> x2 y2 len | vias: x y drill"]
    out.append(f"pads: {len(pads)}")
    for p in pads[:100]:
        pos = p.GetPosition()
        out.append(f"{pad_id(p)} {f(mm(pos.x))} {f(mm(pos.y))} {pad_layers(p)}")
    if len(pads) > 100:
        out.append(f"+{len(pads) - 100} more pads")
    out.append(f"tracks: {len(trk)}")
    for t in sorted(trk, key=lambda t: (t.GetLayer(), trk_pts(t))) [:150]:
        x1, y1, x2, y2 = trk_pts(t)
        out.append(f"{lname(t.GetLayer())} {f(trk_width(t))} {f(x1)} {f(y1)} -> {f(x2)} {f(y2)} "
                   f"{f(mm(t.GetLength()))}")
    if len(trk) > 150:
        out.append(f"+{len(trk) - 150} more tracks")
    out.append(f"vias: {len(vias)}")
    for v in vias[:60]:
        p = v.GetPosition()
        out.append(f"{f(mm(p.x))} {f(mm(p.y))} {f(mm(v.GetDrillValue()))}")
    if len(vias) > 60:
        out.append(f"+{len(vias) - 60} more vias")
    ws = [trk_width(t) for t in trk]
    out.append(f"total length {f(length_of(trk))} mm; width min {f(min(ws)) if ws else '-'} "
               f"max {f(max(ws)) if ws else '-'}")
    return out


def sec_area():
    x1, y1, x2, y2 = AREA
    r = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def hit(b):
        return not (b[2] < r[0] or b[0] > r[2] or b[3] < r[1] or b[1] > r[3])
    out = [f"# area ({f(r[0])},{f(r[1])})-({f(r[2])},{f(r[3])}). parts: ref x y layer | pads: ref.pin net | "
           f"tracks: net layer width x1 y1 -> x2 y2 | vias: net x y | zones: net layer"]
    parts = [fp for fp in FPS if hit(fp_bbox(fp))]
    out.append(f"parts: {len(parts)}")
    for fp in parts:
        p = fp.GetPosition()
        out.append(f"{fp.GetReference()} {f(mm(p.x))} {f(mm(p.y))} {side(fp)}")
    pads = [p for p in B.GetPads() if hit(rect_of(p))]
    pads.sort(key=lambda p: nat(pad_id(p)))
    out.append(f"pads: {len(pads)}")
    for p in pads[:100]:
        out.append(f"{pad_id(p)} {p.GetNetname() or '-'}")
    if len(pads) > 100:
        out.append(f"+{len(pads) - 100} more")
    trk = [t for t in TRACKS if not is_via(t) and seg_rect_dist(*trk_pts(t), r) - trk_width(t) / 2 <= 0]
    out.append(f"tracks: {len(trk)}")
    for t in trk[:100]:
        a, b, c, d = trk_pts(t)
        out.append(f"{t.GetNetname() or '-'} {lname(t.GetLayer())} {f(trk_width(t))} "
                   f"{f(a)} {f(b)} -> {f(c)} {f(d)}")
    if len(trk) > 100:
        out.append(f"+{len(trk) - 100} more")
    vias = [t for t in TRACKS if is_via(t) and
            pt_rect_dist(mm(t.GetPosition().x), mm(t.GetPosition().y), r) - trk_width(t) / 2 <= 0]
    out.append(f"vias: {len(vias)}")
    for v in vias[:60]:
        p = v.GetPosition()
        out.append(f"{v.GetNetname() or '-'} {f(mm(p.x))} {f(mm(p.y))}")
    if len(vias) > 60:
        out.append(f"+{len(vias) - 60} more")
    zones = [z for z in B.Zones() if hit(rect_of(z))]
    out.append(f"zones: {len(zones)}")
    for z in zones:
        layers = "+".join(lname(la) for la in z.GetLayerSet().Seq())
        label = z.GetZoneName() or z.GetNetname() or "-"
        out.append(f"{label} {layers}")
    return out


def main():
    order = {"summary": sec_summary, "parts": sec_parts, "nets": sec_nets, "unrouted": sec_unrouted,
             "near": sec_near, "net": sec_net, "area": sec_area}
    if SEC == "all":
        lines = []
        for k in ("summary", "parts", "nets", "unrouted"):
            lines += order[k]()
        print("\n".join(lines))
    else:
        print("\n".join(order[SEC]()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
