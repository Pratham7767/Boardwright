#!/usr/bin/env python3
"""Checks for the board-editing fixes: dry run writes nothing, a failed batch changes nothing, a failed
place puts the part back, vias are checked on every copper layer, and `add` keeps to approved corridors.

    python plugin/tests/test_edit_fixes.py

Works on temp copies of examples/usb-sensor-test (without its `fab` folder); the examples folder is never
touched. Needs KiCad (found through run_gates.find_kicad_cli); without it the script exits 0 with a skip
note. Prints [ok] or [FAIL] per check; exit 0 only when every check passed. Standard library only.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPTS = REPO / "plugin" / "scripts"
EXAMPLE = REPO / "examples" / "usb-sensor-test"
sys.path.insert(0, str(SCRIPTS))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RESULTS = []
TMPS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(f"[{'ok' if cond else 'FAIL'}] {name}" + ("" if cond else (f"  -> {detail}"[:700] if detail else "")),
          flush=True)
    return bool(cond)


def run(cmd):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=900)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def fresh_copy(tag):
    tmp = Path(tempfile.mkdtemp(prefix=f"bw-fix-{tag}-"))
    TMPS.append(tmp)
    proj = tmp / "usb-sensor-test"
    shutil.copytree(EXAMPLE, proj, ignore=lambda d, names: [n for n in names if n == "fab" or n.endswith(".lck")
                                                            or n.endswith("-backups")])
    return proj


def find_kicad():
    try:
        from run_gates import find_kicad_cli
        cli = find_kicad_cli()
    except Exception:
        cli = None
    if not cli or not Path(cli).exists():
        return None
    for n in ("python.exe", "python3", "python"):
        p = Path(cli).resolve().parent / n
        if p.exists():
            return str(p)
    return None


class K:
    def __init__(self, kpy):
        self.kpy = kpy

    def edit(self, proj, ops, *extra):
        return run([self.kpy, "-I", SCRIPTS / "bw_edit.py", proj, json.dumps(ops), *extra])

    def script(self, proj, body):
        """Run a snippet under KiCad's Python with the plugin scripts importable; returns its last JSON line."""
        f = proj.parent / "snippet.py"
        f.write_text("import sys, json\nsys.path.insert(0, %r)\n" % str(SCRIPTS) + textwrap.dedent(body), "utf-8")
        code, out = run([self.kpy, "-I", f, proj])
        for line in reversed(out.splitlines()):
            if line.startswith("{"):
                return json.loads(line), out
        return None, out


def snapshot(proj):
    return {n: (proj / n).read_bytes() for n in ("usb-sensor-test.kicad_pcb", "usb-sensor-test.kicad_pro",
                                                 "usb-sensor-test.kicad_dru")}


NC = {"netclass": {"name": "ZTEST", "track_width": 0.31, "clearance": 0.2, "nets": ["/LED_STATUS"]}}
RULE = {"rule": {"name": "ztest", "text": '(rule "ztest" (constraint track_width (min 0.1mm)))'}}


def test_dry_run(k):
    proj = fresh_copy("dry")
    before = snapshot(proj)
    code, out = k.edit(proj, [NC, RULE, {"move": "C3", "by": [1, 0]}], "--dry-run")
    after = snapshot(proj)
    check("dry run: exits 0 and says nothing saved", code == 0 and "nothing saved" in out, f"{code} {out}")
    check("dry run: .kicad_pro is byte-identical", before["usb-sensor-test.kicad_pro"] == after["usb-sensor-test.kicad_pro"])
    check("dry run: .kicad_dru is byte-identical", before["usb-sensor-test.kicad_dru"] == after["usb-sensor-test.kicad_dru"])
    check("dry run: board is byte-identical", before["usb-sensor-test.kicad_pcb"] == after["usb-sensor-test.kicad_pcb"])
    check("dry run: still reports the netclass and rule it would write", "netclass ZTEST" in out and "rule ztest" in out, out)
    # a following add in the same batch must use the new class values (track width 0.31 for /LED_STATUS)
    code, out = k.edit(proj, [NC, {"add": [{"track": {"from": [108, 116.5], "to": [109, 116.5], "layer": "F.Cu",
                                                      "net": "/LED_STATUS"}}]}, {"find": {"kind": "track", "net": "/LED_STATUS"}}],
                       "--dry-run")
    check("dry run: the in-memory class is used by a later op without touching the files",
          code == 0 and before["usb-sensor-test.kicad_pro"] == snapshot(proj)["usb-sensor-test.kicad_pro"], f"{code} {out}")


