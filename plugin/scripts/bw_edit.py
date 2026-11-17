"""One-call board edits, with the DRC difference in the answer (run with KiCad's Python).

    python scripts/bw_edit.py . '<ops as JSON>'          edit and save the board
    python scripts/bw_edit.py . @ops.json                 the same, ops from a file
    python scripts/bw_edit.py . '<ops>' --dry-run         do everything but save
    python scripts/bw_edit.py . '{"find": ...}'           look only (no DRC, nothing saved)

Any Python works: the script restarts itself under KiCad's own Python, which reads the board.
The ops are one JSON object or a list of them, run in order. Lengths in mm, angles in degrees,
layers as KiCad names them (F.Cu). A selector is {"kind": ..., "ref": ..., "net": ..., "layer": ...,
"near": [x, y, r]}; ref and net take * and ?.

  {"find": {"kind": "footprint|pad|track|via|zone|net", ...selector, "limit": 100}}
  {"move": "C3" or ["C3", "C4"], "to": [x, y] | "by": [dx, dy], "rot": 90, "side": "F|B"}
  {"set": "R4" or [...], "value": "4.7k", "fields": {"MPN": "..."}}
  {"set": {"kind": "track", "net": "/SDA"}, "width": 0.25}
  {"add": [{"track": {"from": [x, y], "to": [x, y], "width": 0.2, "layer": "F.Cu", "net": "/SDA"}},
           {"via": {"at": [x, y], "net": "/GND", "size": 0.6, "drill": 0.3}}]}
  {"delete": ["ab12cd34", ...]} (ids from find) or {"delete": {"kind": "track", "net": "/SDA"}}
  {"netclass": {"name": "I2C", "track_width": 0.25, "clearance": 0.2, "via_diameter": 0.6,
                "via_drill": 0.3, "nets": ["/I2C_SCL"], "patterns": ["/I2C_*"]}}
  {"rule": {"name": "x", "text": "(rule \"x\" (condition ...) (constraint ...))"}} or {"rule": {"remove": "x"}}
  {"refill": true}
  {"place": {"ref": "C3", "near": "U1.17", "within": 2, "side": "F", "rot": [0, 90, 180, 270]}}
  {"route": ["/LED1", "/LED2"], "width": 0.2, "layers": ["F.Cu", "B.Cu"], "vias": true}

route refuses mains, hazardous and fast nets (boardwright.json safety domains above ES1,
high_speed pairs, and net classes named like USB, HDMI, ETH, PCIe, LVDS, MIPI, DDR, HV or mains):
those are routed by hand and checked. KiCad must not have the board open (its ~*.lck file): close it,
or use the kicad-live tools, which edit the open board.

Answer: one line per op, then the DRC difference against the board as it was: new, fixed, unchanged
errors, and unconnected items. Exit 0 ok, 1 an op failed or new DRC errors, 2 setup problem.
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bw_project import SetupError, load_config, nets_by_class, project_files  # noqa: E402

MM = 1e6
MAX_OUT = 12000
FAST_CLASS = re.compile(r"(?i)usb|hdmi|eth|pcie|lvds|mipi|ddr|serdes|sata|^hv|mains|^ac(_|$)|hazard")


def die(msg):
    print("ERROR: " + msg)
    sys.exit(2)


def f2(x):
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


# ------------------------------------------------------------------ project rules
class Rules:
    def __init__(self, proj: Path, files: dict):
        self.proj, self.files = proj, files
        self.pro_path = files["pro"]
        self.reload()

    def use(self, path: Path):
        """Read the classes from another file (a dry run keeps its changes outside the project)."""
        self.pro_path = path
        self.reload()

    def reload(self):
        pro = json.loads(self.pro_path.read_text("utf-8"))
        ns = pro.get("net_settings") or {}
        self.classes = {c.get("name"): c for c in ns.get("classes") or [] if c.get("name")}
        self.cache = {}

    def class_of(self, net: str) -> str:
        if net not in self.cache:
            by = nets_by_class(self.pro_path, [net])
            hits = [c for c, ns in by.items() if net in ns and c != "Default"]
            self.cache[net] = hits[0] if hits else "Default"
        return self.cache[net]

    def __call__(self, net: str) -> dict:
        d = self.classes.get("Default", {})
        c = self.classes.get(self.class_of(net), d) if net else d
        g = lambda k, dv: c.get(k) if c.get(k) is not None else d.get(k, dv)  # noqa: E731
        return {"width": g("track_width", 0.2), "clearance": g("clearance", 0.2),
                "via_d": g("via_diameter", 0.6), "via_drill": g("via_drill", 0.3)}


def protected_nets(proj: Path, rules: Rules, names: list) -> dict:
    """{net: why} for nets the router must never touch."""
    out = {}
    cfg = load_config(proj)
    try:
        import safety_class
        data, _p, _n = safety_class.analyse(proj)
        for d in data.get("domains", []):
            if d.get("es") and d["es"] != "ES1":
                for n in d["nets"]:
                    out[n] = f"in safety domain {d['name']} ({d['es']})"
    except Exception:
        pass
    for pr in (cfg.get("high_speed") or {}).get("pairs") or []:
        for k in ("p", "n"):
            if pr.get(k):
                out[pr[k]] = f"high-speed pair {pr.get('name', '')}"
    for n in names:
        c = rules.class_of(n)
        if FAST_CLASS.search(c):
            out.setdefault(n, f"net class {c}")
    return out


# ------------------------------------------------------------------ DRC
def find_cli():
    here = Path(sys.executable).resolve().parent
    for n in ("kicad-cli.exe", "kicad-cli"):
        if (here / n).exists():
            return str(here / n)
    from run_gates import find_kicad_cli
    return find_kicad_cli()


def drc(pcb: Path) -> dict | None:
    cli = find_cli()
    if not cli:
        return None
    out = Path(tempfile.mkdtemp(prefix="bwdrc")) / "drc.json"
    subprocess.run([cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", str(out), str(pcb)],
                   capture_output=True)
    try:
        d = json.loads(out.read_text("utf-8-sig"))
    except (OSError, ValueError):
        return None
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)
    errs = {}
    for v in d.get("violations", []):
        if v.get("severity") != "error":
            continue
        key = (v.get("type"), tuple(sorted(re.sub(r"[\d.]+ mm", "", i.get("description", ""))
                                           for i in v.get("items", []))))
        errs[key] = v.get("description", "") + ": " + "; ".join(i.get("description", "") for i in v.get("items", []))
    return {"errors": errs, "unconnected": len(d.get("unconnected_items", []))}


def drc_diff(before, after) -> tuple:
    if not before or not after:
        return ["drc: not run (kicad-cli not found)"], False
    new = [after["errors"][k] for k in after["errors"] if k not in before["errors"]]
    fixed = [k for k in before["errors"] if k not in after["errors"]]
    same = len(after["errors"]) - len(new)
    lines = [f"drc: {len(new)} new error(s), {len(fixed)} fixed, {same} unchanged; "
             f"unconnected {before['unconnected']} -> {after['unconnected']}"]
    lines += ["  new: " + n[:220] for n in new[:12]]
    if len(new) > 12:
        lines.append(f"  ... {len(new) - 12} more")
    return lines, bool(new)


# ------------------------------------------------------------------ board access
class Board:
    def __init__(self, pcb: Path):
        import pcbnew
        self.pcbnew = pcbnew
        self.path = pcb
        self.b = pcbnew.LoadBoard(str(pcb))
        self.fps = {fp.GetReference(): fp for fp in self.b.GetFootprints()}
        self.changed = False
        self.copper_changed = False

    def P(self, x, y):
        return self.pcbnew.VECTOR2I(int(round(x * MM)), int(round(y * MM)))

    def refs(self, sel) -> list:
        pats = [sel] if isinstance(sel, str) else list(sel)
        out = [r for r in sorted(self.fps, key=nat) if any(fnmatch.fnmatchcase(r, p) for p in pats)]
        missing = [p for p in pats if not any(ch in p for ch in "*?") and p not in self.fps]
        if missing:
            raise ValueError("no footprint " + ", ".join(missing))
        return out

    def pad(self, spec: str):
        ref, _, num = spec.partition(".")
        fp = self.fps.get(ref)
        p = fp.FindPadByNumber(num) if fp else None
        if p is None:
            raise ValueError("no pad " + spec)
        return p

    def items(self, sel: dict) -> list:
        """(kind, item) pairs matching a selector."""
        pc = self.pcbnew
        kind = sel.get("kind", "footprint")
        out = []
        if kind == "footprint":
            out = [("footprint", fp) for r, fp in sorted(self.fps.items(), key=lambda kv: nat(kv[0]))]
        elif kind == "pad":
            out = [("pad", p) for r, fp in sorted(self.fps.items(), key=lambda kv: nat(kv[0])) for p in fp.Pads()]
        elif kind in ("track", "via"):
            for t in self.b.GetTracks():
                is_via = t.Type() == pc.PCB_VIA_T
                if (kind == "via") == is_via:
                    out.append((kind, t))
        elif kind == "zone":
            out = [("zone", z) for z in self.b.Zones()]
        elif kind == "net":
            out = [("net", n) for n in sorted(self.b.GetNetsByName().values(), key=lambda n: nat(n.GetNetname()))
                   if n.GetNetCode() > 0]
        else:
            raise ValueError("unknown kind " + kind)
        res = []
        for k, it in out:
            if "ref" in sel:
                ref = it.GetReference() if k == "footprint" else (
                    it.GetParentFootprint().GetReference() if k == "pad" else None)
                if ref is None or not fnmatch.fnmatchcase(ref, sel["ref"]):
                    continue
            if "net" in sel:
                name = it.GetNetname()
                if not fnmatch.fnmatchcase(name, sel["net"]):
                    continue
            if "layer" in sel and k in ("track", "footprint", "pad", "zone"):
                lid = self.b.GetLayerID(sel["layer"])
                if not it.IsOnLayer(lid):
                    continue
            if "near" in sel and k != "net":
                x, y, r = sel["near"]
                bb = it.GetBoundingBox()
                dx = max(bb.GetLeft() / MM - x, x - bb.GetRight() / MM, 0)
                dy = max(bb.GetTop() / MM - y, y - bb.GetBottom() / MM, 0)
                if math.hypot(dx, dy) > r:
                    continue
            res.append((k, it))
        return res

    def row(self, k, it) -> str:
        pc = self.pcbnew
        if k == "footprint":
            p = it.GetPosition()
            return (f"{it.GetReference()} {it.GetValue()} {it.GetFPID().GetLibItemName()} "
                    f"{'F' if it.GetLayer() == pc.F_Cu else 'B'} {f2(p.x / MM)} {f2(p.y / MM)} "
                    f"rot {f2(it.GetOrientationDegrees())}")
        if k == "pad":
            p, s = it.GetPosition(), it.GetSize(pc.F_Cu) if hasattr(it, "GetSize") else None
            size = f"{f2(s.x / MM)}x{f2(s.y / MM)}" if s is not None else "?"
            lay = "".join(l for l, lid in (("F", pc.F_Cu), ("B", pc.B_Cu)) if it.IsOnLayer(lid))
            return (f"{it.GetParentFootprint().GetReference()}.{it.GetNumber()} {it.GetNetname() or '-'} "
                    f"{f2(p.x / MM)} {f2(p.y / MM)} size {size} rot {f2(it.GetOrientationDegrees())} {lay}")
        if k == "track":
            s, e = it.GetStart(), it.GetEnd()
            return (f"{uid(it)} {it.GetNetname()} {self.b.GetLayerName(it.GetLayer())} w {f2(it.GetWidth() / MM)} "
                    f"{f2(s.x / MM)},{f2(s.y / MM)} -> {f2(e.x / MM)},{f2(e.y / MM)}")
        if k == "via":
            p = it.GetPosition()
            return (f"{uid(it)} {it.GetNetname()} {f2(p.x / MM)} {f2(p.y / MM)} "
                    f"d {f2(it.GetWidth(pc.F_Cu) / MM)} drill {f2(it.GetDrillValue() / MM)}")
        if k == "zone":
            bb = it.GetBoundingBox()
            what = "keepout" if it.GetIsRuleArea() else it.GetNetname()
            return (f"{uid(it)} {it.GetZoneName() or '-'} {what} "
                    f"{','.join(self.b.GetLayerName(l) for l in it.GetLayerSet().Seq())} prio {it.GetAssignedPriority()} "
                    f"bbox {f2(bb.GetLeft() / MM)},{f2(bb.GetTop() / MM)} {f2(bb.GetRight() / MM)},{f2(bb.GetBottom() / MM)}")
        if k == "net":
            code = it.GetNetCode()
            pads = [f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}"
                    for fp in self.fps.values() for p in fp.Pads() if p.GetNetCode() == code]
            ln = sum(t.GetLength() for t in self.b.GetTracks() if t.GetNetCode() == code
                     and t.Type() != pc.PCB_VIA_T) / MM
            return f"{it.GetNetname()} {it.GetNetClassName()} pads {len(pads)} track {f2(ln)} mm: {' '.join(pads[:10])}"
        return str(it)


def uid(it) -> str:
    return it.m_Uuid.AsString()[:8]


def nat(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ------------------------------------------------------------------ ops
def op_find(bd: Board, a, ctx):
    sel = a if isinstance(a, dict) else {"kind": "footprint", "ref": a}
    rows = bd.items(sel)
    limit = int(sel.get("limit", 100))
    out = [f"find {sel.get('kind', 'footprint')}: {len(rows)}"]
    out += ["  " + bd.row(k, it) for k, it in rows[:limit]]
    if len(rows) > limit:
        out.append(f"  ... {len(rows) - limit} more (raise limit, or narrow the selector)")
    return out


def op_move(bd: Board, a, ctx):
    pc = bd.pcbnew
    out = []
    for r in bd.refs(a["move"]):
        fp = bd.fps[r]
        if "to" in a:
            fp.SetPosition(bd.P(*a["to"]))
        elif "by" in a:
            p = fp.GetPosition()
            fp.SetPosition(bd.P(p.x / MM + a["by"][0], p.y / MM + a["by"][1]))
        if "side" in a and (a["side"] == "B") != (fp.GetLayer() == pc.B_Cu):
            fp.Flip(fp.GetPosition(), pc.FLIP_DIRECTION_LEFT_RIGHT if hasattr(pc, "FLIP_DIRECTION_LEFT_RIGHT") else False)
        if "rot" in a:
            fp.SetOrientationDegrees(float(a["rot"]))
        p = fp.GetPosition()
        out.append(f"move {r}: at {f2(p.x / MM)},{f2(p.y / MM)} rot {f2(fp.GetOrientationDegrees())}")
    bd.changed = bd.copper_changed = True
    return out


def op_set(bd: Board, a, ctx):
    target = a["set"]
    out = []
    if isinstance(target, dict):
        items = bd.items(target)
        if not items:
            raise ValueError("set: the selector matched nothing")
        for k, it in items:
            if "width" in a and k == "track":
                it.SetWidth(int(a["width"] * MM))
            if "layer" in a and k == "track":
                it.SetLayer(bd.b.GetLayerID(a["layer"]))
            if "net" in a and k in ("track", "via"):
                it.SetNet(bd.b.FindNet(a["net"]))
        out.append(f"set {len(items)} {items[0][0]}(s)")
        bd.changed = bd.copper_changed = True
        return out
    for r in bd.refs(target):
        fp = bd.fps[r]
        if "value" in a:
            fp.SetValue(str(a["value"]))
        for name, val in (a.get("fields") or {}).items():
            fp.SetField(name, str(val))
        out.append(f"set {r}: " + ", ".join(k for k in a if k != "set"))
    bd.changed = True
    out.append("  note: footprint fields on the board only; the schematic keeps its own (update it there too)")
    return out


def _corridor_check(bd: Board, proj: Path):
    """In routing plan mode: inside(net, points, layers) raises ValueError unless every point lies in the
    net's corridor on one of the layers (any corridor layer when layers is None) or within 1 mm of the
    net's own pads. Without plan mode, or for a net with no corridor (plane nets), it accepts everything."""
    import routing_plan
    if not routing_plan.mode_on(proj):
        return lambda net, pts, layers: None
    pc = bd.pcbnew
    plan = routing_plan.load(proj)
    cache = {}

    def inside(net, pts, layers):
        c = routing_plan.corridor_for(plan, net) if net else None
        if c is None:
            return
        if net not in cache:
            cache[net] = routing_plan.corridor_polys(bd.b, c)
        polys = cache[net]
        lids = [bd.b.GetLayerID(n) for n in layers] if layers else list(polys)
        pads = [p for fp in bd.fps.values() for p in fp.Pads() if p.GetNetname() == net]
        for x, y in pts:
            pt = bd.P(x, y)
            if any(polys.get(lid) is not None and polys[lid].Contains(pt) for lid in lids):
                continue
            near = False
            for p in pads:
                for lid in (lids or [pc.F_Cu]):
                    if not p.IsOnLayer(lid):
                        continue
                    ps = pc.SHAPE_POLY_SET()
                    p.TransformShapeToPolygon(ps, lid, int(1.0 * MM), int(0.005 * MM), pc.ERROR_OUTSIDE)
                    if ps.OutlineCount() and ps.Contains(pt):
                        near = True
                        break
                if near:
                    break
            if not near:
                raise ValueError(f"add: point {f2(x)},{f2(y)} of {net} is outside its corridor {c['id']} "
                                 "and not within 1 mm of the net's pads (routing plan mode)")
    return inside


