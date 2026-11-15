#!/usr/bin/env python3
"""Circuit-block rule measurements from manufacturers' application notes (read-only).

Run with KiCad's bundled Python (it provides `pcbnew`):
    <kicad>/bin/python.exe -I block_check.py <project_dir>

Inputs: netlist from `kicad-cli sch export netlist --format kicadxml` (components, fields, pin types,
nets) and the board through pcbnew (pad positions, layers, tracks, vias). The board is only loaded, never saved.
Limits can be changed in <project_dir>/boardwright.json under "block"; every row prints the limit used and
whether it is the default. There is deliberately no option to skip or downgrade a check.
Exit code 0 = no ERROR, 1 = at least one ERROR, 2 = setup problem.
Reports: <project_dir>/reports/block-check.json and block-check.md.

CHECKS (rows: id | severity | item | measured | limit | note)
 B1 decoupling distance IC power pin -> nearest cap to ground   B2 protection part -> connector distance
 B3 crystal load capacitance                                    B4 I2C pull-up range
 B5 track width against current (block.currents)                B6 BOM against placement file
 B7 paste layers in the gerber export
Components in the schematic but not on the board are listed once (B0, INFO) and skipped by geometric checks.
Config keys ("block"): decoupling_max_mm, protection_max_mm, protection_refs, crystal_stray_pf, i2c_mode,
 i2c_bus_pf, i2c_vcc, currents, width_mm_per_amp.
Notes on heuristics: X-prefixed refs count as crystals only when the part has at most 4 pins; nets named
 SCLK are not treated as I2C SCL; a configured block.i2c_vcc overrides the Vcc parsed from the rail name.
"""
import json
import math
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_gates import find_kicad_cli  # noqa: E402

HEADER = ("Rule sources: TI SLVA689 (I2C), TI AN-1229 (track width), RP2040 hardware design guide (crystal), "
          "plugin EMC guide values (protection distance). Defaults marked 'default' are engineering "
          "estimates; the part's datasheet takes priority.")
MM = 1e6
MAX_INFO_ROWS = 25
MPN_NAMES = ("mpn", "mfr part", "manufacturer_part_number", "manufacturer part number")
GND_RE = re.compile(r"GND|VSS", re.I)
PROT_RE = re.compile(r"TVS|ESD|SMBJ|SMAJ|SMCJ|USBLC|PESD|PRTR|TPD\d|SP05|ESDA", re.I)
CONN_RE = re.compile(r"^(J|P|CN|USB)\d", re.I)
RAIL_RE = re.compile(r"3V3|3\.3V|5V|1V8|VCC|VDD|VBUS|\+", re.I)
DEFAULTS = {
    "decoupling_max_mm": 5.0,
    "protection_max_mm": 10.0,
    "protection_refs": [],
    "crystal_stray_pf": 3.0,
    "i2c_mode": "fast",
    "i2c_bus_pf": 100.0,
    "i2c_vcc": None,
    "currents": None,
    "width_mm_per_amp": 0.305,
}
I2C_MODES = {"standard": (1000e-9, 0.003), "fast": (300e-9, 0.003), "fast-plus": (120e-9, 0.020)}


class SetupError(Exception):
    pass


# ------------------------------------------------------------ value parsing
_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "\u00b5": 1e-6, "\u03bc": 1e-6, "m": 1e-3,
           "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "R": 1.0}
_INFIX = re.compile(r"^(\d+)([pnu\u00b5\u03bcmkKMGR])(\d+)(?![A-Za-z])")
_PLAIN = re.compile(r"^(\d+(?:\.\d+)?)\s*([pnu\u00b5\u03bcmkKMGR]?)\s*"
                    r"(F|f|\u03a9|\u2126|[Oo]hms?)?(?![A-Za-z0-9])")