def test_batch_atomic(k):
    proj = fresh_copy("atomic")
    before = snapshot(proj)
    code, out = k.edit(proj, [NC, RULE, {"move": "C3", "by": [1, 0]}, {"move": "NOPE", "by": [1, 0]}])
    after = snapshot(proj)
    check("batch: a failing last op exits 1 and says nothing was changed", code == 1 and "nothing was changed" in out,
          f"{code} {out}")
    for n in before:
        check(f"batch: {n.split('.')[-1]} is byte-identical after the failed batch", before[n] == after[n])
    # a good batch still saves
    code, out = k.edit(proj, [NC, {"move": "C3", "by": [1, 0]}], "--no-drc")
    now = snapshot(proj)
    check("batch: a good batch still saves the board and .kicad_pro",
          code == 0 and now["usb-sensor-test.kicad_pcb"] != before["usb-sensor-test.kicad_pcb"]
          and now["usb-sensor-test.kicad_pro"] != before["usb-sensor-test.kicad_pro"], f"{code} {out}")


def test_place_restore(k):
    proj = fresh_copy("place")
    res, out = k.script(proj, """
        from pathlib import Path
        import bw_edit
        from bw_project import project_files
        proj = Path(sys.argv[1]).resolve()
        files = project_files(proj)
        bd = bw_edit.Board(files["pcb"])
        ctx = {"proj": proj, "files": files, "rules": bw_edit.Rules(proj, files)}
        fp = bd.fps["C3"]
        def state():
            p = fp.GetPosition()
            return [p.x, p.y, round(fp.GetOrientationDegrees(), 6), fp.GetLayer()]
        a = state()
        err = ""
        try:
            bw_edit.op_place(bd, {"place": {"ref": "C3", "near": "U1.1", "within": 0.01, "side": "B", "rot": [90]}}, ctx)
        except ValueError as e:
            err = str(e)
        print(json.dumps({"before": a, "after": state(), "err": err}))
    """)
    check("place: an impossible place raises 'no free spot'", res and "no free spot" in res["err"], out)
    check("place: a failed place leaves C3 at its position, rotation and side",
          res and res["before"] == res["after"], f"{res} {out[-300:]}")


def test_via_layers(k):
    proj = fresh_copy("via")
    res, out = k.script(proj, """
        from pathlib import Path
        import pcbnew, bw_edit, bw_router
        from bw_project import project_files
        proj = Path(sys.argv[1]).resolve()
        files = project_files(proj)
        bd = bw_edit.Board(files["pcb"])
        b = bd.b
        net = b.FindNet("/LED_STATUS")
        r = bw_router.Router(b, bw_edit.Rules(proj, files), layers=("F.Cu",), vias=True)
        t = next((t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T and t.GetLayer() == pcbnew.B_Cu
                  and t.GetNetname() not in ("", "/LED_STATUS") and t.GetLength() > 1e6), None)
        out = {"track": bool(t), "routing_layers": len(r.lids), "copper_layers": len(r.all_lids)}
        if t:
            mx = (t.GetStart().x + t.GetEnd().x) / 2
            my = (t.GetStart().y + t.GetEnd().y) / 2
            ix, iy = r.grid.cell(mx, my)
            k = iy * r.grid.w + ix
            via = r.via_grid(net)
            out["via_blocked"] = bool(via[0][k])
            out["entries"] = len(via)
            # the same cell is not necessarily blocked for a track on F.Cu alone
            out["track_blocked_f"] = bool(r._blocked(net, 0.1)[0][k])
        print(json.dumps(out))
    """)
    check("via grid: the board has a B.Cu track of another net to test with", res and res["track"], out)
    check("via grid: with only F.Cu as routing layer, the grid still knows both copper layers",
          res and res["routing_layers"] == 1 and res["copper_layers"] >= 2, str(res))
    check("via grid: a cell on another net's B.Cu track is blocked for vias", res and res.get("via_blocked") is True,
          f"{res} {out[-300:]}")