def op_add(bd: Board, a, ctx):
    pc = bd.pcbnew
    out = []
    import routing_plan
    planned = routing_plan.gate(ctx["proj"], sorted({(i.get("track") or i.get("via") or {}).get("net", "")
                                                     for i in a["add"]} - {""}))
    if planned:
        raise ValueError("routing plan: " + "; ".join(f"{n}: {w}" for n, w in planned.items()))
    inside = _corridor_check(bd, ctx["proj"])
    for item in a["add"]:
        if "track" in item:
            t = item["track"]
            net = bd.b.FindNet(t["net"]) if t.get("net") else None
            if t.get("net") and net is None:
                raise ValueError("no net " + t["net"])
            inside(t.get("net", ""), [t["from"], t["to"]], [t.get("layer", "F.Cu")])
            tr = pc.PCB_TRACK(bd.b)
            tr.SetStart(bd.P(*t["from"]))
            tr.SetEnd(bd.P(*t["to"]))
            tr.SetWidth(int((t.get("width") or ctx["rules"](t.get("net", ""))["width"]) * MM))
            tr.SetLayer(bd.b.GetLayerID(t.get("layer", "F.Cu")))
            if net:
                tr.SetNet(net)
            bd.b.Add(tr)
            out.append(f"add track {uid(tr)} {t.get('net', '')}")
        elif "via" in item:
            v = item["via"]
            net = bd.b.FindNet(v["net"]) if v.get("net") else None
            inside(v.get("net", ""), [v["at"]], None)
            r = ctx["rules"](v.get("net", ""))
            via = pc.PCB_VIA(bd.b)
            via.SetPosition(bd.P(*v["at"]))
            via.SetWidth(int((v.get("size") or r["via_d"]) * MM))
            via.SetDrill(int((v.get("drill") or r["via_drill"]) * MM))
            if net:
                via.SetNet(net)
            bd.b.Add(via)
            out.append(f"add via {uid(via)} {v.get('net', '')}")
        else:
            raise ValueError("add: each item is {track: ...} or {via: ...}")
    bd.changed = bd.copper_changed = True
    return out


