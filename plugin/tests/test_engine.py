#!/usr/bin/env python3
"""Tests for scripts/engine.py: python plugin/tests/test_engine.py  (standard library only).

Needs KiCad and the engine tools (install/setup_engine.ps1); skips cleanly (exit 0) when either is missing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "plugin" / "scripts"
ENGINE = SCRIPTS / "engine.py"
EXAMPLE = ROOT / "examples" / "usb-sensor-test"
PREP = ROOT / "tools" / "bench" / "prep.py"
sys.path.insert(0, str(SCRIPTS))
FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILS.append(name)


def skip(why):
    print(f"skip  {why}")
    sys.exit(0)


def run(args, env=None):
    t0 = time.time()
    r = subprocess.run([sys.executable, str(ENGINE), *map(str, args)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=dict(os.environ, **(env or {})))
    return r.returncode, (r.stdout + r.stderr), time.time() - t0


def fresh(tmp, name, unroute):
    dest = Path(tmp) / name
    shutil.copytree(EXAMPLE, dest, ignore=shutil.ignore_patterns("fab", ".boardwright", ".git"))
    task = Path(tmp) / f"{name}.json"
    task.write_text(json.dumps({"prep": [{"unroute": unroute}]}), "utf-8")
    r = subprocess.run([KPY, "-I", str(PREP), str(dest), str(task)], capture_output=True, text=True)
    if r.returncode != 0:
        print("prep failed: " + r.stdout + r.stderr)
        sys.exit(1)
    return dest


def copper(proj):
    pcb = next(Path(proj).glob("*.kicad_pcb"))
    r = subprocess.run([KPY, "-I", str(SCRIPTS / "engine_kicad.py"), "copper", str(pcb)], capture_output=True,
                       text=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def pcb_of(proj):
    return next(Path(proj).glob("*.kicad_pcb"))


def pro_of(proj):
    return next(Path(proj).glob("*.kicad_pro"))


def dru_errors(proj):
    import engine
    d = engine.drc_full(pcb_of(proj))
    return d


def main():
    global KPY
    import engine
    import kicad_python
    KPY = kicad_python.find()
    if not KPY:
        skip("KiCad not found")
    if not (engine.engine_dir() / "engine.json").is_file():
        skip("engine tools not installed (no engine.json)")
    try:
        engine.find_tools()
    except engine.Setup as exc:
        skip(str(exc))
    import history

    tmp = tempfile.mkdtemp(prefix="bwenginetest")
    try:
        five = ["/LED_STATUS", "/LED_STATUS_A", "/LED_PWR_A", "/CC1", "/CC2"]

        # (a) five nets routed, no new DRC error, history steps, .kicad_pro untouched
        p = fresh(tmp, "a", five)
        pro_before = pro_of(p).read_bytes()
        d0 = dru_errors(p)
        n0 = len(history.Store(p).steps())
        rc, out, secs = run([p, "run"])
        d1 = dru_errors(p)
        steps = [s[2] for s in history.Store(p).steps()][n0:]
        cu = copper(p)
        check(f"(a) run exits 0 ({secs:.0f} s)", rc == 0, out[-600:])
        check("(a) summary is short", len(out.splitlines()) < 40, str(len(out.splitlines())))
        check("(a) all five nets have copper", all(n in cu and cu[n][0] > 0 for n in five), str(cu))
        check("(a) no unconnected left", d1 and d1["unconnected"] == 0, str(d1 and d1["unconnected"]))
        check("(a) no new DRC error", d1 and d0 and all(k in d0["errors"] for k in d1["errors"]))
        check("(a) one step before and one after",
              len(steps) == 2 and steps[0] == "before engine run" and steps[1].startswith("engine: routed 5 nets"),
              str(steps))
        check("(a) .kicad_pro byte-identical", pro_of(p).read_bytes() == pro_before)
        check("(a) report written", (p / "reports" / "engine.json").is_file() and (p / "reports" / "engine.md").is_file())
        check("(a) lock released", not (p / ".boardwright" / "edit.lock").exists())
        rc2, out2, _s = run([p, "leftovers"])
        check("(a) leftovers command", rc2 == 0 and "leftovers: 0" in out2, out2)

        # (b) fast nets are left out, an ordinary net is routed
        p = fresh(tmp, "b", ["/USB_DP", "/USB_DM", "/CC1"])
        rc, out, secs = run([p, "run"])
        cu = copper(p)
        check(f"(b) run exits 1 ({secs:.0f} s)", rc == 1, out[-600:])
        check("(b) /CC1 routed", "/CC1" in cu and cu["/CC1"][0] > 0, str(cu.get("/CC1")))
        check("(b) USB nets have no tracks", not cu.get("/USB_DP", [0])[0] and not cu.get("/USB_DM", [0])[0],
              str(cu))
        check("(b) USB nets left out as fast", "left out /USB_DP: fast net" in out and "left out /USB_DM: fast net" in out,
              out[-600:])
        check("(b) USB listed as leftovers", "Leftovers for Claude: " in out and "Leftovers for Claude: 0" not in out
              and "/USB_DP:" in out and "/USB_DM:" in out, out[-600:])

        # (c) Freerouting alone, on the five-net case
        p = fresh(tmp, "c", five)
        d0 = dru_errors(p)
        rc, out, secs = run([p, "run", "--engines", "freerouting"])
        d1 = dru_errors(p)
        cu = copper(p)
        got = [n for n in five if cu.get(n, [0])[0] > 0]
        print(f"     (c) freerouting alone ({secs:.0f} s): routed {len(got)} of 5: {', '.join(got)}")
        for l in out.splitlines():
            if l.startswith("freerouting:") or l.startswith("  /"):
                print("     " + l)
        check("(c) freerouting stage ran and was accepted", "freerouting: ACCEPTED" in out, out[-600:])
        check("(c) freerouting routed at least one net", len(got) >= 1, str(cu))
        check("(c) no new DRC error", d1 and d0 and all(k in d0["errors"] for k in d1["errors"]))
        check("(c) honest exit code", rc == (0 if d1["unconnected"] == 0 else 1), f"rc {rc}")

        # (d) dry run leaves the board byte-identical
        p = fresh(tmp, "d", five)
        before = pcb_of(p).read_bytes()
        pro_before = pro_of(p).read_bytes()
        rc, out, secs = run([p, "run", "--dry-run"])
        check(f"(d) dry run reports what it would do ({secs:.0f} s)", "routed 5 of 5" in out and "dry run" in out, out[-500:])
        check("(d) board byte-identical", pcb_of(p).read_bytes() == before)
        check(".kicad_pro byte-identical (dry)", pro_of(p).read_bytes() == pro_before)
        check("(d) no history, no report, no lock",
              not (p / ".boardwright").exists() and not (p / "reports" / "engine.json").exists())

        # (e) KiCad has the board open
        p = fresh(tmp, "e", five)
        (p / "~usb-sensor-test.kicad_pcb.lck").write_text("{}", "utf-8")
        before = pcb_of(p).read_bytes()
        rc, out, _s = run([p, "run"])
        check("(e) lock file makes it refuse", rc == 2 and "close the board in KiCad first" in out, out[-300:])
        check("(e) board untouched", pcb_of(p).read_bytes() == before)

        # (f) tools missing
        empty = Path(tmp) / "empty"
        empty.mkdir()
        p2 = fresh(tmp, "f", five)
        rc, out, _s = run([p2, "run"], env={"BOARDWRIGHT_ENGINE_DIR": str(empty)})
        check("(f) missing tools: exit 2 with the install message",
              rc == 2 and "the engine tools are not installed" in out, out[-300:])
        rc, out, _s = run([p2, "status"], env={"BOARDWRIGHT_ENGINE_DIR": str(empty)})
        check("(f) status says so too", rc == 2 and "not installed" in out, out[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nALL PASSED" if not FAILS else f"\n{len(FAILS)} FAILED: {', '.join(FAILS)}")
    return 1 if FAILS else 0


KPY = None

if __name__ == "__main__":
    sys.exit(main())
