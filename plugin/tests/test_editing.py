#!/usr/bin/env python3
"""Automated checks for the editing features: history, edit hooks, bw_edit, router, place, routing plan, fab rules.

    python plugin/tests/test_editing.py

Every test works on a fresh copy of examples/usb-sensor-test in a temp folder (the examples folder is
never touched; the copy leaves out `fab`). Prints one line per check, [ok] or [FAIL]. Exit 0 only when
every check passed. Without KiCad, only the KiCad-free checks (history, edit hooks) run.
Standard library only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPTS = REPO / "plugin" / "scripts"
EXAMPLE = REPO / "examples" / "usb-sensor-test"
PREP = REPO / "tools" / "bench" / "prep.py"
sys.path.insert(0, str(SCRIPTS))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PY = sys.executable
RESULTS = []
TMPS = []
FIVE = ["/LED_STATUS", "/LED_STATUS_A", "/LED_PWR_A", "/CC1", "/CC2"]


def _force_remove(func, path, _exc):
    # git object files are read-only on Windows
    try:
        os.chmod(path, 0o700)
        func(path)
    except OSError:
        pass


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(f"[{'ok' if cond else 'FAIL'}] {name}" + ("" if cond else (f"  -> {detail}"[:600] if detail else "")), flush=True)
    return bool(cond)


def run(cmd, env=None, stdin=None, cwd=None):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       input=stdin, env=env, cwd=cwd, timeout=900)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def fresh_copy(tag):
    tmp = Path(tempfile.mkdtemp(prefix=f"bw-test-{tag}-"))
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
        return None, None
    for n in ("python.exe", "python3", "python"):
        p = Path(cli).resolve().parent / n
        if p.exists():
            return str(cli), str(p)
    return str(cli), None


def hist(proj, *args):
    return run([PY, SCRIPTS / "history.py", proj, *args])


def hook(proj, mode, payload, sid="s1"):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    payload = dict(payload, session_id=payload.get("session_id", sid))
    return run([PY, SCRIPTS / "edit_hooks.py", mode], env=env, stdin=json.dumps(payload))


def git(proj, *args):
    return run(["git", "-C", proj, *args])


def read_cfg(proj):
    return json.loads((proj / "boardwright.json").read_text("utf-8"))


# ------------------------------------------------------------------ 1. history
def test_history():
    proj = fresh_copy("hist")
    dru = proj / "usb-sensor-test.kicad_dru"
    code, out = hist(proj, "snap")
    check("history: first snap saves step 1", code == 0 and "saved step 1" in out, out)
    code, out = hist(proj, "snap")
    check("history: second snap says no change", code == 0 and "no change" in out, out)
    original = dru.read_bytes()
    dru.write_bytes(original + b" ")
    code, out = hist(proj, "snap")
    check("history: changed .kicad_dru saves a new step", "saved step 2" in out, out)
    code, out = hist(proj, "restore", "1")
    check("history: restore 1 exits 0", code == 0 and "restored" in out, out)
    check("history: restore 1 gives the file back byte-identical", dru.read_bytes() == original)
    code, out = hist(proj, "list")
    m = re.search(r"# (\d+) steps", out)
    check("history: restore added steps", m and int(m.group(1)) >= 3, out)
    gi = proj / ".boardwright" / ".gitignore"
    check(".boardwright/.gitignore contains *", gi.is_file() and gi.read_text("utf-8").strip() == "*")

    # nothing under .boardwright is staged by a user's git add -A
    g = fresh_copy("hist-git")
    git(g, "init", "-q")
    hist(g, "snap")
    run(["git", "-C", g, "add", "-A"])
    code, out = git(g, "diff", "--cached", "--name-only")
    check("history: after git init + add -A nothing under .boardwright/ is staged",
          code == 0 and ".boardwright" not in out and "usb-sensor-test.kicad_pcb" in out, out)

    # lock
    code, out = hist(proj, "lock", "take", "aaa")
    check("lock: take aaa succeeds", code == 0 and "taken" in out, out)
    code, out = hist(proj, "lock", "take", "bbb")
    check("lock: take bbb exits 1 with refused", code == 1 and "refused" in out, f"{code} {out}")
    code, out = hist(proj, "lock", "release", "aaa")
    check("lock: release aaa", code == 0 and "released" in out, out)
    code, out = hist(proj, "lock", "status")
    check("lock: status is free after release", "free" in out, out)
    code, out = hist(proj, "lock", "take", "bbb")
    check("lock: bbb can take it once freed", code == 0 and "taken" in out, out)

    # stage-commit in a git repo
    s = fresh_copy("hist-stage")
    git(s, "init", "-q")
    ident = ["-c", "user.email=t@t", "-c", "user.name=t"]
    git(s, "add", "-A")
    code, out = git(s, *ident, "commit", "-q", "-m", "base")
    check("stage-commit: base commit made", code == 0, out)
    (s / "usb-sensor-test.kicad_dru").write_bytes((s / "usb-sensor-test.kicad_dru").read_bytes() + b"\n# change\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    code, out = run([PY, SCRIPTS / "history.py", s, "stage-commit", "5", "layout"], env=env)
    code2, msg = git(s, "log", "-1", "--format=%s")
    check("stage-commit 5 layout makes a commit 'stage 5: layout passed'",
          code == 0 and msg.strip() == "stage 5: layout passed", f"{out} | {msg}")


# ------------------------------------------------------------------ 2. edit hooks
def test_hooks():
    proj = fresh_copy("hooks")
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(proj / "x.kicad_pcb")}}
    code, out = hook(proj, "pre", edit, "s1")
    check("hooks: s1 editing x.kicad_pcb is allowed (no output)", code == 0 and out.strip() == "", out)
    code, out = hook(proj, "pre", edit, "s2")
    try:
        dec = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        dec = None
    check("hooks: s2 editing is denied", dec == "deny", out)
    code, out = hook(proj, "pre", {"tool_name": "Read", "tool_input": {"file_path": str(proj / "x.kicad_pcb")}}, "s2")
    check("hooks: a Read by s2 is allowed", code == 0 and out.strip() == "", out)
    code, out = hook(proj, "stop", {}, "s1")
    code, out = hist(proj, "lock", "status")
    check("hooks: stop for s1 frees the lock", "free" in out, out)

    hist(proj, "snap")
    code, out = hist(proj, "list")
    before = int(re.search(r"# (\d+) steps", out).group(1))
    dru = proj / "usb-sensor-test.kicad_dru"
    dru.write_bytes(dru.read_bytes() + b"\n# edited\n")
    hook(proj, "post", {"tool_name": "Edit", "tool_input": {"file_path": str(dru)}}, "s1")
    code, out = hist(proj, "list")
    after = int(re.search(r"# (\d+) steps", out).group(1))
    check("hooks: post after a design file change saves a history step", after == before + 1, f"{before} -> {after}")
    hook(proj, "stop", {}, "s1")

    code, out = hook(proj, "pre", {"tool_name": "Write", "tool_input": {
        "file_path": str(proj / "reports" / "routing-plan.json"), "content": "{}"}}, "s1")
    try:
        dec = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        dec = None
    check("hooks: a Write to reports/routing-plan.json is denied", dec == "deny", out)

    code, out = hook(proj, "prompt", {"prompt": "/boardwright:pcb-plan on"}, "s1")
    check("hooks: prompt '/boardwright:pcb-plan on' sets routing_plan true",
          read_cfg(proj).get("routing_plan") is True, out)


# ------------------------------------------------------------------ KiCad helpers
class Kicad:
    def __init__(self, cli, kpy):
        self.cli, self.kpy = cli, kpy

    def edit(self, proj, ops, *extra):
        return run([self.kpy, "-I", SCRIPTS / "bw_edit.py", proj, json.dumps(ops), *extra])

    def prep(self, proj, steps):
        tf = proj.parent / "prep-task.json"
        tf.write_text(json.dumps({"prep": steps}), "utf-8")
        return run([self.kpy, "-I", PREP, proj, tf])

    def plan(self, proj, *args):
        return run([self.kpy, "-I", SCRIPTS / "routing_plan.py", proj, *args])


def unrouted_copy(k, tag):
    proj = fresh_copy(tag)
    code, out = k.prep(proj, [{"unroute": FIVE}])
    check(f"{tag}: prep unrouted the five nets", code == 0 and "prepared" in out, out)
    return proj


# ------------------------------------------------------------------ 3. bw_edit
def test_bw_edit(k):
    proj = fresh_copy("edit")
    code, out = k.edit(proj, {"find": {"kind": "pad", "ref": "C3"}})
    rows = [l for l in out.splitlines() if l.startswith("  C3.")]
    check("bw_edit: find pads of C3 returns 2 rows", code == 0 and len(rows) == 2, out)

    ops = [{"netclass": {"name": "I2C", "track_width": 0.25, "clearance": 0.2, "nets": ["/I2C_SCL", "/I2C_SDA"]}},
           {"move": ["H1", "H2", "H3", "H4"], "rot": 45}]
    code, out = k.edit(proj, ops)
    check("bw_edit: netclass + move run with 0 new DRC errors", "0 new error(s)" in out and code == 0, f"{code} {out}")
    pro = json.loads((proj / "usb-sensor-test.kicad_pro").read_text("utf-8"))
    ns = pro.get("net_settings", {})
    cls = next((c for c in ns.get("classes", []) if c.get("name") == "I2C"), None)
    check("bw_edit: I2C class is in the .kicad_pro with track 0.25, clearance 0.2",
          cls and cls.get("track_width") == 0.25 and cls.get("clearance") == 0.2, str(cls))
    pats = {p.get("pattern") for p in ns.get("netclass_patterns", []) if p.get("netclass") == "I2C"}
    check("bw_edit: I2C class keeps nets /I2C_SCL and /I2C_SDA after the board save",
          {"/I2C_SCL", "/I2C_SDA"} <= pats, str(pats))
    code, out = k.edit(proj, {"find": {"kind": "footprint", "ref": "H?"}})
    hs = [l for l in out.splitlines() if re.match(r"\s+H[1-4] ", l)]
    check("bw_edit: H1-H4 are at 45 degrees on the saved board",
          len(hs) == 4 and all(re.search(r"rot 45$", l.strip()) for l in hs), out)


# ------------------------------------------------------------------ 4. router
def test_router(k):
    proj = unrouted_copy(k, "router")
    code, out = k.edit(proj, {"route": FIVE})
    check("router: five nets routed without FAILED", "FAILED" not in out, out)
    check("router: five nets routed with 0 new DRC errors", "0 new error(s)" in out, out)
    check("router: unconnected 5 -> 0", "unconnected 5 -> 0" in out, out)
    code, out = k.edit(proj, {"route": ["/USB_DP"]})
    check("router: /USB_DP route is refused", "route refused /USB_DP" in out, out)


# ------------------------------------------------------------------ 5. place
def test_place(k):
    proj = fresh_copy("place")
    code, out = k.prep(proj, [{"unroute_part": "C3"}, {"move": {"ref": "C3", "x": 140.0, "y": 112.0}}])
    check("place: prep moved C3", code == 0 and "prepared" in out, out)
    code, out = k.edit(proj, [{"place": {"ref": "C3", "near": "U1.1", "within": 3}},
                              {"route": ["/+3V3", "/GND"]}])
    m = re.search(r"pad \S+ ([\d.]+) mm from U1\.1", out)
    check("place: C3 pad within 3 mm of U1.1", m and float(m.group(1)) <= 3.0, out)
    check("place: 0 new DRC errors", "0 new error(s)" in out, out)
    check("place: unconnected 2 -> 0", "unconnected 2 -> 0" in out, out)


# ------------------------------------------------------------------ 6. routing plan
def test_plan(k):
    proj = unrouted_copy(k, "plan")
    hook(proj, "prompt", {"prompt": "/boardwright:pcb-plan on"})
    check("plan: mode is on", read_cfg(proj).get("routing_plan") is True)
    code, out = k.edit(proj, {"route": ["/LED_STATUS"]})
    check("plan: route refused with no corridor", "refused" in out and "no corridor" in out, out)
    corridor = {"corridors": [{"id": "c1", "nets": ["/LED_STATUS"], "layers": ["F.Cu"], "width_mm": 0.2,
                               "half_width_mm": 0.6, "path": [[107.5, 116.5], [112.0, 116.5]], "why": "test"}]}
    code, out = k.plan(proj, "propose", json.dumps(corridor))
    check("plan: propose c1 saved", code == 0 and "c1: proposed" in out, out)
    code, out = k.edit(proj, {"route": ["/LED_STATUS"]})
    check("plan: route still refused while proposed", "refused" in out and "proposed" in out, out)
    code, out = hook(proj, "prompt", {"prompt": "/boardwright:pcb-plan approve c1"})
    check("plan: designer approves c1 through the prompt hook", "approved c1" in out, out)
    code, out = k.edit(proj, {"route": ["/LED_STATUS"]})
    check("plan: route succeeds once approved", "FAILED" not in out and "refused" not in out
          and re.search(r"route /LED_STATUS: \d+ track", out), out)
    code, out = k.plan(proj, "verify")
    check("plan: verify prints PASS", code == 0 and "PASS" in out, out)


# ------------------------------------------------------------------ 7. fab rules
def test_fab(k):
    proj = fresh_copy("fab")
    dru = proj / "usb-sensor-test.kicad_dru"
    original = dru.read_text("utf-8")
    run([PY, SCRIPTS / "fab_rules.py", proj, "write", "--fab", "oshpark"])
    t1 = dru.read_text("utf-8")
    check("fab: write adds exactly one profile section", t1.count("# BEGIN Boardwright fab profile") == 1
          and t1.count("# END Boardwright fab profile") == 1)
    check("fab: the section sits right after (version 1)",
          re.match(r"\(version 1\)\s*\n\s*# BEGIN Boardwright fab profile oshpark", t1) is not None, t1[:200])
    run([PY, SCRIPTS / "fab_rules.py", proj, "write", "--fab", "jlcpcb"])
    t2 = dru.read_text("utf-8")
    check("fab: a second write still leaves exactly one section", t2.count("# BEGIN Boardwright fab profile") == 1
          and "profile jlcpcb" in t2 and "profile oshpark" not in t2)

    def outside(t):
        a = t.index("# BEGIN Boardwright fab profile")
        b = t.index("# END Boardwright fab profile") + len("# END Boardwright fab profile")
        return re.sub(r"\s+", " ", t[:a] + t[b:]).strip()
    check("fab: text outside the markers is unchanged",
          outside(t1) == re.sub(r"\s+", " ", original).strip() == outside(t2))
    if not k:
        return
    dru.write_text(t2.rstrip("\n") + '\n(rule "sentinel" (constraint track_width (min 50mm)))\n', "utf-8")
    out_json = proj.parent / "drc-fab.json"
    run([k.cli, "pcb", "drc", "--format", "json", "--severity-all", "-o", out_json, proj / "usb-sensor-test.kicad_pcb"])
    try:
        d = json.loads(out_json.read_text("utf-8-sig"))
    except Exception:
        d = {}
    n = sum(1 for v in d.get("violations", []) if v.get("type") == "track_width")
    check("fab: KiCad loads the rules file (sentinel gives track_width violations)", n > 0, f"{n} track_width violations")


def main():
    t0 = time.time()
    if not EXAMPLE.is_dir():
        print("examples/usb-sensor-test not found")
        return 2
    cli, kpy = find_kicad()
    k = Kicad(cli, kpy) if cli and kpy else None
    try:
        test_history()
        test_hooks()
        if k:
            for t in (test_bw_edit, test_router, test_place, test_plan, test_fab):
                t(k)
        else:
            test_fab(None)
            print("[skip] KiCad not found: skipped bw_edit, router, place, routing plan checks and the fab rules DRC load check")
    finally:
        for t in TMPS:
            shutil.rmtree(t, onerror=_force_remove)
            shutil.rmtree(t, ignore_errors=True)
    bad = RESULTS.count(False)
    print(f"\n{len(RESULTS) - bad} passed, {bad} failed in {time.time() - t0:.0f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