def op_delete(bd: Board, a, ctx):
    target = a["delete"]
    if isinstance(target, dict):
        if set(target) <= {"kind"}:
            raise ValueError("delete: a selector must say more than its kind")
        victims = [it for k, it in bd.items(target) if k in ("track", "via", "zone")]
    else:
        ids = set(target)
        victims = [t for t in list(bd.b.GetTracks()) + list(bd.b.Zones()) if uid(t) in ids]
        missing = ids - {uid(v) for v in victims}
        if missing:
            raise ValueError("delete: no item " + ", ".join(sorted(missing)))
    for v in victims:
        bd.b.Remove(v)
    bd.changed = bd.copper_changed = True
    return [f"delete: {len(victims)} item(s)"]


def op_netclass(bd: Board, a, ctx):
    nc = a["netclass"]
    name = nc.get("name")
    if not name:
        raise ValueError("netclass needs a name")
    f = ctx["files"]
    pro = ctx.get("pro_json") or json.loads(f["pro"].read_text("utf-8"))
    ns = pro.setdefault("net_settings", {})
    classes = ns.setdefault("classes", [])
    default = next((c for c in classes if c.get("name") == "Default"), {})
    cls = next((c for c in classes if c.get("name") == name), None)
    if cls is None:
        cls = {k: v for k, v in default.items() if k not in ("name", "priority")}
        cls["name"] = name
        cls["priority"] = max([c.get("priority", 0) for c in classes if c.get("name") != "Default"] + [-1]) + 1
        classes.append(cls)
    for k in ("track_width", "clearance", "via_diameter", "via_drill", "diff_pair_width", "diff_pair_gap"):
        if k in nc:
            cls[k] = nc[k]
    pats = ns.setdefault("netclass_patterns", []) or []
    ns["netclass_patterns"] = pats
    for p in list(nc.get("patterns") or []) + list(nc.get("nets") or []):
        if not any(x.get("pattern") == p and x.get("netclass") == name for x in pats):
            pats[:] = [x for x in pats if x.get("pattern") != p]
            pats.append({"netclass": name, "pattern": p})
    ctx["pro_json"] = pro
    if ctx.get("dry"):                       # a dry run writes nothing: the rules read a temp copy outside the project
        if "tmp_pro" not in ctx:
            ctx["tmp_pro"] = Path(tempfile.mkdtemp(prefix="bwpro")) / "dry.kicad_pro"
        ctx["tmp_pro"].write_text(json.dumps(pro, indent=2) + "\n", "utf-8")
        ctx["rules"].use(ctx["tmp_pro"])
    else:
        f["pro"].write_text(json.dumps(pro, indent=2) + "\n", "utf-8")
        ctx["rules"].reload()
    missing = [n for n in nc.get("nets") or [] if bd.b.FindNet(n) is None]
    out = [f"netclass {name}" + (" (dry run, would write the .kicad_pro)" if ctx.get("dry") else "") + ": " + ", ".join(f"{k} {nc[k]}" for k in nc if k not in ("name", "nets", "patterns"))
           + f"; {len(nc.get('nets') or []) + len(nc.get('patterns') or [])} pattern(s)"]
    if missing:
        out.append("  warning: no such net on the board: " + ", ".join(missing))
    return out


