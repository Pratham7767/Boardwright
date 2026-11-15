"""Independent isolation-barrier check (read-only).

Run with KiCad's bundled Python:
    <kicad>/bin/python.exe -I barrier_check.py <project_dir>

Reads <project_dir>/boardwright.json ("barrier" section), the single *.kicad_pcb and the single
*.kicad_pro in project_dir. The board is loaded and its zones are refilled IN MEMORY only; nothing is saved.

Hazard side = copper (pads, tracks, vias, zone fill) whose net is in one of barrier.hazard_netclasses.
Safe side   = all other copper, including copper with no net (unconnected pads, copper mounting holes).
Measures the minimum 2-D copper-to-copper distance between the sides on any layer.
NOT modelled: creepage across a board edge or through slots, creepage over the surface of a
2-layer board between layers, and components' own body clearances.

Exit 0: minimum >= min_mm.  1: minimum below min_mm.  2: setup problem (config, ambiguous files, empty class).
"""
import fnmatch
import glob
import heapq
import json
import math
import os
import sys

MM = 1e6
HI_MM = 30.0          # search radius for the distance bisection


def die(msg):
    print("SETUP ERROR: " + msg)
    sys.exit(2)


if len(sys.argv) != 2:
    die("usage: barrier_check.py <project_dir>")
PROJ = os.path.abspath(sys.argv[1])
if not os.path.isdir(PROJ):
    die("not a directory: " + PROJ)


def single(ext):
    f = glob.glob(os.path.join(PROJ, "*" + ext))
    if len(f) != 1:
        die(f"expected exactly one *{ext} in {PROJ}, found {len(f)}")
    return f[0]


PCB, PRO = single(".kicad_pcb"), single(".kicad_pro")
CFG_PATH = os.path.join(PROJ, "boardwright.json")
if not os.path.isfile(CFG_PATH):
    die("missing " + CFG_PATH)
try:
    CFG = json.load(open(CFG_PATH, encoding="utf-8"))
except ValueError as e:
    die(f"cannot parse {CFG_PATH}: {e}")
BC = CFG.get("barrier")
if not isinstance(BC, dict):
    die("no 'barrier' section in boardwright.json")
HAZ = BC.get("hazard_netclasses")
if not HAZ or not isinstance(HAZ, list):
    die("barrier.hazard_netclasses must be a non-empty list")
if "min_mm" not in BC:
    die("barrier.min_mm missing")
MIN_MM = float(BC["min_mm"])
TOP = int(BC.get("top", 10))
if not BC.get("include_zone_fill", True):
    die("barrier.include_zone_fill=false is not supported: it would downgrade the check")

try:
    NS = json.load(open(PRO, encoding="utf-8"))["net_settings"]
except (ValueError, KeyError) as e:
    die(f"cannot read net_settings from {PRO}: {e}")
PATTERNS = NS.get("netclass_patterns") or []
ASSIGN = NS.get("netclass_assignments") or {}
exp = CFG.get("expect_netclass_patterns")
if exp is not None and exp != len(PATTERNS):
    die(f"expect_netclass_patterns={exp} but the project has {len(PATTERNS)}")
known = {c.get("name") for c in NS.get("classes", [])}
for c in HAZ:
    if known and c not in known:
        die(f"hazard netclass '{c}' is not defined in {os.path.basename(PRO)}")

import pcbnew  # noqa: E402  (only available in KiCad's Python)

B = pcbnew.LoadBoard(PCB)
pcbnew.ZONE_FILLER(B).Fill(B.Zones())     # in memory only; never saved


def netclass(net):
    """Netclass of a net name: explicit assignment, else first matching pattern, else Default."""
    for key in (net, net.lstrip("/")):
        if key in ASSIGN:
            v = ASSIGN[key]
            return v[0] if isinstance(v, list) else v
    cands = {net, net.lstrip("/"), "/" + net.lstrip("/")}
    for p in PATTERNS:
        pat = p["pattern"]
        for pt in {pat, pat.lstrip("/")}:
            if any(fnmatch.fnmatchcase(c, pt) for c in cands):
                return p["netclass"]
    return "Default"


def has_net(name):
    return bool(name) and not name.startswith("unconnected-")


