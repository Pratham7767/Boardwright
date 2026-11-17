"""Routing plan mode: corridors proposed by Claude, approved by the designer, routed only inside.

    python scripts/routing_plan.py . propose @plan.json   save a plan (every corridor: proposed)
    python scripts/routing_plan.py . draw                 draw the corridors on User.4 in the board
    python scripts/routing_plan.py . show                            the plan as a table
    python scripts/routing_plan.py . verify               is every track of a planned net inside its corridor?

A mode the designer chooses: "routing_plan": true in boardwright.json. Off by default.

plan.json: {"planes": [{"layer": "In1.Cu", "net": "/GND", "role": "reference for F.Cu"}],
            "corridors": [{"id": "c1", "nets": ["/I2C_SDA", "/I2C_SCL"], "layers": ["F.Cu"],
                           "width_mm": 0.2, "half_width_mm": 1.0, "impedance_ohm": null,
                           "path": [[x, y], [x, y], ...], "why": "short run, no other signals"}]}

Only the designer approves or rejects a corridor: they type `/boardwright:pcb-plan approve c1 c3`
(or `reject c2`, `approve all`) and the plugin's prompt hook records it from what they typed. There is
no command for Claude to approve, and the plan file may not be edited by hand (the edit hook refuses).
A corridor proposed again with a different path or layers goes back to "proposed".

The plan lives in reports/routing-plan.json and reports/routing-plan.md. bw_edit's route and add ops,
and the live pcb_add_tracks tool, refuse a planned-mode net that has no approved corridor, and route
inside its corridor. Exit 0 ok, 1 a check failed, 2 setup problem.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bw_project import load_config, md_table  # noqa: E402

MM = 1e6
PLAN_LAYER = "User.4"
TAG = "bw-plan"


def plan_path(proj: Path) -> Path:
    return proj / "reports" / "routing-plan.json"


def mode_on(proj: Path) -> bool:
    try:
        return bool(load_config(proj).get("routing_plan"))
    except Exception:
        return False


def load(proj: Path) -> dict:
    p = plan_path(proj)
    if not p.is_file():
        return {"version": 1, "planes": [], "corridors": [], "log": []}
    return json.loads(p.read_text("utf-8"))


def save(proj: Path, plan: dict) -> None:
    p = plan_path(proj)
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", "utf-8")
    rows = [[c["id"], c["status"], ", ".join(c["nets"]), ",".join(c.get("layers") or []), c.get("width_mm", ""),
             c.get("impedance_ohm") or "", c.get("why", "")] for c in plan["corridors"]]
    md = ["# Routing plan", "",
          "Proposed by Claude. Only the designer approves: `/boardwright:pcb-plan approve c1 c2`, `reject c3`, "
          "`approve all`. Corridors are drawn on the User.4 layer.", ""]
    if plan.get("planes"):
        md += ["## Reference planes", ""] + md_table(["layer", "net", "role"],
                                                      [[p["layer"], p["net"], p.get("role", "")] for p in plan["planes"]]) + [""]
    md += ["## Corridors", ""] + md_table(["id", "status", "nets", "layers", "width mm", "impedance", "why"], rows)
    if plan.get("log"):
        md += ["", "## Decisions", ""] + [f"- {l}" for l in plan["log"][-30:]]
    (p.parent / "routing-plan.md").write_text("\n".join(md) + "\n", "utf-8")


def decide(proj: Path, words: list, said: str) -> str:
    """Record the designer's decision. Called only by the prompt hook, from what the user typed."""
    if not words or words[0] not in ("approve", "reject"):
        return ""
    plan = load(proj)
    ids = [w.strip(",") for w in words[1:] if w.strip(",")]
    known = {c["id"]: c for c in plan["corridors"]}
    if ids == ["all"]:
        ids = [c["id"] for c in plan["corridors"] if c["status"] == "proposed"]
    bad = [i for i in ids if i not in known]
    status = "approved" if words[0] == "approve" else "rejected"
    stamp = time.strftime("%Y-%m-%d %H:%M")
    for i in ids:
        if i in known:
            known[i]["status"] = status
            known[i]["decided_at"] = stamp
            known[i]["decided_by"] = "designer"
    if ids and set(ids) - set(bad):
        plan["log"].append(f"{stamp} designer: {status} {', '.join(i for i in ids if i in known)} (typed: {said[:80]})")
        save(proj, plan)
    msg = f"Routing plan: {status} {', '.join(i for i in ids if i in known) or 'nothing'} (recorded by the plugin "\
          "from the designer's own words)."
    if bad:
        msg += " Unknown corridor id(s): " + ", ".join(bad) + "."
    return msg