def sexpr_block(text: str, start: int) -> int:
    depth = 0
    i = start
    in_str = False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced rules file")


def op_rule(bd: Board, a, ctx):
    r = a["rule"]
    dru = ctx["files"]["dru"]
    text = ctx["dru_text"] if "dru_text" in ctx else (dru.read_text("utf-8") if dru.exists() else "(version 1)\n")
    name = r.get("remove") or r.get("name")
    if not name:
        raise ValueError("rule needs a name (or remove)")
    m = re.search(r'\(rule\s+"?' + re.escape(name) + r'"?[\s)]', text)
    if m:
        end = sexpr_block(text, m.start())
        text = text[:m.start()].rstrip() + "\n" + text[end:].lstrip("\n")
    if "remove" not in r:
        body = r.get("text") or ""
        if not body.strip().startswith("(rule"):
            raise ValueError('rule.text must be a whole (rule "name" ...) block')
        text = text.rstrip() + "\n\n" + body.strip() + "\n"
    ctx["dru_text"] = text
    if not ctx.get("dry"):
        dru.write_text(text, "utf-8")
    return [f"rule {name}: " + ("removed" if "remove" in r else ("replaced" if m else "added"))
            + (" (dry run, would write the .kicad_dru)" if ctx.get("dry") else "")]