def parse_value(text):
    """Parse '15p', '15 pF', '0.015n', '4k7', '4.7k', '10K 1%', '4700', '2R2', '100n/50V', '1uF'.

    Returns (value in base units, explicit) where explicit is False for a bare number without prefix or
    unit (ambiguous), or None if the text cannot be parsed."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    s = re.split(r"/|\s{2,}", s)[0].strip()       # '100n/50V' -> '100n'
    m = _INFIX.match(s)
    if m:
        return float(f"{m.group(1)}.{m.group(3)}") * _PREFIX[m.group(2)], True
    m = _PLAIN.match(s)
    if m:
        explicit = bool(m.group(2) or m.group(3))
        return float(m.group(1)) * (_PREFIX[m.group(2)] if m.group(2) else 1.0), explicit
    return None


def cap_pf(text, bare_is_pf=False):
    p = parse_value(text)
    if p is None:
        return None
    v, explicit = p
    if not explicit:
        return float(v) if bare_is_pf else None
    return v * 1e12


def res_ohm(text):
    p = parse_value(text)
    return None if p is None else p[0]


# ------------------------------------------------------------ calculations
def crystal_cl(c1_pf, c2_pf, stray_pf):
    """Load capacitance seen by the crystal: C1*C2/(C1+C2) + stray (RP2040 hardware design guide)."""
    return c1_pf * c2_pf / (c1_pf + c2_pf) + stray_pf


def i2c_range(vcc, mode, cb_pf):
    """(Rp_min, Rp_max) in ohm: (Vcc-0.4)/IOL and tr/(0.8473*Cb) (TI SLVA689)."""
    tr, iol = I2C_MODES[mode]
    return (vcc - 0.4) / iol, tr / (0.8473 * cb_pf * 1e-12)


def i2c_verdict(rp, vcc, mode, cb_pf):
    lo, hi = i2c_range(vcc, mode, cb_pf)
    return lo <= rp <= hi, lo, hi


def vcc_from_name(name):
    n = name.lstrip("/")
    m = re.search(r"(?<![\d.])(\d+)V(\d+)(?!\d)", n, re.I)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*V(?![A-Za-z])", n, re.I)
    if m:
        return float(m.group(1))
    return None


# ------------------------------------------------------------ project / netlist
def find_stem(project):
    stems = set()
    for pattern in ("*.kicad_pro", "*.kicad_pcb"):
        found = sorted(project.glob(pattern))
        if len(found) > 1:
            raise SetupError(f"more than one {pattern} in {project}; cannot pick the project")
        stems.update(p.stem for p in found)
    if len(stems) != 1:
        raise SetupError(f"no single project stem found in {project} "
                         f"(*.kicad_pro / *.kicad_pcb give {sorted(stems) or 'nothing'})")
    stem = stems.pop()
    for ext in (".kicad_sch", ".kicad_pcb"):
        if not (project / (stem + ext)).exists():
            raise SetupError(f"{stem}{ext} not found in {project}")
    return stem


def export_netlist(cli, sch):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "netlist.xml"
        cmd = [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out), str(sch)]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0 or not out.exists():
            raise SetupError("netlist export failed: " + (proc.stderr or proc.stdout).strip()[:500])
        try:
            return ET.parse(out).getroot()
        except ET.ParseError as exc:
            raise SetupError(f"cannot parse netlist XML: {exc}")


def parse_netlist(root):
    comps = OrderedDict()
    for c in root.findall("./components/comp"):
        ref = c.get("ref") or ""
        if ref.startswith("#"):
            continue
        fields = {}
        for f in c.findall("./fields/field"):
            fields[(f.get("name") or "").strip().lower()] = (f.text or "").strip()
        props = {(p.get("name") or "").strip().lower() for p in c.findall("./property")}
        ls = c.find("libsource")
        comps[ref] = {
            "ref": ref, "value": (c.findtext("value") or "").strip(), "fields": fields,
            "excluded": any("exclude_from_board" in p for p in props),
            "dnp": "dnp" in props,
            "lib": ls.get("lib") if ls is not None else "",
            "part": ls.get("part") if ls is not None else "",
            "pins": [],
        }
    nets = OrderedDict()
    power_out = set()
    for n in root.findall("./nets/net"):
        name = n.get("name") or ""
        nodes = []
        for nd in n.findall("node"):
            ref = nd.get("ref") or ""
            if ref.startswith("#"):
                continue
            node = {"ref": ref, "pin": nd.get("pin") or "", "func": nd.get("pinfunction") or "",
                    "type": nd.get("pintype") or ""}
            nodes.append(node)
            if node["type"] == "power_out":
                power_out.add(name)
            if ref in comps:
                comps[ref]["pins"].append({"pin": node["pin"], "net": name, "type": node["type"]})
        nets[name] = nodes
    return comps, nets, power_out


def mpn_of(comp):
    for name in MPN_NAMES:
        if comp["fields"].get(name):
            return comp["fields"][name]
    return ""


def prefix_match(ref, regex):
    return re.match(regex, ref) is not None


def is_ground(name):
    return bool(GND_RE.search(name))


# ------------------------------------------------------------ config
def load_config(project):
    cfg = dict(DEFAULTS)
    src = {k: "default" for k in DEFAULTS}
    path = project / "boardwright.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SetupError(f"cannot read {path.name}: {exc}")
        blk = data.get("block") if isinstance(data, dict) else None
        if blk is not None:
            if not isinstance(blk, dict):
                raise SetupError("boardwright.json: 'block' must be an object")
            for k, v in blk.items():
                if k not in DEFAULTS:
                    raise SetupError(f"boardwright.json block: unknown key '{k}' (known: {sorted(DEFAULTS)})")
                cfg[k] = v
                src[k] = "config"
    for k in ("decoupling_max_mm", "protection_max_mm", "crystal_stray_pf", "i2c_bus_pf", "width_mm_per_amp"):
        v = cfg[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or (k in ("i2c_bus_pf", "width_mm_per_amp") and v == 0):
            raise SetupError(f"block.{k} must be a positive number, got {v!r}")
        cfg[k] = float(v)
    if cfg["i2c_mode"] not in I2C_MODES:
        raise SetupError(f"block.i2c_mode must be one of {sorted(I2C_MODES)}, got {cfg['i2c_mode']!r}")
    if cfg["i2c_vcc"] is not None and (isinstance(cfg["i2c_vcc"], bool) or not isinstance(cfg["i2c_vcc"], (int, float))
                                       or cfg["i2c_vcc"] <= 0.4):
        raise SetupError(f"block.i2c_vcc must be a number above 0.4, got {cfg['i2c_vcc']!r}")
    if not isinstance(cfg["protection_refs"], list):
        raise SetupError("block.protection_refs must be a list of references")
    cur = cfg["currents"]
    if cur is not None:
        if not isinstance(cur, dict):
            raise SetupError("block.currents must be an object {net name: amps}")
        for k, v in cur.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise SetupError(f"block.currents['{k}'] must be a positive number, got {v!r}")
    return cfg, src


# ------------------------------------------------------------ board access
class Board:
    def __init__(self, pcb_path):
        import pcbnew
        self.pcbnew = pcbnew
        self.B = pcbnew.LoadBoard(str(pcb_path))      # never saved
        self.pads = {}
        self.layer = {}
        for fp in self.B.GetFootprints():
            ref = fp.GetReference()
            d = {}
            for p in fp.Pads():
                q = p.GetPosition()
                d.setdefault(p.GetNumber(), []).append((q.x / MM, q.y / MM))
            self.pads[ref] = d
            self.layer[ref] = "top" if fp.GetLayer() == pcbnew.F_Cu else "bottom"
        self.tracks = []      # (netname, width_mm, class)
        self.vias = []        # (netname, x, y)
        for t in self.B.GetTracks():
            if t.GetClass() == "PCB_VIA":
                q = t.GetPosition()
                self.vias.append((t.GetNetname(), q.x / MM, q.y / MM))
            else:
                self.tracks.append((t.GetNetname(), t.GetWidth() / MM))

    def placed(self, ref):
        return ref in self.pads

    def pad_xy(self, ref, num):
        return self.pads.get(ref, {}).get(num, [])

    def net_exists(self, name):
        return self.B.FindNet(name) is not None

    def netclass_names(self, name):
        n = self.B.FindNet(name)
        raw = n.GetNetClassName() if n is not None else ""
        return [c for c in (raw or "").split(",") if c]

    def paste_pads(self):
        pn = self.pcbnew
        cnt = {"top": 0, "bottom": 0}
        for fp in self.B.GetFootprints():
            for p in fp.Pads():
                if p.GetAttribute() != pn.PAD_ATTRIB_SMD:
                    continue
                if p.IsOnLayer(pn.F_Paste):
                    cnt["top"] += 1
                if p.IsOnLayer(pn.B_Paste):
                    cnt["bottom"] += 1
        return cnt


def min_dist(a_list, b_list):
    best = None
    for a in a_list:
        for b in b_list:
            d = math.dist(a, b)
            if best is None or d < best:
                best = d
    return best


# ------------------------------------------------------------ rows
class Rows:
    def __init__(self):
        self.rows = []

    def add(self, cid, sev, item, measured, limit, note, limit_src=None):
        self.rows.append({"id": cid, "severity": sev, "item": item, "measured": measured,
                          "limit": limit, "limit_source": limit_src, "note": note})

    def counts(self):
        c = {"ERROR": 0, "WARN": 0, "INFO": 0}
        for r in self.rows:
            c[r["severity"]] += 1
        return c

    def sorted(self):
        order = {"ERROR": 0, "WARN": 1, "INFO": 2}
        return sorted(self.rows, key=lambda r: order[r["severity"]])    # stable: keeps check order


def short_list(items, n=15):
    items = list(items)
    return ", ".join(items[:n]) + (f" +{len(items) - n}" if len(items) > n else "")


# ------------------------------------------------------------ B1
def check_b1(R, comps, nets, board, cfg, src):
    lim = cfg["decoupling_max_mm"]
    lim_txt = f"<= {lim:g} mm ({src['decoupling_max_mm']})"
    note_default = "default, engineering estimate: use the IC's datasheet" if src["decoupling_max_mm"] == "default" else ""
    caps = {}
    for ref, c in comps.items():
        if prefix_match(ref, r"C\d+$") and not c["excluded"] and len(c["pins"]) == 2:
            caps[ref] = c
    for ref, c in comps.items():
        if not prefix_match(ref, r"(U|IC)\d+"):
            continue
        if c["excluded"]:
            continue
        groups = OrderedDict()
        for p in c["pins"]:
            if p["type"] == "power_in" and p["net"] and not is_ground(p["net"]) and not p["net"].startswith("unconnected-") \
                    and not p["net"].startswith("/unconnected-"):
                groups.setdefault(p["net"], []).append(p["pin"])
        for net, pins in groups.items():
            item = f"{ref} pin{'s' if len(pins) > 1 else ''} {','.join(pins)} ({net})"
            cands = []
            for cref, cc in caps.items():
                nl = [p["net"] for p in cc["pins"]]
                if net in nl and any(is_ground(n) for n in nl if n != net):
                    cands.append((cref, cc, [p["pin"] for p in cc["pins"] if p["net"] == net]))
            if not cands:
                R.add("B1", "WARN", item, "no capacitor", lim_txt, "no decoupling capacitor on net", src["decoupling_max_mm"])
                continue
            if not board.placed(ref):
                continue
            best = None
            for cref, cc, cpins in cands:
                if not board.placed(cref):
                    continue
                for ip in pins:
                    for cp in cpins:
                        d = min_dist(board.pad_xy(ref, ip), board.pad_xy(cref, cp))
                        if d is not None and (best is None or d < best[0]):
                            best = (d, cref, cc, ip)
            if best is None:
                continue
            d, cref, cc, ip = best
            same = board.layer[cref] == board.layer[ref]
            problems = []
            if d > lim:
                problems.append("farther than limit")
            if not same:
                problems.append(f"capacitor on {board.layer[cref]}, IC on {board.layer[ref]}")
            sev = "WARN" if problems else "INFO"
            note = f"nearest cap {cref} {cc['value']} at pin {ip}, {'same' if same else 'other'} layer"
            if problems:
                note += "; " + "; ".join(problems)
            if note_default:
                note += "; " + note_default
            R.add("B1", sev, item, f"{d:.1f} mm", lim_txt, note, src["decoupling_max_mm"])


# ------------------------------------------------------------ B2
def check_b2(R, comps, nets, board, cfg, src):
    lim = cfg["protection_max_mm"]
    lim_txt = f"<= {lim:g} mm ({src['protection_max_mm']})"
    extra = {str(r) for r in cfg["protection_refs"]}
    conn_pins = {}
    for net, nodes in nets.items():
        conn_pins[net] = [n for n in nodes if prefix_match(n["ref"], CONN_RE.pattern) and n["ref"] in comps]
    for ref, c in comps.items():
        if c["excluded"]:
            continue
        hay = " ".join([c["value"], mpn_of(c), c["part"]])
        if ref not in extra and not PROT_RE.search(hay):
            continue
        shared = False
        for p in c["pins"]:
            net = p["net"]
            if not net or is_ground(net):
                continue
            conns = [n for n in conn_pins.get(net, []) if n["ref"] != ref]
            if not conns:
                continue
            shared = True
            item = f"{ref}.{p['pin']} -> connector ({net})"
            if not board.placed(ref):
                continue
            best = None
            for n in conns:
                if not board.placed(n["ref"]):
                    continue
                d = min_dist(board.pad_xy(ref, p["pin"]), board.pad_xy(n["ref"], n["pin"]))
                if d is not None and (best is None or d < best[0]):
                    best = (d, n)
            if best is None:
                continue
            d, n = best
            a = board.pad_xy(ref, p["pin"])[0]
            b = board.pad_xy(n["ref"], n["pin"])[0]
            x0, x1 = min(a[0], b[0]) - 1.0, max(a[0], b[0]) + 1.0
            y0, y1 = min(a[1], b[1]) - 1.0, max(a[1], b[1]) + 1.0
            nv = sum(1 for vn, vx, vy in board.vias if vn == net and x0 <= vx <= x1 and y0 <= vy <= y1)
            sev = "WARN" if d > lim else "INFO"
            R.add("B2", sev, item, f"{d:.1f} mm to {n['ref']}.{n['pin']}", lim_txt,
                  f"{nv} via(s) of this net in the box between the pads (+1 mm); pad centre to pad centre",
                  src["protection_max_mm"])
        if not shared:
            R.add("B2", "INFO", f"{ref} ({c['value']})", "-", lim_txt, "not on a connector net", src["protection_max_mm"])


# ------------------------------------------------------------ B3
def check_b3(R, comps, nets, cfg, src):
    stray = cfg["crystal_stray_pf"]
    stray_note = "assumed stray; formula from the RP2040 hardware design guide" if src["crystal_stray_pf"] == "default" else ""
    lim_default = f"stray {stray:g} pF ({src['crystal_stray_pf']})"
    for ref, c in comps.items():
        if c["excluded"]:
            continue
        is_xtal = (prefix_match(ref, r"(Y|X)\d") and len(c["pins"]) <= 4) or re.search(r"crystal|resonator", c["part"], re.I) \
            or prefix_match(ref, r"Y\d")
        if not is_xtal:
            continue
        xnets = []
        for p in c["pins"]:
            if p["net"] and not is_ground(p["net"]) and p["net"] not in xnets:
                xnets.append(p["net"])
        item = f"{ref} {c['value']}"
        if len(xnets) != 2:
            R.add("B3", "WARN", item, "-", lim_default, f"cannot identify the two crystal nets (found {xnets})")
            continue
        loads = []
        for n in xnets:
            lst = []
            for cref, cc in comps.items():
                if not prefix_match(cref, r"C\d+$") or len(cc["pins"]) != 2 or cc["excluded"]:
                    continue
                nl = [p["net"] for p in cc["pins"]]
                if n in nl and any(is_ground(x) for x in nl if x != n):
                    lst.append(cc)
            loads.append(lst)
        if len(loads[0]) != 1 or len(loads[1]) != 1:
            R.add("B3", "WARN", item, "-", lim_default,
                  f"cannot identify load capacitors: {xnets[0]} has {[x['ref'] for x in loads[0]]}, "
                  f"{xnets[1]} has {[x['ref'] for x in loads[1]]} (need exactly one each)")
            continue
        c1, c2 = loads[0][0], loads[1][0]
        v1, v2 = cap_pf(c1["value"]), cap_pf(c2["value"])
        if v1 is None or v2 is None:
            R.add("B3", "WARN", item, "-", lim_default,
                  f"cannot parse capacitor values {c1['ref']}='{c1['value']}', {c2['ref']}='{c2['value']}'")
            continue
        cl = crystal_cl(v1, v2, stray)
        target = crystal_target(c)
        base = f"{c1['ref']} {v1:g} pF + {c2['ref']} {v2:g} pF"
        if target is None:
            R.add("B3", "INFO", item, f"CL {cl:.2f} pF", lim_default,
                  f"{base}; no target CL known (field CL/Load or '<n>pF' in value/MPN); {stray_note}".rstrip("; "),
                  src["crystal_stray_pf"])
        else:
            dev = abs(cl - target) / target
            sev = "WARN" if dev > 0.20 else "INFO"
            R.add("B3", sev, item, f"CL {cl:.2f} pF", f"target {target:g} pF +/-20% ({src['crystal_stray_pf']} stray)",
                  f"{base}; deviation {dev * 100:.0f}%; {stray_note}".rstrip("; "), src["crystal_stray_pf"])


def crystal_target(c):
    for name in ("cl", "load", "load capacitance"):
        v = c["fields"].get(name)
        if v:
            t = cap_pf(v, bare_is_pf=True)
            if t:
                return t
    toks = set()
    for text in (c["value"], mpn_of(c)):
        for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*pF", text or "", re.I):
            toks.add(float(m.group(1)))
    return toks.pop() if len(toks) == 1 else None


# ------------------------------------------------------------ B4
def check_b4(R, comps, nets, power_out, cfg, src):
    mode = cfg["i2c_mode"]
    cb = cfg["i2c_bus_pf"]
    for net in nets:
        if not (re.search(r"SDA", net, re.I) or re.search(r"SCL(?!K)", net, re.I)):
            continue
        ups = []
        for n in nets[net]:
            c = comps.get(n["ref"])
            if c is None or not prefix_match(c["ref"], r"R\d+$") or len(c["pins"]) != 2 or c["excluded"]:
                continue
            other = [p["net"] for p in c["pins"] if p["pin"] != n["pin"]]
            if len(other) != 1:
                continue
            on = other[0]
            if is_ground(on):
                continue
            if on in power_out or RAIL_RE.search(on):
                ups.append((c, on))
        item = f"{net}"
        if not ups:
            R.add("B4", "WARN", item, "no pull-up", f"{mode} mode, Cb {cb:g} pF ({src['i2c_bus_pf']})",
                  "no resistor from this net to a power net (an external pull-up may be on another board)")
            continue
        vals = [res_ohm(c["value"]) for c, _ in ups]
        if any(v is None or v <= 0 for v in vals):
            R.add("B4", "WARN", item, "-", "-", "cannot parse pull-up value(s) " + ", ".join(f"{c['ref']}='{c['value']}'" for c, _ in ups))
            continue
        rp = 1.0 / sum(1.0 / v for v in vals)
        rails = sorted({r for _, r in ups})
        vcc = cfg["i2c_vcc"] if cfg["i2c_vcc"] is not None else vcc_from_name(rails[0])
        refs = "+".join(c["ref"] for c, _ in ups)
        if vcc is None:
            R.add("B4", "WARN", item, f"{rp:g} ohm ({refs})", "-",
                  f"cannot determine Vcc from rail '{rails[0]}'; set block.i2c_vcc")
            continue
        ok, lo, hi = i2c_verdict(rp, vcc, mode, cb)
        notes = [f"{refs} to {','.join(rails)}", f"Vcc {vcc:g} V", f"Cb {cb:g} pF {src['i2c_bus_pf']} (assumed bus capacitance; formulas from TI SLVA689)"]
        probs = []
        if len(ups) > 1:
            probs.append(f"{len(ups)} pull-ups in parallel ({' || '.join(f'{v:g}' for v in vals)} = {rp:.0f} ohm)")
        if len(rails) > 1:
            probs.append("pull-ups go to different rails")
        if not ok:
            probs.append("below minimum (sink current)" if rp < lo else "above maximum (rise time)")
        sev = "WARN" if probs else "INFO"
        R.add("B4", sev, item, f"{rp:.0f} ohm", f"{lo:.0f}..{hi:.0f} ohm ({mode}, tr {I2C_MODES[mode][0]*1e9:g} ns)",
              "; ".join(probs + notes), src["i2c_bus_pf"])


# ------------------------------------------------------------ B5
def resolve_net(board, name):
    for cand in (name, "/" + name.lstrip("/"), name.lstrip("/")):
        if board.net_exists(cand):
            return cand
    return None


def check_b5(R, board, cfg, src):
    per = cfg["width_mm_per_amp"]
    cur = cfg["currents"]
    wsrc = src["width_mm_per_amp"]
    minw = {}
    for n, w in board.tracks:
        if n and (n not in minw or w < minw[n]):
            minw[n] = w
    if cur:
        resolved = OrderedDict()
        for name, amps in cur.items():
            r = resolve_net(board, name)
            if r is None:
                raise SetupError(f"block.currents: net '{name}' does not exist on the board")
            resolved[r] = (name, amps)
        for net, (name, amps) in resolved.items():
            req = amps * per
            lim = f">= {req:.3f} mm = {amps:g} A x {per:g} mm/A ({wsrc})"
            note = "TI AN-1229 s6.1, valid for the conditions stated there" + ("; default" if wsrc == "default" else "")
            if net not in minw:
                R.add("B5", "WARN", net, "no tracks", lim, "no track on this net (copper may be a zone); width not measured. " + note, wsrc)
            else:
                w = minw[net]
                R.add("B5", "WARN" if w < req - 1e-9 else "INFO", net, f"min {w:.3f} mm", lim, note, wsrc)
    else:
        rows = []
        for net, w in minw.items():
            classes = board.netclass_names(net)
            if any(c != "Default" for c in classes):
                rows.append((w, net))
        rows.sort()
        txt = ", ".join(f"{n} {w:.2f}" for w, n in rows[:5]) or "none (no tracks in non-Default net classes)"
        R.add("B5", "INFO", "five thinnest non-Default-class nets", txt, f"{per:g} mm/A ({wsrc})",
              "no currents configured (block.currents); width values in mm")


# ------------------------------------------------------------ B6
def expand_refs(cell):
    return [r.strip() for r in re.split(r"[,;]", cell or "") if r.strip()]


def check_b6(R, project, stem, pcb_path):
    bom = project / "fab" / f"{stem}-bom.csv"
    pos = project / "fab" / f"{stem}-pos.csv"
    if not (bom.exists() and pos.exists()):
        R.add("B6", "INFO", "fab/" + stem + "-bom.csv, -pos.csv", "-", "-", "no release files yet")
        return
    import csv

    def read(p):
        with open(p, newline="", encoding="utf-8-sig", errors="replace") as f:
            return list(csv.DictReader(f))

    def col(rows, names):
        if not rows:
            return None
        for k in rows[0].keys():
            if k and k.strip().lower() in names:
                return k
        return None
    brows, prows = read(bom), read(pos)
    bk = col(brows, ("reference", "references", "designator"))
    pk = col(prows, ("ref", "reference", "designator"))
    if bk is None or pk is None:
        raise SetupError(f"fab BOM/position file lacks a Reference/Ref column (BOM {bk}, pos {pk})")
    bref = [r for row in brows for r in expand_refs(row[bk])]
    pref = [(row[pk] or "").strip() for row in prows]
    ranges = [r for r in bref if re.match(r"^[A-Za-z]+\d+\s*[-\u2013]\s*[A-Za-z]*\d+$", r)]
    bset, pset = set(bref), set(pref)
    bl, pl = {r.lower() for r in bset}, {r.lower() for r in pset}
    only_b = sorted(bset - pset)
    only_p = sorted(pset - bset)
    case_only_b = [r for r in only_b if r.lower() in pl]
    case_only_p = [r for r in only_p if r.lower() in bl]
    item = f"{bom.name} vs {pos.name}"
    meas = f"BOM {len(bset)} refs, pos {len(pset)} refs"
    problems = False
    if ranges:
        R.add("B6", "WARN", item, meas, "-", "reference looks like a range: " + short_list(ranges))
        problems = True
    if only_b:
        real = [r for r in only_b if r not in case_only_b]
        if real:
            R.add("B6", "WARN", item, meas, "-", "in BOM but not in placement file (case-insensitive): " + short_list(real))
            problems = True
    if only_p:
        real = [r for r in only_p if r not in case_only_p]
        if real:
            R.add("B6", "WARN", item, meas, "-", "in placement file but not in BOM (case-insensitive): " + short_list(real))
            problems = True
    if case_only_b or case_only_p:
        R.add("B6", "WARN", item, meas, "-",
              "match only when case is ignored: BOM " + short_list(case_only_b) + " / pos " + short_list(case_only_p))
        problems = True
    pcb_m = pcb_path.stat().st_mtime
    old = [p.name for p in (bom, pos) if p.stat().st_mtime < pcb_m]
    if old:
        R.add("B6", "WARN", item, ", ".join(f"{p.name} {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}"
                                            for p in (bom, pos)),
              f"older than {pcb_path.name} ({time.strftime('%Y-%m-%d %H:%M', time.localtime(pcb_m))})",
              "exported before the last board change")
        problems = True
    if not problems:
        R.add("B6", "INFO", item, meas, "-", "BOM and placement references match (case-sensitive)")


# ------------------------------------------------------------ B7
def count_flashes(path):
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.rstrip().endswith("D03*"):
                n += 1
    return n


def check_b7(R, project, board):
    gdir = project / "fab" / "gerbers"
    if not gdir.is_dir():
        R.add("B7", "INFO", "fab/gerbers", "-", "-", "no release files yet")
        return
    files = [p for p in gdir.iterdir() if p.is_file()]
    others = [p for p in files if "_Paste" not in p.name]
    pads = board.paste_pads()
    for side, key in (("top", "F_Paste"), ("bottom", "B_Paste")):
        found = [p for p in files if key in p.name]
        n = pads[side]
        flashes = sum(count_flashes(p) for p in found)
        item = f"{key} ({side})"
        meas = f"{flashes} flashes in {', '.join(p.name for p in found) or 'no file'}; {n} SMD pads with paste"
        if n > 0 and (not found or flashes == 0) and others:
            R.add("B7", "ERROR", item, meas, "flashes > 0 when pads with paste exist",
                  "paste file " + ("missing" if not found else "has no flashes") + " but the board has SMD pads with paste")
        else:
            R.add("B7", "INFO", item, meas, "-",
                  "flashes are counted from lines ending D03*; regions (G36) and stencil-only apertures are not counted")


# ------------------------------------------------------------ output
def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def render(rows, hidden):
    out = ["| id | sev | item | measured | limit | note |", "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['id']} | {r['severity']} | {esc(r['item'])} | {esc(r['measured'])} | {esc(r['limit'])} | {esc(r['note'])} |")
    if hidden:
        out.append(f"\n+{hidden} more INFO rows in reports/block-check.json")
    return out


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.time()
    args = [a for a in argv if not a.startswith("-")]
    if len(args) != 1 or len(args) != len(argv):
        print(__doc__)
        return 2
    project = Path(args[0]).resolve()
    R = Rows()
    try:
        if not project.is_dir():
            raise SetupError(f"{project} is not a directory")
        cli = find_kicad_cli()
        if not cli:
            raise SetupError("kicad-cli not found (set KICAD_CLI or add it to PATH)")
        try:
            import pcbnew  # noqa: F401
        except ImportError:
            raise SetupError("cannot import pcbnew; run with KiCad's bundled python.exe")
        stem = find_stem(project)
        cfg, src = load_config(project)
        pcb_path = project / f"{stem}.kicad_pcb"
        root = export_netlist(cli, project / f"{stem}.kicad_sch")
        comps, nets, power_out = parse_netlist(root)
        board = Board(pcb_path)

        unplaced = [r for r, c in comps.items() if not c["excluded"] and not board.placed(r)]
        if unplaced:
            R.add("B0", "INFO", f"{len(unplaced)} parts not placed", "-", "-",
                  "skipped by the geometric checks: " + short_list(unplaced, 30))
        check_b1(R, comps, nets, board, cfg, src)
        check_b2(R, comps, nets, board, cfg, src)
        check_b3(R, comps, nets, cfg, src)
        check_b4(R, comps, nets, power_out, cfg, src)
        check_b5(R, board, cfg, src)
        check_b6(R, project, stem, pcb_path)
        check_b7(R, project, board)
    except SetupError as exc:
        print(f"block_check: setup problem: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"block_check: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    rows = R.sorted()
    c = R.counts()
    shown, info_n, hidden = [], 0, 0
    for r in rows:
        if r["severity"] == "INFO":
            info_n += 1
            if info_n > MAX_INFO_ROWS:
                hidden += 1
                continue
        shown.append(r)
    summary = f"rows {len(rows)}: errors {c['ERROR']}, warnings {c['WARN']}, info {c['INFO']}; not placed: {len(unplaced)} parts"
    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "block-check.json").write_text(json.dumps({
        "summary": summary, "header": HEADER, "config": cfg, "config_source": src,
        "errors": c["ERROR"], "warnings": c["WARN"], "info": c["INFO"], "not_placed": unplaced,
        "rows": rows}, indent=2), encoding="utf-8")
    text = HEADER + "\n\n" + "\n".join(render(shown, hidden)) + "\n\n" + summary
    (reports / "block-check.md").write_text("# Block check\n\n" + text + "\n", encoding="utf-8")
    print(text)
    print(f"({time.time() - t0:.1f} s)")
    return 1 if c["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