def corridor_for(plan: dict, net: str) -> dict | None:
    for c in plan.get("corridors", []):
        if net in c.get("nets", []):
            return c
    return None


def gate(proj: Path, nets: list) -> dict:
    """{net: why} for nets planned mode forbids routing now (no approved corridor)."""
    if not mode_on(proj):
        return {}
    plan = load(proj)
    plane_nets = {p.get("net") for p in plan.get("planes", [])}
    out = {}
    for n in nets:
        if n in plane_nets:                      # pours and stitching vias of a plane net are not corridor work
            continue
        c = corridor_for(plan, n)
        if c is None:
            out[n] = "routing plan mode is on and this net is in no corridor: propose one first"
        elif c["status"] != "approved":
            out[n] = f"its corridor {c['id']} is {c['status']}, not approved by the designer"
    return out


def corridor_polys(board, c: dict):
    """{layer id: SHAPE_POLY_SET} of the corridor band on each of its layers."""
    import pcbnew
    out = {}
    for ln in c.get("layers") or []:
        lid = board.GetLayerID(ln)
        ps = pcbnew.SHAPE_POLY_SET()
        pts = c.get("path") or []
        for a, b in zip(pts, pts[1:]):
            s = pcbnew.PCB_SHAPE(board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(pcbnew.VECTOR2I(int(a[0] * MM), int(a[1] * MM)))
            s.SetEnd(pcbnew.VECTOR2I(int(b[0] * MM), int(b[1] * MM)))
            s.SetWidth(int(2 * c.get("half_width_mm", 1.0) * MM))
            s.SetLayer(lid)
            s.TransformShapeToPolygon(ps, lid, 0, int(0.005 * MM), pcbnew.ERROR_OUTSIDE)
        ps.Simplify()
        out[lid] = ps
    return out


def cmd_propose(proj: Path, src: str) -> int:
    text = Path(src[1:]).read_text("utf-8") if src.startswith("@") else src
    new = json.loads(text)
    plan = load(proj)
    old = {c["id"]: c for c in plan["corridors"]}
    out = []
    for c in new.get("corridors", []):
        for k in ("id", "nets", "layers", "path"):
            if not c.get(k):
                print(f"corridor {c.get('id', '?')}: needs '{k}'")
                return 2
        prev = old.get(c["id"])
        same = prev and prev.get("path") == c["path"] and prev.get("layers") == c["layers"] and \
            prev.get("nets") == c["nets"] and prev.get("half_width_mm") == c.get("half_width_mm")
        c["status"] = prev["status"] if same else "proposed"
        for k in ("decided_at", "decided_by"):
            if same and prev.get(k):
                c[k] = prev[k]
        old[c["id"]] = c
        out.append(f"{c['id']}: {c['status']}")
    plan["corridors"] = list(old.values())
    if "planes" in new:
        plan["planes"] = new["planes"]
    plan["log"].append(time.strftime("%Y-%m-%d %H:%M") + " Claude proposed " + ", ".join(out))
    save(proj, plan)
    print("saved reports/routing-plan.md: " + "; ".join(out))
    print("Ask the designer to look at it (drawn on User.4 after `draw`) and to type "
          "/boardwright:pcb-plan approve <ids> or reject <ids>. Route nothing until then.")
    return 0


def cmd_draw(proj: Path) -> int:
    import kicad_python
    kicad_python.ensure(__file__)
    import glob
    import pcbnew
    pcb = Path(glob.glob(str(proj / "*.kicad_pcb"))[0])
    if (pcb.parent / f"~{pcb.name}.lck").exists():
        print("KiCad has the board open: close it to draw the plan, or look at reports/routing-plan.md.")
        return 2
    b = pcbnew.LoadBoard(str(pcb))
    lid = b.GetLayerID(PLAN_LAYER)
    for d in list(b.GetDrawings()):
        if d.GetLayer() == lid:
            b.Remove(d)
    plan = load(proj)
    n = 0
    for c in plan["corridors"]:
        if c["status"] == "rejected":
            continue
        pts = c["path"]
        for a, b_ in zip(pts, pts[1:]):
            s = pcbnew.PCB_SHAPE(b)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(pcbnew.VECTOR2I(int(a[0] * MM), int(a[1] * MM)))
            s.SetEnd(pcbnew.VECTOR2I(int(b_[0] * MM), int(b_[1] * MM)))
            s.SetWidth(int(2 * c.get("half_width_mm", 1.0) * MM))
            s.SetLayer(lid)
            b.Add(s)
            n += 1
        t = pcbnew.PCB_TEXT(b)
        t.SetText(f"{c['id']} {c['status']}: {' '.join(c['nets'])} ({','.join(c['layers'])})")
        t.SetPosition(pcbnew.VECTOR2I(int(pts[0][0] * MM), int(pts[0][1] * MM)))
        t.SetLayer(lid)
        t.SetTextSize(pcbnew.VECTOR2I(int(0.6 * MM), int(0.6 * MM)))
        b.Add(t)
    b.Save(str(pcb))
    print(f"drew {n} corridor segment(s) on {PLAN_LAYER}; turn that layer on in KiCad to see them")
    return 0


def cmd_show(proj: Path) -> int:
    plan = load(proj)
    print(f"routing plan mode: {'on' if mode_on(proj) else 'off'} (boardwright.json routing_plan)")
    if not plan["corridors"]:
        print("no plan yet")
        return 0
    for c in plan["corridors"]:
        print(f"{c['id']} {c['status']}: {', '.join(c['nets'])} on {','.join(c['layers'])}"
              f" ({c.get('why', '')})")
    return 0


def cmd_verify(proj: Path) -> int:
    import kicad_python
    kicad_python.ensure(__file__)
    import glob
    import pcbnew
    pcb = glob.glob(str(proj / "*.kicad_pcb"))[0]
    b = pcbnew.LoadBoard(pcb)
    plan = load(proj)
    bad = 0
    for c in plan["corridors"]:
        polys = corridor_polys(b, c)
        outside, count = 0, 0
        for t in b.GetTracks():
            if t.GetNetname() not in c["nets"]:
                continue
            count += 1
            ps = polys.get(t.GetLayer())
            if t.Type() == pcbnew.PCB_VIA_T:
                ok = any(p.Contains(t.GetPosition()) for p in polys.values())
            else:
                ok = ps is not None and ps.Contains(t.GetStart()) and ps.Contains(t.GetEnd())
            if not ok:
                outside += 1
        if c["status"] != "approved" and count:
            print(f"{c['id']}: {count} track(s) on a corridor that is {c['status']}")
            bad += 1
        elif outside:
            print(f"{c['id']}: {outside} of {count} track(s) outside the corridor")
            bad += 1
        else:
            print(f"{c['id']}: {count} track(s), all inside" if count else f"{c['id']}: not routed yet")
    print("PASS" if not bad else f"FAIL: {bad} corridor(s)")
    return 1 if bad else 0


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    proj = Path(argv[0]).resolve()
    cmd = argv[1]
    if cmd == "propose" and len(argv) > 2:
        return cmd_propose(proj, argv[2])
    if cmd == "draw":
        return cmd_draw(proj)
    if cmd == "show":
        return cmd_show(proj)
    if cmd == "verify":
        return cmd_verify(proj)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