def op_refill(bd: Board, a, ctx):
    ctx["refill"] = True
    return ["refill: zones will be refilled before saving"]


def overlaps(a, b, clearance_mm) -> bool:
    """Do two polygon sets touch, overlap or come closer than the clearance? (KiCad's boolean
    intersection is unreliable from Python; edge collision plus a containment test is not.)"""
    import pcbnew as pc
    clr = int(clearance_mm * MM)
    for i in range(b.OutlineCount()):
        if a.Collide(b.Outline(i), clr):
            return True
    for i in range(a.OutlineCount()):
        if b.Collide(a.Outline(i), clr):
            return True
    if a.OutlineCount() and b.OutlineCount():
        if b.Contains(a.Outline(0).CPoint(0)) or a.Contains(b.Outline(0).CPoint(0)):
            return True
    del pc
    return False


def op_place(bd: Board, a, ctx):
    q = a["place"]
    fp = bd.fps.get(q["ref"])
    if fp is None:
        raise ValueError("no footprint " + q["ref"])
    target = bd.pad(q["near"])
    within = float(q.get("within", 3))
    rots = q.get("rot", [0, 90, 180, 270])
    rots = rots if isinstance(rots, list) else [rots]
    side = q.get("side", "F")
    start = (fp.GetPosition(), fp.GetOrientationDegrees(), fp.GetLayer())
    try:
        return _place(bd, ctx, q, fp, target, within, rots, side)
    except Exception:
        # put the part back exactly where it was (side, position, rotation)
        if fp.GetLayer() != start[2]:
            fp.Flip(fp.GetPosition(), False)
        fp.SetPosition(start[0])
        fp.SetOrientationDegrees(start[1])
        fp.BuildCourtyardCaches()
        raise