# every hazard class must resolve to at least one net on the board (an empty hazard side would pass falsely)
board_nets = [str(n) for n in B.GetNetsByName().keys() if str(n)]
for c in HAZ:
    if not [n for n in board_nets if netclass(n) == c]:
        die(f"hazard netclass '{c}' matches zero nets on the board; the hazard side would be incomplete")
HAZ_SET = set(HAZ)


def is_hazard(net):
    return has_net(net) and netclass(net) in HAZ_SET


COPPER = [L for L in B.GetEnabledLayers().CuStack()]
items = []   # dict: side, layer, shape, label, group, kind, x, y, bb, zone


def add(side, L, shape, label, group, kind, x, y):
    items.append({"side": side, "layer": L, "shape": shape, "label": label, "group": group, "kind": kind,
                  "x": x, "y": y, "bb": shape.BBox(), "zone": kind == "zone"})


for fp in B.GetFootprints():
    for p in fp.Pads():
        net = p.GetNetname()
        side = "H" if is_hazard(net) else "S"
        q = p.GetPosition()
        ref = f"{fp.GetReference()}.{p.GetNumber()}" if p.GetNumber() else f"{fp.GetReference()}.(pad)"
        lab = f"{ref} [{net if has_net(net) else 'no net'}]"
        for L in COPPER:
            if p.IsOnLayer(L):
                add(side, L, p.GetEffectiveShape(L), lab, "pad " + ref, "pad", q.x / MM, q.y / MM)
for t in B.GetTracks():
    net = t.GetNetname()
    side = "H" if is_hazard(net) else "S"
    isvia = t.GetClass() == "PCB_VIA"
    for L in COPPER:
        if t.IsOnLayer(L):
            if isvia:
                q = t.GetPosition()
                add(side, L, t.GetEffectiveShape(L), f"via [{net or 'no net'}] @{q.x/MM:.2f},{q.y/MM:.2f}",
                    f"via {net}", "via", q.x / MM, q.y / MM)
            else:
                m = t.GetStart()
                e = t.GetEnd()
                x, y = (m.x + e.x) / 2 / MM, (m.y + e.y) / 2 / MM
                add(side, L, t.GetEffectiveShape(L), f"track [{net or 'no net'}] @{x:.2f},{y:.2f}",
                    f"track {net}", "track", x, y)
for z in B.Zones():
    if z.GetIsRuleArea():
        continue
    net = z.GetNetname()
    side = "H" if is_hazard(net) else "S"
    for L in COPPER:
        if not z.IsOnLayer(L):
            continue
        fill = z.GetFilledPolysList(L)
        if fill.OutlineCount() == 0:
            continue
        bb = fill.BBox()
        add(side, L, fill, f"zone fill [{net or 'no net'}] {B.GetLayerName(L)}",
            f"zone {net} {B.GetLayerName(L)}", "zone",
            (bb.GetLeft() + bb.GetRight()) / 2 / MM, (bb.GetTop() + bb.GetBottom()) / 2 / MM)

H = [i for i in items if i["side"] == "H"]
S = [i for i in items if i["side"] == "S"]
if not H:
    die("hazard side has no copper items")
if not S:
    die("safe side has no copper items")


class Top:
    """Best distance per (hazard group, safe group); `n` smallest are kept visible."""

    def __init__(self, n):
        self.n, self.d, self.cut = n, {}, HI_MM

    def update(self, key, dist, rec):
        cur = self.d.get(key)
        if cur is None or dist < cur[0]:
            self.d[key] = (dist, rec)
            if len(self.d) >= self.n:
                c = heapq.nsmallest(self.n, (v[0] for v in self.d.values()))[-1]
                self.cut = min(c, HI_MM)

    def ranked(self):
        return sorted(self.d.values(), key=lambda v: v[0])[: self.n]


