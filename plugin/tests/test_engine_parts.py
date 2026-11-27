#!/usr/bin/env python3
"""Fast checks of the routing engine's parts that need no router: the stop-file runner, the fresh run folders,
and the net-name patterns. Standard library only; runs anywhere.

    python plugin/tests/test_engine_parts.py
"""
import fnmatch
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import engine  # noqa: E402

BAD = []

# Run under KiCad's Python: two copies of a board, each with one new track narrower than its net's class that
# starts on the smallest pad of a net whose class is wider than that pad: 1 mm long (a neck-down) and 5 mm long.
NECK_BOARD = r"""
import sys
sys.path.insert(0, sys.argv[1])
import kicad_python
kicad_python.quiet()
import pcbnew
b = pcbnew.LoadBoard(sys.argv[2])
ns = b.GetDesignSettings().m_NetSettings
best = None
for pad in b.GetPads():
    n = pad.GetNetname()
    if not n:
        continue
    bb = pad.GetBoundingBox()
    side = min(bb.GetWidth(), bb.GetHeight())
    cw = ns.GetEffectiveNetClass(n).GetTrackWidth()
    if side + 20000 < cw and (best is None or side < best[1]):
        best = (pad, side)
pad, side = best
px, py, net = pad.GetX(), pad.GetY(), pad.GetNetname()
for old in [x for x in b.GetTracks() if x.GetNetname() == net]:
    b.Remove(old)                              # only the new track is judged
for name, length in (("neck_short", 1000000), ("neck_long", 5000000)):
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(px, py))
    t.SetEnd(pcbnew.VECTOR2I(px + length, py))
    t.SetWidth(side)
    t.SetLayer(pcbnew.F_Cu)
    t.SetNet(pad.GetNet())
    b.Add(t)
    b.Save(sys.argv[3] + "/" + name + ".kicad_pcb")
    b.Remove(t)
print("NET=" + net)
"""