def _place(bd: Board, ctx, q, fp, target, within, rots, side):
    pc = bd.pcbnew
    if (side == "B") != (fp.GetLayer() == pc.B_Cu):
        fp.Flip(fp.GetPosition(), False)
    cy_layer = pc.B_CrtYd if side == "B" else pc.F_CrtYd
    others = []
    for r, o in bd.fps.items():
        if o is fp:
            continue
        c = o.GetCourtyard(cy_layer)
        if c.OutlineCount():
            others.append(c)
    outline = pc.SHAPE_POLY_SET()
    bd.b.GetBoardPolygonOutlines(outline, True)
    ds = bd.b.GetDesignSettings()
    inner = pc.SHAPE_POLY_SET(outline)
    inner.Inflate(-int(ds.m_CopperEdgeClearance), pc.CORNER_STRATEGY_ROUND_ALL_CORNERS, int(0.005 * MM))
    mate = [p for p in fp.Pads() if p.GetNetCode() and p.GetNetCode() == target.GetNetCode()]
    rules = ctx["rules"]
    copper = []
    for t in bd.b.GetTracks():
        copper.append(t)
    for o in bd.fps.values():
        if o is not fp:
            copper.extend(o.Pads())
    tx, ty = target.GetPosition().x / MM, target.GetPosition().y / MM
    best = None
    step = 0.05
    reach = within + 4.0
    n = int(reach / step)
    cand = []
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            x, y = tx + i * step, ty + j * step
            if math.hypot(x - tx, y - ty) <= reach:
                cand.append((math.hypot(x - tx, y - ty), x, y))
    cand.sort()
    for _d, x, y in cand:
        for rot in rots:
            fp.SetPosition(bd.P(x, y))
            fp.SetOrientationDegrees(float(rot))
            mp = mate[0] if mate else None
            ref_pt = mp.GetPosition() if mp else fp.GetPosition()
            dist = math.hypot(ref_pt.x / MM - tx, ref_pt.y / MM - ty)
            if dist > within or (best and dist >= best[0]):
                continue
            fp.BuildCourtyardCaches()
            cy = fp.GetCourtyard(cy_layer)
            if cy.OutlineCount() == 0:
                continue
            ok = not any(overlaps(cy, o, 0) for o in others)
            if not ok:
                continue
            bb = cy.BBox()
            for cx, cy_ in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                            (bb.GetLeft(), bb.GetBottom()), (bb.GetRight(), bb.GetBottom())):
                if not inner.Contains(pc.VECTOR2I(int(cx), int(cy_))):
                    ok = False
                    break
            if not ok:
                continue
            for p in fp.Pads():
                lid = pc.B_Cu if side == "B" else pc.F_Cu
                mine = rules(p.GetNetname())
                ps = pc.SHAPE_POLY_SET()
                p.TransformShapeToPolygon(ps, lid, 0, int(0.005 * MM), pc.ERROR_OUTSIDE)
                for c in copper:
                    if not c.IsOnLayer(lid) or (c.GetNetCode() and c.GetNetCode() == p.GetNetCode()):
                        continue
                    clr = max(mine["clearance"], rules(c.GetNetname())["clearance"])
                    cs = pc.SHAPE_POLY_SET()
                    c.TransformShapeToPolygon(cs, lid, 0, int(0.005 * MM), pc.ERROR_OUTSIDE)
                    if overlaps(ps, cs, clr):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                best = (dist, x, y, rot)
        if best and _d > best[0] + 3.0:
            break
    if not best:
        raise ValueError(f"place: no free spot for {q['ref']} within {within} mm of {q['near']} "
                         "(move other parts, or allow more distance)")
    dist, x, y, rot = best
    fp.SetPosition(bd.P(x, y))
    fp.SetOrientationDegrees(float(rot))
    bd.changed = bd.copper_changed = True
    return [f"place {q['ref']}: at {f2(x)},{f2(y)} rot {f2(rot)} {side}; "
            f"{'pad ' + mate[0].GetNumber() if mate else 'centre'} {f2(dist)} mm from {q['near']}"]