ALL, NZ = Top(TOP), Top(TOP)
for a in H:
    ba = a["bb"]
    for b in S:
        if a["layer"] != b["layer"]:
            continue
        bb = b["bb"]
        dx = max(ba.GetLeft() - bb.GetRight(), bb.GetLeft() - ba.GetRight(), 0)
        dy = max(ba.GetTop() - bb.GetBottom(), bb.GetTop() - ba.GetBottom(), 0)
        lb = math.hypot(dx, dy) / MM
        zone_pair = a["zone"] or b["zone"]
        cut = ALL.cut if zone_pair else max(ALL.cut, NZ.cut)
        if lb >= cut:
            continue
        sa, sb = a["shape"], b["shape"]
        if sa.Collide(sb, 0):
            d = 0.0
        else:
            lo, hi = 0, int(min(cut, HI_MM) * MM) + 1
            if not sa.Collide(sb, hi):
                continue
            while hi - lo > 100:           # 0.1 um resolution
                m = (lo + hi) // 2
                if sa.Collide(sb, m):
                    hi = m
                else:
                    lo = m
            d = lo / MM            # lower bound: never report more distance than there is
        key = (a["group"], b["group"])
        ALL.update(key, d, (a, b))
        if not zone_pair:
            NZ.update(key, d, (a, b))


def fmt(v):
    d, (a, b) = v
    return {"distance_mm": round(d, 3), "hazard": a["label"], "safe": b["label"],
            "hazard_kind": a["kind"], "safe_kind": b["kind"],
            "layer": B.GetLayerName(a["layer"]),
            "hazard_xy_mm": [round(a["x"], 2), round(a["y"], 2)],
            "safe_xy_mm": [round(b["x"], 2), round(b["y"], 2)]}


R_ALL = [fmt(v) for v in ALL.ranked()]
R_NZ = [fmt(v) for v in NZ.ranked()]
if not R_ALL:
    die(f"no hazard/safe pair found within {HI_MM:.0f} mm: check the config (nothing to measure)")
MIN_ALL = R_ALL[0]["distance_mm"]
MIN_NZ = R_NZ[0]["distance_mm"] if R_NZ else None
TOL_MM = 0.001        # measurement resolution (1 um); zone fills sit exactly on the DRC limit
PASS = MIN_ALL >= MIN_MM - TOL_MM


def table(title, rows):
    print(f"\n{title}")
    print(f"{'mm':>7}  {'layer':<5} hazard side item (x,y)  <->  safe side item (x,y)")
    for r in rows:
        ha = f"{r['hazard']} ({r['hazard_xy_mm'][0]},{r['hazard_xy_mm'][1]})"
        sa = f"{r['safe']} ({r['safe_xy_mm'][0]},{r['safe_xy_mm'][1]})"
        print(f"{r['distance_mm']:7.2f}  {r['layer']:<5} {ha}  <->  {sa}")


print(f"Isolation barrier check: {os.path.basename(PCB)}")
print(f"Hazard netclasses: {', '.join(HAZ)}   required minimum: {MIN_MM} mm   hazard items {len(H)}, safe items {len(S)}")
print("Note: 2-D copper-to-copper distance on any layer; creepage across a board edge or slot is NOT modelled.")
print("Note: zone fills refilled in memory; zone positions are the fill bounding-box centre.")
table(f"Closest {TOP} pairs (all copper, incl. zone fill)", R_ALL)
table(f"Closest {TOP} pairs excluding zone fill", R_NZ)
print(f"\nMinimum (all copper): {MIN_ALL:.2f} mm; excluding zone fill: " +
      (f"{MIN_NZ:.2f} mm" if MIN_NZ is not None else "n/a"))
print(f"RESULT: {'PASS' if PASS else 'FAIL'} (minimum {MIN_ALL:.2f} mm {'>=' if PASS else '<'} {MIN_MM} mm)")

os.makedirs(os.path.join(PROJ, "reports"), exist_ok=True)
with open(os.path.join(PROJ, "reports", "barrier.json"), "w", encoding="utf-8") as f:
    json.dump({"board": os.path.basename(PCB), "hazard_netclasses": HAZ, "min_mm": MIN_MM,
               "minimum_all_mm": MIN_ALL, "minimum_excluding_zone_fill_mm": MIN_NZ, "pass": PASS,
               "hazard_items": len(H), "safe_items": len(S),
               "closest_all": R_ALL, "closest_excluding_zone_fill": R_NZ,
               "not_modelled": "creepage across a board edge or slot; surface creepage between layers"},
              f, indent=1)
sys.exit(0 if PASS else 1)