def check(name, ok, extra=""):
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  -> {extra}"))
    if not ok:
        BAD.append(name)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bw_engine_parts_"))
    try:
        # a stand-in router: works until its stop file appears, then writes what it has and exits
        router = tmp / "router.py"
        router.write_text(
            "import os, sys, time, pathlib\n"
            "stop = os.environ.get('KICAD_STOP_FILE')\n"
            "assert os.environ.get('PYTHONHASHSEED') == '0'\n"
            "for i in range(600):\n"
            "    if stop and os.path.exists(stop):\n"
            "        pathlib.Path(sys.argv[1]).write_text(f'partial after {i}')\n"
            "        sys.exit(0)\n"
            "    time.sleep(0.05)\n"
            "pathlib.Path(sys.argv[1]).write_text('finished')\n", "utf-8")
        out = tmp / "out.txt"
        stop = tmp / "STOP"
        saved = tmp / "saved.kicad_pcb"
        saved.write_text("x")
        check("a session import that saved its board counts even if KiCad failed while closing",
              engine.import_ok(-1, 'noise\n{"ok": true}\n', saved) and engine.import_ok(0, "", saved)
              and not engine.import_ok(1, '{"ok": false}', saved)
              and not engine.import_ok(0, '{"ok": true}', tmp / "missing.kicad_pcb"))
        t0 = time.time()
        rc, text, killed, secs = engine.run_until([sys.executable, router, out], 2 / 60, str(tmp), stop_file=stop)
        check("at the limit the stop file is made and the router keeps its partial result",
              rc == 0 and not killed and out.read_text().startswith("partial") and stop.exists(), (rc, killed, text))
        check("it stops near the limit, not at the end of the work", time.time() - t0 < 20, time.time() - t0)

        # a process that ignores the stop file is killed after the grace time
        hang = tmp / "hang.py"
        hang.write_text("import time\ntime.sleep(60)\n", "utf-8")
        rc, text, killed, secs = engine.run_until([sys.executable, hang], 1 / 60, str(tmp), stop_file=tmp / "S2",
                                                  grace=2)
        check("a router that ignores the stop file is killed after the grace time", killed and secs < 30, secs)

        # a fresh run folder: the board plus the project's own .kicad_pro, also next to the output
        proj = tmp / "proj"
        proj.mkdir()
        (proj / "b.kicad_pro").write_text('{"rules": 1}', "utf-8")
        (proj / "b.kicad_pcb").write_text("(kicad_pcb)", "utf-8")
        merged = tmp / "merged.kicad_pcb"
        merged.write_text("(kicad_pcb merged)", "utf-8")
        src, raw, d = engine.stage_dir(proj, tmp, merged, "krt")
        check("the run folder has the board and the project's rules beside it",
              src.read_text() == "(kicad_pcb merged)" and (d / "board.kicad_pro").read_text() == '{"rules": 1}')
        check("the output folder is empty except the project's rules (nothing read back from an older run)",
              sorted(p.name for p in raw.parent.iterdir()) == ["board.kicad_pro"] and not raw.exists())
        (raw.parent / "board.kicad_pcb").write_text("old result", "utf-8")
        src, raw, d = engine.stage_dir(proj, tmp, merged, "krt")
        check("a second run starts from a fresh folder", not raw.exists())

        # net names reach KiCadRoutingTools as patterns that match exactly that net
        for n in ("-12V", "/D[0]", "A*B?", "GND"):
            check(f"pattern for {n} matches only itself", fnmatch.fnmatchcase(n, engine.krt_pattern(n))
                  and not engine.krt_pattern(n).startswith("-"))
        check("A*B? does not match AxBy", not fnmatch.fnmatchcase("AxBy", engine.krt_pattern("A*B?")))

        # high-speed pairs the engine leaves alone (unless --allow-fast), from the demo boards' real names
        import bw_edit
        for n in ("/CM5/DPHY0_P.C_N", "/CM5/HDMI_PI.D2_N", "/CM5/PCIE_PI.CLK_P", "/USB_C.D_P",
                  "/CSI/CAM0.CSI2_D0+", "/USB Hub/USBSS_RX_P", "/USB_DP", "/USB_DM"):
            check(f"{n} is a high-speed pair member", bool(bw_edit.FAST_NAME.search(n)))
        for n in ("/graphic/CSIO-", "/DSI", "/Expansion connector/PCIe_{C2x1}.~{CLKREQ}", "/USB_VBUS", "GND",
                  "/DDAT0", "+3.3V"):
            check(f"{n} is not", not bw_edit.FAST_NAME.search(n))
        for c in ("100ohm", "90ohm", "50ohm", "USB"):
            check(f"net class {c} counts as fast", bool(bw_edit.FAST_CLASS.search(c)))
        check("net class Power does not", not bw_edit.FAST_CLASS.search("Power"))
        got = engine.pair_members(["/A_P", "/A_N", "/B+", "/B-", "/C_P", "/USB_DP", "/USB_DM", "/X"])
        check("pairs need both members", got == ["/A_N", "/A_P", "/B+", "/B-", "/USB_DM", "/USB_DP"], got)
        got = engine.pair_members(["/ETH.TRD2_N", "/X_P"], ["/ETH.TRD2_N", "/ETH.TRD2_P", "/X_P", "/Y"])
        check("an open half whose partner is already routed is still a pair, with its partner",
              got == ["/ETH.TRD2_N", "/ETH.TRD2_P"], got)
        # which of the pair router's results may be merged (report shapes as KiCadRoutingTools 0.24.1 writes them)
        rep = {"single_ended_fallback": {"routed": ["/S_P", "/S_N", "/F_P", "/F_N"]}, "pair_reports": [
            {"p_net": "/C_P", "n_net": "/C_N", "outcome": "coupled", "incomplete_members": []},
            {"p_net": "/S_P", "n_net": "/S_N", "outcome": "deferred", "failure_reason": "electrically-short",
             "incomplete_members": []},
            {"p_net": "/F_P", "n_net": "/F_N", "outcome": "deferred", "failure_reason": "coupled-route-failed",
             "se_fallback": {"p": "routed", "n": "routed"}, "incomplete_members": []},
            {"p_net": "/H_P", "n_net": "/H_N", "outcome": "partial", "incomplete_members": ["/H_P", "/H_N"]},
            {"p_net": "/T_P", "n_net": "/T_N", "outcome": "deferred", "failure_reason": "electrically-short",
             "incomplete_members": []}]}
        got = engine.accepted_pairs(rep)
        check("only coupled pairs are kept: not short legs as two tracks, failed coupling, partial, unrouted",
              got == ["/C_P", "/C_N"], got)
        # pairs grouped by the layers and sizes the rules give them (jetson: other sizes inside than outside)
        L = ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "B.Cu"]
        mixed = {l: ([0.17, .45, .1, 0.18] if l in ("F.Cu", "B.Cu") else [0.125, .45, .1, 0.10]) for l in L}
        even = {l: [0.2, .45, .1, 0.15] for l in L}
        sf = tmp / "pair_sizes.json"
        sf.write_text(__import__("json").dumps({"sizes": {"/A+": mixed, "/A-": mixed, "/U_P": even, "/U_N": even}}),
                      "utf-8")
        got = engine.pair_groups(str(sf), ["/A+", "/A-", "/U_P", "/U_N", "/X_P", "/X_N"],
                                 {"copper": L, "standard": L, "planes": {"In2.Cu": "GND"}})
        check("pairs whose sizes differ by layer keep to the outer layers' size; even ones use every non-plane "
              "layer; unknown sizes are left to the router",
              got == [(("F.Cu", "B.Cu"), 0.17, 0.18, ["/A+", "/A-"]),
                      (("F.Cu", "In1.Cu", "In3.Cu", "B.Cu"), 0.2, 0.15, ["/U_P", "/U_N"]),
                      ((), 0.0, 0.0, ["/X_P", "/X_N"])], got)
        # a big group in runs of at most N pairs, partners never split
        got = engine.pair_chunks(["/B_N", "/A+", "/C_P", "/A-", "/B_P", "/C_N", "/D_DM", "/D_DP"], 3)
        check("pair runs: at most 3 pairs each, sorted by name, both members together",
              got == [["/A+", "/A-", "/B_N", "/B_P", "/C_N", "/C_P"], ["/D_DM", "/D_DP"]], got)

        # blame by place: the nets with copper near a DRC error's position (needs KiCad's Python)
        import kicad_python
        kpy = kicad_python.find()
        board = Path(__file__).resolve().parents[2] / "examples" / "usb-sensor-test" / "usb-sensor-test.kicad_pcb"
        if kpy and board.is_file():
            near = engine.nets_near(kpy, board, board, [(117.0, 112.4)], ["/+3V3", "/GND", "/USB_DP"], 3.0)
            check("nets near a spot: the copper around C3 is +3V3 and GND, not USB", near == ["/+3V3", "/GND"], near)
            check("nets near a spot far from any copper: none",
                  engine.nets_near(kpy, board, board, [(0.0, 0.0)], ["/+3V3", "/GND"], 1.0) == [])
            # the routers' working copy: keep-outs over copper text, the copper itself untouched
            guarded = engine.guard_text(kpy, board, tmp / "guarded.kicad_pcb")
            check("copper-text keep-outs written to a copy", guarded == tmp / "guarded.kicad_pcb", guarded)
            check("no net counts as moved between a board and its guarded copy",
                  engine.moved_nets(kpy, board, guarded, []) == [])
            # the owner's neck-down rule: narrower than the class only at a pad, as far as the pad needs, <= 2 mm
            import json
            import subprocess
            src = tmp / "neck_src.kicad_pcb"                # every class 3 mm wide: any pad is narrower than that
            shutil.copyfile(board, src)
            pro = json.loads(board.with_suffix(".kicad_pro").read_text("utf-8"))
            for c in pro["net_settings"]["classes"]:
                c["track_width"] = 3.0
            for name in ("neck_src", "neck_short", "neck_long"):
                (tmp / f"{name}.kicad_pro").write_text(json.dumps(pro), "utf-8")
            made = subprocess.run([kpy, "-I", "-c", NECK_BOARD, str(Path(engine.__file__).parent), str(src),
                                   str(tmp)], capture_output=True, text=True)
            net = next((l[4:] for l in made.stdout.splitlines() if l.startswith("NET=")), "")
            if net and (tmp / "neck_short.kicad_pcb").is_file() and (tmp / "neck_long.kicad_pcb").is_file():
                short = engine.audit(kpy, tmp / "neck_short.kicad_pcb", [net], {})
                long_ = engine.audit(kpy, tmp / "neck_long.kicad_pcb", [net], {})
                check("a short track at a pad's width passes the size audit", net not in short, short)
                check("a long track at the same width still fails it", net in long_, long_)
            else:
                check("neck-down boards made", False, made.stderr[-300:])
            # sizes from the project's rules (engine_rules.py) win over the class, per layer, both ways
            layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
            sz = tmp / "sizes.json"
            sz.write_text(json.dumps({"layers": layers, "sizes": {
                "/I2C_SCL": {l: [0.5, 0.7, 0.3] for l in layers},        # stricter than its 0.2 mm class
                "/GND": {l: [0.25, 0.6, 0.3] for l in layers}}}), "utf-8")   # looser than its 0.4 mm class
            engine.SIZES["file"] = str(sz)
            try:
                got = engine.audit(kpy, board, ["/I2C_SCL", "/GND"], {})
            finally:
                engine.SIZES["file"] = ""
            check("a rule wider than the class is enforced", "/I2C_SCL" in got and "rules 0.500" in got["/I2C_SCL"],
                  got)
            check("a rule narrower than the class is what counts", "/GND" not in got, got)
        else:
            print("skip nets near a spot: KiCad not found")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if not BAD else f"{len(BAD)} FAILED")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