def op_route(bd: Board, a, ctx):
    import bw_router
    nets = a["route"] if isinstance(a["route"], list) else [a["route"]]
    names = []
    for n in nets:
        hits = [x for x in bd.b.GetNetsByName().keys() if fnmatch.fnmatchcase(str(x), n)] if any(c in n for c in "*?") else [n]
        names += [str(h) for h in hits]
    import routing_plan
    prot = protected_nets(ctx["proj"], ctx["rules"], names)
    prot = {n: w + " (route it by hand and check it)" for n, w in prot.items()}
    for n, why in routing_plan.gate(ctx["proj"], names).items():
        prot.setdefault(n, why)
    plan = routing_plan.load(ctx["proj"]) if routing_plan.mode_on(ctx["proj"]) else None
    polys = {}

    def allowed(net):
        if plan is None:
            return None
        if net not in polys:
            c = routing_plan.corridor_for(plan, net)
            polys[net] = routing_plan.corridor_polys(bd.b, c) if c else {}
        return polys[net]
    refused = [n for n in names if n in prot]
    names = [n for n in names if n not in prot]
    out = [f"route refused {n}: {prot[n]}" for n in refused]
    layers = a.get("layers") or ["F.Cu", "B.Cu"]
    if plan is not None and len(names) == 1:
        c = routing_plan.corridor_for(plan, names[0])
        layers = c.get("layers") or layers
    router = bw_router.Router(bd.b, ctx["rules"], layers=layers, pitch_mm=float(a.get("grid", 0.1)),
                              vias=bool(a.get("vias", True)), allowed=allowed)
    failed = bool(refused)
    for n in names:
        res = router.route_net(n, a.get("width"))
        if res.get("failed"):
            failed = True
            out.append(f"route {n}: FAILED {res['failed']}")
        elif res.get("already_connected"):
            out.append(f"route {n}: already connected")
        else:
            out.append(f"route {n}: {res['tracks']} track(s), {res['vias']} via(s), {res['length_mm']} mm "
                       f"at {res['width_mm']} mm on {','.join(res['layers'])}")
    if router.added:
        bd.changed = bd.copper_changed = True
        ctx["refill"] = True
        ctx["segments"] = [
            {"start_x_mm": t.GetStart().x / MM, "start_y_mm": t.GetStart().y / MM, "end_x_mm": t.GetEnd().x / MM,
             "end_y_mm": t.GetEnd().y / MM, "layer": bd.b.GetLayerName(t.GetLayer()),
             "width_mm": t.GetWidth() / MM, "net": t.GetNetname()}
            for t in router.added if t.Type() != bd.pcbnew.PCB_VIA_T]
    ctx["failed"] = ctx.get("failed") or failed
    return out