def enable_plan(proj, k):
    d = proj / ".boardwright"
    d.mkdir(exist_ok=True)
    (d / "choices.json").write_text(json.dumps({"routing_plan": {"value": True, "how": "test", "at": "2026-01-01T00:00:00"}}),
                                    "utf-8")
    corridor = {"corridors": [{"id": "c1", "nets": ["/LED_STATUS"], "layers": ["F.Cu"], "width_mm": 0.2,
                               "half_width_mm": 0.6, "path": [[107.5, 116.5], [112.0, 116.5]], "why": "test"}]}
    pf = proj.parent / "plan.json"
    pf.write_text(json.dumps(corridor), "utf-8")
    code, out = run([k.kpy, "-I", SCRIPTS / "routing_plan.py", proj, "propose", "@" + str(pf)])
    check("corridor: plan proposed", code == 0 and "c1: proposed" in out, out)
    rp = proj / "reports" / "routing-plan.json"
    plan = json.loads(rp.read_text("utf-8"))
    for c in plan["corridors"]:
        c["status"] = "approved"          # test fixture only: the real approval comes from the designer's own words
    rp.write_text(json.dumps(plan), "utf-8")


def test_corridor(k):
    proj = fresh_copy("corr")
    enable_plan(proj, k)
    before = snapshot(proj)
    far = {"add": [{"track": {"from": [120, 130], "to": [125, 130], "layer": "F.Cu", "net": "/LED_STATUS", "width": 0.2}}]}
    code, out = k.edit(proj, far, "--no-drc")
    check("corridor: a track far outside the approved corridor is refused with a clear message",
          code == 1 and "outside its corridor c1" in out and "nothing was changed" in out, f"{code} {out}")
    check("corridor: nothing was saved after the refusal", snapshot(proj) == before)
    half = {"add": [{"track": {"from": [108, 116.5], "to": [125, 130], "layer": "F.Cu", "net": "/LED_STATUS", "width": 0.2}}]}
    code, out = k.edit(proj, half, "--no-drc")
    check("corridor: one end outside is refused too", code == 1 and "outside its corridor" in out, f"{code} {out}")
    far_via = {"add": [{"via": {"at": [125, 130], "net": "/LED_STATUS"}}]}
    code, out = k.edit(proj, far_via, "--no-drc")
    check("corridor: a via far outside is refused", code == 1 and "outside its corridor" in out, f"{code} {out}")
    good = {"add": [{"track": {"from": [108, 116.5], "to": [111, 116.5], "layer": "F.Cu", "net": "/LED_STATUS", "width": 0.2}}]}
    code, out = k.edit(proj, good, "--no-drc")
    check("corridor: a track inside the corridor is accepted and saved",
          code == 0 and "add track" in out and "saved" in out and snapshot(proj) != before, f"{code} {out}")


def main():
    t0 = time.time()
    if not EXAMPLE.is_dir():
        print("examples/usb-sensor-test not found")
        return 2
    kpy = find_kicad()
    if not kpy:
        print("[skip] KiCad not found: skipped the edit-fix checks")
        return 0
    k = K(kpy)
    try:
        for t in (test_dry_run, test_batch_atomic, test_place_restore, test_via_layers, test_corridor):
            t(k)
    finally:
        for t in TMPS:
            shutil.rmtree(t, ignore_errors=True)
    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad} passed, {bad} failed in {time.time() - t0:.0f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