OPS = {"find": op_find, "move": op_move, "set": op_set, "add": op_add, "delete": op_delete,
       "netclass": op_netclass, "rule": op_rule, "refill": op_refill, "place": op_place, "route": op_route}


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    proj = Path(argv[0]).resolve()
    raw = argv[1]
    dry = "--dry-run" in argv
    try:
        text = Path(raw[1:]).read_text("utf-8") if raw.startswith("@") else raw
        ops = json.loads(text)
    except (OSError, ValueError) as exc:
        die(f"ops are not valid JSON: {exc}")
    ops = ops if isinstance(ops, list) else [ops]
    try:
        files = project_files(proj)
    except SetupError as exc:
        die(str(exc))
    for o in ops:
        if not isinstance(o, dict) or not (set(o) & set(OPS)):
            die(f"unknown op {json.dumps(o)[:80]}; ops: {', '.join(OPS)}")
    read_only = all(set(o) & set(OPS) == {"find"} for o in ops)
    pcb = files["pcb"]
    lck = pcb.parent / f"~{pcb.name}.lck"
    if lck.exists() and not read_only and not dry:
        print(f"KiCad has {pcb.name} open (found {lck.name}). Close the board in KiCad, or edit the open board "
              "with the kicad-live tools; nothing was changed. A --dry-run still answers, and for route it lists "
              "the segments to send with pcb_add_tracks.")
        return 2
    rules = Rules(proj, files)
    ctx = {"proj": proj, "files": files, "rules": rules, "dry": dry}
    # the project files as they were: a failed batch puts them back (all or nothing)
    saved = {k: (files[k].read_bytes() if files[k].exists() else None) for k in ("pro", "dru")}
    before = None if read_only or dry or "--no-drc" in argv else drc(pcb)
    bd = Board(pcb)
    out, failed = [], False
    try:
        for o in ops:
            name = next(k for k in o if k in OPS)
            try:
                out += OPS[name](bd, o if name != "find" else o["find"], ctx)
            except (ValueError, KeyError, TypeError) as exc:
                out.append(f"{name}: FAILED {exc}")
                failed = True
                break
    finally:
        if ctx.get("tmp_pro"):
            shutil.rmtree(ctx["tmp_pro"].parent, ignore_errors=True)
    failed = failed or ctx.get("failed", False)
    if failed and not read_only and not dry:
        for k, data in saved.items():
            if data is None:
                if files[k].exists():
                    files[k].unlink()
            elif not files[k].exists() or files[k].read_bytes() != data:
                files[k].write_bytes(data)
        out.append("nothing was changed: one op failed, so the board and the project files are as they were")
        print("\n".join(out)[:MAX_OUT])
        return 1
    if read_only:
        text = "\n".join(out)
        print(text[:MAX_OUT] + ("\n... (cut: narrow the selector)" if len(text) > MAX_OUT else ""))
        return 0
    if dry:
        out.append("dry run: nothing saved")
        if ctx.get("segments"):
            out.append("segments for pcb_add_tracks: " + json.dumps(ctx["segments"]))
        print("\n".join(out))
        return 1 if failed else 0
    if bd.changed or ctx.get("refill"):
        if ctx.get("refill"):
            filler = bd.pcbnew.ZONE_FILLER(bd.b)
            filler.Fill(bd.b.Zones())
        bd.b.Save(str(pcb))
        out.append(f"saved {pcb.name}")
    after = None if "--no-drc" in argv else drc(pcb)
    lines, new_errors = drc_diff(before, after) if after is not None or before is not None else (["drc: skipped"], False)
    out += lines
    print("\n".join(out)[:MAX_OUT])
    return 1 if failed or new_errors else 0


if __name__ == "__main__":
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    import kicad_python  # under any Python: rerun with KiCad's own, which has pcbnew
    kicad_python.ensure(__file__)
    sys.exit(main(sys.argv[1:]))
