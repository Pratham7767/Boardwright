"""The deterministic routing engine: KiCadRoutingTools first, Freerouting for what is left, then checks.

    python scripts/engine.py <project> run [--nets PATTERN ...] [--allow-fast] [--dry-run]
                                           [--engines krt,freerouting] [--minutes N]
    python scripts/engine.py <project> status        are the tools installed, and their versions
    python scripts/engine.py <project> leftovers     the last run's leftover list

Runs under the system Python (standard library only); KiCad's Python is used only through subprocesses
(engine_kicad.py). The tools are installed by plugin/scripts/setup_engine.ps1 (Windows) or setup_engine.sh
(Linux, macOS), or from the chat's Setup checks, into the folder named by
BOARDWRIGHT_ENGINE_DIR, else %LOCALAPPDATA%\\Boardwright\\engine (Windows) or ~/.local/share/boardwright/engine,
described by engine.json there.

What `run` does: counts the open connections per net with KiCad's connectivity (complete, unlike the DRC's
unconnected list, which stops at 499); picks the nets with open connections (minus protected nets, nets the
routing plan blocks, and nets with nothing to join); takes the edit lock and saves a history step; routes with
KiCadRoutingTools in its strict mode (never lowers a clearance or size) on a temporary copy of the project,
signal nets first and nets with a copper pour (planes, GND) after them with a shorter limit; routes what is left
with Freerouting, which stops at the time limit and keeps what it routed; checks each stage with KiCad's DRC
against the project as it was: a net whose new copper adds a DRC error is dropped and the rest is checked again
(so one bad net does not throw away a stage); copies the result .kicad_pcb (only that file) over the project's;
writes reports/engine.json and reports/engine.md. Mains and hazardous nets are never routed by the engine; fast nets
(USB and the like) only with --allow-fast. Exit 0 all connections routed and no new errors, 1 leftovers
remain, 2 setup problem.
"""
from __future__ import annotations

import fnmatch
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
sys.path.insert(0, str(HERE))
from bw_project import SetupError, board_nets, md_table, project_files, write_report  # noqa: E402

NOT_INSTALLED = ("the engine tools are not installed: run scripts/setup_engine.ps1 (Windows) or scripts/setup_engine.sh (Linux, macOS) from the plugin, the installer, or Install engine in the chat's Setup")
COPY_IGNORE = shutil.ignore_patterns("fab", ".boardwright", ".git", "reports", "*.lck", "*-backups", "__pycache__",
                                     "datasheets")


class Setup(Exception):
    """A setup problem: exit code 2."""


# ------------------------------------------------------------------ tools
def engine_dir() -> Path:
    env = os.environ.get("BOARDWRIGHT_ENGINE_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Boardwright" / "engine"
    return Path.home() / ".local" / "share" / "boardwright" / "engine"


def find_tools() -> dict:
    cfg = engine_dir() / "engine.json"
    if not cfg.is_file():
        raise Setup(NOT_INSTALLED)
    try:
        t = json.loads(cfg.read_text("utf-8-sig"))
    except ValueError:
        raise Setup(NOT_INSTALLED + " (engine.json is unreadable)")
    if os.environ.get("BOARDWRIGHT_FREEROUTING_JAR"):     # another Freerouting build, e.g. to compare versions
        t["freerouting_jar"] = os.environ["BOARDWRIGHT_FREEROUTING_JAR"]
    for k in ("java", "freerouting_jar", "krt", "krt_python"):
        if not t.get(k) or not Path(t[k]).exists():
            raise Setup(NOT_INSTALLED + f" ('{k}' in engine.json points to nothing)")
    if not (Path(t["krt"]) / "py_router" / "route.py").is_file():
        raise Setup(NOT_INSTALLED + " (KiCadRoutingTools router not found)")
    return t


def kicad_python() -> str:
    import kicad_python
    kpy = kicad_python.find()
    if not kpy:
        raise Setup("KiCad 9 or 10 was not found (its Python and kicad-cli are needed). "
                    "Install KiCad, or set KICAD_CLI to the full path of kicad-cli.")
    return kpy


def sh(cmd, timeout=None, cwd=None, env=None) -> tuple:
    """(returncode, output, timed_out, seconds); output is stdout and stderr together."""
    t0 = time.time()
    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    # Every Python started under the engine (KiCadRoutingTools starts KiCad's Python itself, e.g. to refill zones)
    # loads quiet_site/sitecustomize.py first: it sends KiCad's messages to stderr instead of a message box that
    # would wait for a click.
    quiet_dir = str(Path(__file__).resolve().parent / "quiet_site")
    e["PYTHONPATH"] = quiet_dir + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    try:
        r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=cwd, env=e)
        return r.returncode, (r.stdout or "") + (r.stderr or ""), False, time.time() - t0
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return -1, out, True, time.time() - t0
    except OSError as exc:
        return -1, str(exc), False, time.time() - t0


# ------------------------------------------------------------------ DRC and board copies
def make_copy(proj: Path, dest: Path, board: Path | None = None) -> Path:
    """A copy of the project without history, fab files and datasheets; BOARD (if given) replaces its .kicad_pcb."""
    shutil.copytree(proj, dest, ignore=COPY_IGNORE)
    pcb = project_files(dest)["pcb"]
    if board is not None:
        shutil.copyfile(board, pcb)
    return pcb


UNC = re.compile(r"^Pad (\S+) \[(.*?)\] of (\S+) on ")


def drc_full(pcb: Path, refill: bool = False) -> dict | None:
    """Like bw_edit.drc (same error keys, so bw_edit.drc_diff compares them) plus the unconnected list
    as [(net, 'REF.pad' or a description)] pairs of items. refill: kicad-cli refills the zones first and saves
    the board (pcb must sit in a project copy: kicad-cli then applies the project's own rules file, which
    KiCad's Python refill did not, jetson)."""
    import bw_edit
    cli = bw_edit.find_cli()
    if not cli:
        return None
    out = Path(tempfile.mkdtemp(prefix="bwengdrc")) / "drc.json"
    subprocess.run([cli, "pcb", "drc", "--format", "json", "--severity-all",
                    *(["--refill-zones", "--save-board"] if refill else []), "-o", str(out), str(pcb)],
                   capture_output=True)
    try:
        d = json.loads(out.read_text("utf-8-sig"))
    except (OSError, ValueError):
        return None
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)
    errs = {}
    pos: dict = {}
    for v in d.get("violations", []):
        if v.get("severity") != "error":
            continue
        base = (v.get("type"), tuple(sorted(re.sub(r"[\d.]+ mm", "", i.get("description", ""))
                                            for i in v.get("items", []))))
        # identical errors are numbered, so a new one that repeats an old one still counts as new
        n = 0
        while base + (n,) in errs:
            n += 1
        key = base + (n,)
        errs[key] = v.get("description", "") + ": " + "; ".join(i.get("description", "") for i in v.get("items", []))
        pos[key] = [(i["pos"]["x"], i["pos"]["y"]) for i in v.get("items", []) if isinstance(i.get("pos"), dict)
                    and "x" in i["pos"] and "y" in i["pos"]]
    unc = []
    for u in d.get("unconnected_items", []):
        items = []
        net = ""
        for i in u.get("items", []):
            desc = i.get("description", "")
            m = UNC.match(desc)
            if m:
                items.append(f"{m.group(3)}.{m.group(1)}")
                net = net or m.group(2)
            else:
                n = re.search(r"\[(.*?)\]", desc)
                net = net or (n.group(1) if n else "")
                items.append(desc.split(" on ")[0].replace(f"[{net}] ", "") + f" at {i.get('pos', {}).get('x')},{i.get('pos', {}).get('y')}")
        unc.append((net, items))
    return {"errors": errs, "pos": pos, "unconnected": len(unc), "unconnected_list": unc}


def open_counts(kpy: str, pcb: Path) -> dict:
    """{'open': {net: connections}, 'total': n, 'zone_nets': [...]} from KiCad's connectivity. Unlike the
    DRC's unconnected list (capped at 499 items) this is complete on big boards."""
    rc, out, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "open", pcb], timeout=600)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and "open" in d:
                return d
    raise Setup("KiCad could not count the open connections: " + out.strip()[-200:])


# ------------------------------------------------------------------ choosing nets
def choose(proj: Path, files: dict, open_map: dict, patterns: list, allow_fast: bool) -> tuple:
    """(chosen, left_out {net: why}). open_map: {net: open connections}."""
    import bw_edit
    import routing_plan
    left: dict = {}
    if patterns:
        names = board_nets(files["pcb"])
        cand = []
        for p in patterns:
            hits = [n for n in names if fnmatch.fnmatchcase(n, p)]
            if not hits:
                left[p] = "matches no net on the board"
            cand += [h for h in hits if h not in cand]
        for n in cand:
            if n not in open_map:
                left[n] = "nothing to join (already connected)"
        cand = [n for n in cand if n in open_map]
    else:
        cand = sorted(open_map)
    cand = [n for n in cand if n]
    rules = bw_edit.Rules(proj, files)
    prot = bw_edit.protected_nets(proj, rules, cand)
    hazards = bw_edit.hazardous_nets(proj, rules, cand)
    chosen = []
    plan_block = routing_plan.gate(proj, cand)
    for n in cand:
        if n in hazards:
            left[n] = f"hazardous or mains: never routed by the engine ({hazards[n]})"
            continue
        if n in prot:
            why = prot[n]
            if not allow_fast:
                left[n] = f"fast net, route it by hand or pass --allow-fast ({why})"
                continue
        if n in plan_block:
            left[n] = plan_block[n]
            continue
        chosen.append(n)
    return chosen, left


# ------------------------------------------------------------------ stages
def merge(kpy, base: Path, result: Path, out: Path, nets: list, work: Path) -> tuple:
    nj = work / "nets.json"
    nj.write_text(json.dumps(nets), "utf-8")
    rc, text, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "merge", base, result, out, nj], timeout=300)
    return rc == 0 and out.is_file(), text.strip()[-300:]


def krt_pattern(net: str) -> str:
    """A net name as a KiCadRoutingTools --nets value that matches exactly that net: its patterns are fnmatch
    patterns, so [ ] * ? are put in brackets, and a leading '-' (as in -12V) would be read as an option."""
    out = "".join(f"[{c}]" if c in "[]*?" else c for c in net)
    return "[-]" + out[1:] if out.startswith("-") else out


def stage_dir(proj: Path, work: Path, base: Path, tag: str) -> tuple:
    """A fresh folder for one router run: the board as board.kicad_pcb with the project's own .kicad_pro beside
    it (the router reads the board's rules from it) and an empty out/ folder with the same .kicad_pro, because
    KiCadRoutingTools also reads back the .kicad_pro next to its output. A fresh folder every time keeps runs
    repeatable (a reused output folder changed the next result)."""
    d = work / f"run_{tag}"
    shutil.rmtree(d, ignore_errors=True)
    (d / "out").mkdir(parents=True)
    pro = project_files(proj)["pcb"].with_suffix(".kicad_pro")
    src = d / "board.kicad_pcb"
    shutil.copyfile(base, src)
    if pro.is_file():
        shutil.copyfile(pro, d / "board.kicad_pro")
        shutil.copyfile(pro, d / "out" / "board.kicad_pro")
    return src, d / "out" / "board.kicad_pcb", d


def run_until(cmd, minutes: float, cwd: str, stop_file: Path | None = None, grace: float = 180.0,
              env: dict | None = None) -> tuple:
    """Run cmd with a deadline. With stop_file: at the deadline the file is created (KiCadRoutingTools then
    stops before its next net and writes what it has routed) and the process gets `grace` seconds to finish;
    only then is it killed. -> (returncode, output, killed, seconds)."""
    t0 = time.time()
    e = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONHASHSEED="0", **(env or {}))
    quiet_dir = str(Path(__file__).resolve().parent / "quiet_site")
    e["PYTHONPATH"] = quiet_dir + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    if stop_file is not None:
        e["KICAD_STOP_FILE"] = str(stop_file)
    log = Path(tempfile.mkstemp(prefix="bwrun", suffix=".log")[1])
    try:
        with open(log, "w", encoding="utf-8", errors="replace") as fh:
            try:
                p = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=e, stdout=fh, stderr=subprocess.STDOUT)
            except OSError as exc:
                return -1, str(exc), False, 0.0
            deadline = t0 + minutes * 60
            killed = False
            try:
                p.wait(timeout=max(1.0, deadline - time.time()))
            except subprocess.TimeoutExpired:
                if stop_file is not None:
                    stop_file.write_text("stop", "utf-8")
                    try:
                        p.wait(timeout=grace)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait()
                        killed = True
                else:
                    p.kill()
                    p.wait()
                    killed = True
        out = log.read_text("utf-8", errors="replace")
        return p.returncode, out, killed, time.time() - t0
    finally:
        try:
            log.unlink()
        except OSError:
            pass


def krt_stage(tools: dict, kpy: str, base: Path, work: Path, nets: list, minutes: float, tag: str = "krt",
              proj: Path | None = None, env: dict | None = None, grace: float = 180.0) -> dict:
    src, raw, d = stage_dir(proj, work, base, tag)
    summary = d / "summary.json"
    stop = d / "STOP"
    router = Path(tools["krt"]) / "py_router"
    cmd = [tools["krt_python"], router / "route.py", src, "--output", raw, "--nets", *[krt_pattern(n) for n in nets],
           "--escalation", "off", "--strict-sizes", "--no-fix-drc-settings", "--fab-tier", "standard",
           "--json-out", summary]
    # one run over all the nets, stopped by its own stop file at the time limit: it then keeps what it routed
    rc, out, killed, secs = run_until(cmd, minutes, str(router), stop_file=stop, grace=grace, env=env)
    res = {"engine": tag, "seconds": round(secs, 1), "raw": None, "routed": [], "failed": [],
           "stopped_at_limit": stop.exists()}
    if killed:
        res["error"] = f"did not stop within {minutes:g} minutes plus its grace time"
        return res
    try:
        s = json.loads(summary.read_text("utf-8"))
        res["routed"] = list(s.get("routed_single", []))
        res["failed"] = list(s.get("failed_single", [])) + list(s.get("open_single", [])) + \
            list(s.get("failed_multipoint", []))
    except (OSError, ValueError):
        if not raw.is_file():
            res["error"] = f"no summary from KiCadRoutingTools (exit {rc}): " + " | ".join(
                l for l in out.splitlines() if l.strip() and "swig" not in l)[-300:]
            return res
    if not raw.is_file():
        res["error"] = f"KiCadRoutingTools wrote no board (exit {rc})"
        return res
    res["raw"] = raw
    return res


def planes_stage(tools: dict, kpy: str, base: Path, work: Path, nets: list, minutes: float, proj: Path) -> dict:
    """Nets with a copper pour (GND, power planes): KiCadRoutingTools' plane repair joins their pads and split
    areas to the existing pour with short taps and vias, instead of routing them as tracks across the board.
    It does not rip up other nets (that needs --rip-blocker-nets, not passed)."""
    src, raw, d = stage_dir(proj, work, base, "planes")
    router = Path(tools["krt"]) / "py_router"
    cmd = [tools["krt_python"], router / "repair_planes.py", src, raw, "--nets", *[krt_pattern(n) for n in nets],
           # the same strict mode as the router: no smaller "last resort" vias or narrower tracks than the board
           # allows, and the project's rules file left as it is
           "--escalation", "off", "--fab-tier", "standard", "--no-fix-drc-settings"]
    # the board's own sizes and clearances (its defaults made 0.15 mm drills on a board that allows 0.4 mm)
    r = board_rules(kpy, base)
    for flag, key in (("--via-size", "via_um"), ("--via-drill", "drill_um"), ("--clearance", "clearance_um"),
                      ("--board-edge-clearance", "edge_um"), ("--hole-to-hole-clearance", "hole_to_hole_um"),
                      ("--min-track-width", "width_um")):
        if r.get(key):
            cmd += [flag, f"{r[key] / 1000:.4f}"]
    rc, out, killed, secs = run_until(cmd, minutes, str(router))
    res = {"engine": "krt-planes", "seconds": round(secs, 1), "raw": None}
    if killed:
        res["error"] = f"timed out after {minutes:g} minutes"
    elif not raw.is_file():
        res["error"] = f"the plane repair wrote no board (exit {rc}): " + " | ".join(
            l for l in out.splitlines() if l.strip())[-200:]
    else:
        res["raw"] = raw
    return res


def board_rules(kpy: str, pcb: Path) -> dict:
    """The board's own limits from KiCad (µm): edge clearance, hole clearance, minimum track width."""
    rc, out, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "rules", pcb], timeout=300)
    for line in reversed(out.splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                pass
    return {}


def freerouting_stage(tools: dict, kpy: str, base: Path, work: Path, minutes: float, rules: dict | None = None) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    dsn, ses, raw = work / "fr.dsn", work / "fr.ses", work / "fr_raw.kicad_pcb"
    res = {"engine": "freerouting", "seconds": 0.0, "raw": None}
    t0 = time.time()
    rc, out, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "dsn", base, dsn], timeout=300)
    if rc != 0 or not dsn.is_file():
        res["error"] = "KiCad could not export the Specctra DSN: " + out.strip()[-200:]
        return res
    # Freerouting's own time limit: when it is reached Freerouting stops and still saves what it routed
    # (tested with 2.5.0). The outer limit only catches a hang.
    secs = max(60, int(minutes * 60))
    limit = f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    cmd = [tools["java"], "-jar", tools["freerouting_jar"], "-de", dsn, "-do", ses, "--gui.enabled=false",
           "--router.autorouter.max_passes=30", f"--router.job_timeout={limit}", "--router.optimizer.enabled=false",
           # no narrowing of tracks near small pads (it went under the board's minimum width: video benchmark),
           # and Freerouting's own clearance checks on
           "--router.automatic_neckdown=false", "--router.strict_drc=true", "--router.clearance_tolerance_um=0",
           # repeatable: a fixed item order (two runs with the same seed gave identical files) and one thread
           "--router.autorouter.item_order_seed=1", "--router.max_threads=1"]
    cmd += os.environ.get("BOARDWRIGHT_FREEROUTING_ARGS", "").split()    # extra settings, for experiments
    # KiCad's DSN export carries no copper-to-edge clearance; Freerouting then uses its own default (250 um),
    # which it lowers to the smallest pad-to-edge gap on the board (down to 0). So the board's own values go
    # in explicitly. 250 itself counts as "the default" there, so it is passed as 251 (stricter, never looser).
    rules = rules or {}
    if rules.get("edge_um"):
        edge = max(1, int(-(-rules["edge_um"] // 1)))
        cmd.append(f"--router.copper_to_edge_clearance_um={251 if edge == 250 else edge}")
    if rules.get("hole_um"):
        cmd.append(f"--router.hole_clearance_um={int(-(-rules['hole_um'] // 1))}")
    if rules.get("min_width_um"):
        cmd.append(f"--router.neck_width_um={int(-(-rules['min_width_um'] // 1))}")
    rc, out, timed_out, _s = sh(cmd, timeout=secs + 300, cwd=str(work))
    res["seconds"] = round(time.time() - t0, 1)
    res["edge_rule_applied"] = "copper-to-edge clearance override" in out.lower() or None
    if timed_out:
        res["error"] = f"Freerouting did not stop at its {minutes:g} minute limit"
        return res
    if not ses.is_file():
        res["error"] = f"Freerouting wrote no session (exit {rc}): " + " | ".join(
            l for l in out.splitlines() if l.strip())[-200:]
        return res
    rc, out, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "ses", base, ses, raw], timeout=300)
    res["seconds"] = round(time.time() - t0, 1)
    if rc != 0 or not raw.is_file():
        res["error"] = "KiCad could not import the Freerouting session: " + out.strip()[-200:]
        return res
    res["raw"] = raw
    return res


NET_IN = re.compile(r"\[([^\]]+)\]")


def nets_near(kpy: str, merged: Path, raw: Path, spots: list, nets: list, radius_mm: float = 1.5) -> list:
    """The listed nets that have router copper (in raw) within radius_mm of any of the spots (mm)."""
    if not spots or not nets:
        return []
    req = Path(tempfile.mkstemp(prefix="bwnear", suffix=".json")[1])
    try:
        req.write_text(json.dumps({"spots": spots, "nets": nets, "radius": radius_mm}), "utf-8")
        rc, out, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "near", raw, req], timeout=300)
    finally:
        try:
            req.unlink()
        except OSError:
            pass
    for line in reversed(out.splitlines()):
        if line.strip().startswith("["):
            try:
                return [n for n in json.loads(line) if n in nets]
            except ValueError:
                pass
    return []


def evaluate(proj, kpy, work, name, st, base_open, orig_drc, nets, base_pcb) -> dict:
    """Merge a stage's copper (listed nets only) into the base and check it with KiCad's DRC. A net whose
    new copper causes a new DRC error is dropped (it stays open for the next stage or for Claude) and the
    rest is checked again, so one bad net no longer throws away a whole stage. Fills st."""
    if st.get("raw") is None:
        st["accepted"] = False
        st["why"] = st.get("error", "no result")
        return st
    import bw_edit
    keep = list(nets)
    dropped: dict = {}
    merged, d, lines, new = None, None, [], []
    for attempt in range(12):
        merged = work / f"{name}_merged{attempt}.kicad_pcb"
        ok, text = merge(kpy, base_pcb, st["raw"], merged, keep, work)
        if not ok:
            st["accepted"] = False
            st["why"] = "could not merge the result into the board: " + text
            return st
        # Checked on a project copy whose zones kicad-cli refills with the project's own rules. The next stage
        # still gets the merged board itself: routers given the kicad-cli refilled board routed far less (video,
        # 85 nets against 172). The board written to the project is refilled by kicad-cli at the end.
        d = drc_full(make_copy(proj, work / f"chk_{name}{attempt}", merged), refill=True)
        if d is None:
            raise Setup("KiCad's DRC could not be run (kicad-cli not found or failed)")
        lines, _new = bw_edit.drc_diff(orig_drc, d)
        new = [d["errors"][k] for k in d["errors"] if k not in orig_drc["errors"]]
        if not new:
            # copper merged for a net replaces all of its old copper: if a router dropped existing segments,
            # the net is now more open than before; keep its old copper instead
            op = open_counts(kpy, merged)
            worse = {n: f"left it more open ({base_open.get(n, 0)} -> {op['open'].get(n, 0)} connections)"
                     for n in keep if op["open"].get(n, 0) > base_open.get(n, 0)}
            if not worse:
                break
            dropped.update(worse)
            keep = [n for n in keep if n not in worse]
            if not keep:
                break
            continue
        bad = {}
        # DRC texts show KiCad's escaped net names unescaped ("/VPP{slash}MCLR" reads "/VPP/MCLR")
        alias = {n.replace("{slash}", "/").replace("{backslash}", "\\"): n for n in keep}
        alias.update({n: n for n in keep})
        for txt in new:
            for shown in NET_IN.findall(txt):
                n = alias.get(shown)
                if n and n not in bad:
                    bad[n] = txt[:200]
        if not bad:
            # No routed net is named (e.g. a custom rule between an old pad and a refilled pour, jetson): blame
            # the nets whose new copper lies near where DRC put the error.
            spots = [xy for k in d["errors"] if k not in orig_drc["errors"] for xy in d.get("pos", {}).get(k, [])]
            for n in nets_near(kpy, merged, st["raw"], spots, keep, 3.0):
                bad[n] = "new copper near a DRC error that names no routed net"
        if not bad:
            break                               # an error no net can be blamed for: reject the stage
        dropped.update(bad)
        keep = [n for n in keep if n not in bad]
        if not keep:
            break
    op = open_counts(kpy, merged) if keep else open_counts(kpy, base_pcb)
    st["board"] = merged
    st["drc"] = d
    st["open"] = op
    st["drc_lines"] = lines
    st["dropped"] = dropped
    st["routed_nets"] = sorted(n for n in keep if n in base_open and n not in op["open"])
    st["still_open"] = sorted(n for n in nets if n in op["open"])
    st["accepted"] = not new and bool(keep)
    if new:
        st["why"] = "adds new DRC errors: " + "; ".join(l.strip()[:160] for l in lines[1:4])
    elif not keep:
        st["why"] = "every net it routed caused a new DRC error"
    elif dropped:
        st["why"] = f"kept {len(keep)} net(s); dropped {len(dropped)} that caused DRC errors: " + \
            ", ".join(list(dropped)[:6])
    return st


# ------------------------------------------------------------------ report
KRT_MAX_OPEN = 1000                             # above this many open connections KiCadRoutingTools is skipped
FR_ROUNDS_BIG = 4                               # Freerouting rounds at most on a big board, while each helps
BIG_POUR = 60                                   # open connections above which a pour net gets its own pass
DRC_CAP = 499                                   # kicad-cli lists at most this many unconnected items


def leftover_rows(drc: dict, open_map: dict) -> list:
    """Connection by connection from the DRC when its list is complete; else per net from the connectivity."""
    if drc and drc["unconnected"] < DRC_CAP:
        rows = [f"{net or '(no net)'}: " + " -> ".join(items) for net, items in drc["unconnected_list"]]
    else:
        rows = [f"{net}: {k} connection(s) open" for net, k in open_map.items()]
    return sorted(rows)


def write_reports(proj: Path, data: dict) -> None:
    md = ["# Engine run", "",
          f"Result: {data['result']}.", "",
          f"Nets chosen ({len(data['chosen'])}): {', '.join(data['chosen']) or 'none'}", ""]
    md += ["## Stages", ""]
    md += md_table(["stage", "seconds", "routed nets", "accepted", "note"],
                   [[s["engine"], s["seconds"], ", ".join(s.get("routed_nets", [])) or "-",
                     "yes" if s.get("accepted") else "no", s.get("why", "")] for s in data["stages"]]) or [""]
    md += ["", "## Nets left out", ""]
    md += [f"- `{n}`: {w}" for n, w in data["left_out"].items()] or ["- none"]
    md += ["", f"## Leftovers: {len(data['leftovers'])} connection(s)", ""]
    md += [f"- {r}" for r in data["leftovers"]] or ["- none"]
    md += ["", "## Check", ""] + [f"- {l}" for l in data.get("drc_lines", [])]
    md += ["", f"Total time {data['seconds']} s. Dry run: {'yes' if data['dry_run'] else 'no'}."]
    write_report(proj, "engine", data, md)


# ------------------------------------------------------------------ commands
def cmd_status(proj: Path) -> int:
    try:
        t = find_tools()
    except Setup as exc:
        print(f"ERROR: {exc}")
        return 2
    rc, out, _x, _s = sh([t["java"], "-version"], timeout=30)
    jv = out.strip().splitlines()[0] if out.strip() else "unknown"
    krt_v = Path(t["krt"]) / "VERSION"
    print(f"engine folder: {engine_dir()}")
    print(f"java: {jv}")
    print(f"freerouting: {Path(t['freerouting_jar']).name}")
    print(f"KiCadRoutingTools: {krt_v.read_text('utf-8').strip() if krt_v.is_file() else 'unverified version'}")
    rc, out, _x, _s = sh([t["krt_python"], "--version"], timeout=30)
    print(f"krt python: {out.strip()}")
    try:
        print(f"KiCad python: {kicad_python()}")
    except Setup as exc:
        print(f"KiCad python: missing ({exc})")
    return 0


def cmd_leftovers(proj: Path) -> int:
    p = proj / "reports" / "engine.json"
    if not p.is_file():
        print("no engine run yet (reports/engine.json is missing)")
        return 0
    d = json.loads(p.read_text("utf-8"))
    print(f"last engine run: {d.get('result')}; leftovers: {len(d.get('leftovers', []))}")
    for r in d.get("leftovers", []):
        print("  " + r)
    for n, w in d.get("left_out", {}).items():
        print(f"  left out {n}: {w}")
    return 0


def cmd_run(proj: Path, args: list) -> int:
    t_start = time.time()
    allow_fast = "--allow-fast" in args
    dry = "--dry-run" in args
    patterns, engines, minutes = [], ["krt", "freerouting"], 10.0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--nets":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                patterns.append(args[i])
                i += 1
            continue
        if a == "--engines":
            if i + 1 >= len(args):
                raise Setup("--engines needs a value, e.g. --engines krt,freerouting")
            engines = [e.strip() for e in args[i + 1].split(",") if e.strip()]
            i += 1
        elif a == "--minutes":
            try:
                minutes = float(args[i + 1])
            except (IndexError, ValueError):
                raise Setup("--minutes needs a number, e.g. --minutes 10")
            if minutes <= 0:
                raise Setup("--minutes must be more than 0")
            i += 1
        elif a not in ("--allow-fast", "--dry-run"):
            raise Setup(f"unknown option {a}")
        i += 1
    bad = [e for e in engines if e not in ("krt", "freerouting")]
    if bad:
        raise Setup(f"unknown engine {bad[0]} (krt, freerouting)")

    # the editor that runs the engine (the MCP server, or a session through the hooks) passes its lock name,
    # so the engine works under that lock instead of finding it "taken by someone else"
    who = os.environ.get("BOARDWRIGHT_LOCK_WHO") or "engine"
    tools = find_tools()                                              # 1
    kpy = kicad_python()
    files = project_files(proj)
    pcb = files["pcb"]
    lck = pcb.parent / f"~{pcb.name}.lck"
    if lck.exists():                                                  # 2
        raise Setup(f"close the board in KiCad first (found {lck.name}); nothing was changed")
    import bw_edit
    import history
    work = Path(tempfile.mkdtemp(prefix="bwengine"))
    holder = False
    try:
        base_pcb = make_copy(proj, work / "base")
        # The baseline errors are found the same way every result is checked (kicad-cli refills the zones with the
        # project's rules), so pour shapes that only a refill changes do not count as new errors (jetson). That
        # refill happens on a separate copy: the routers start from the board as it is (from a refilled start
        # Freerouting routed half as much on video).
        orig = drc_full(make_copy(proj, work / "base_check"), refill=True)
        if orig is None:
            raise Setup("KiCad's DRC could not be run (kicad-cli not found or failed)")
        op0 = open_counts(kpy, base_pcb)
        chosen, left = choose(proj, files, op0["open"], patterns, allow_fast)   # 3
        zone_nets = set(op0.get("zone_nets", []))
        if not dry:                                                   # 4
            other = history.lock_take(proj, who, "engine run")
            if other:
                raise Setup("someone else is editing this project: " + history.describe(other))
            holder = True
            history.Store(proj).snap("before engine run")
        board_limits = board_rules(kpy, base_pcb)

        def route_variant(steps: list, vwork: Path, venv: dict | None = None) -> dict:
            """One routing sequence on its own copies, in its own folder. Every stage is checked by KiCad's DRC
            against the project as it was (evaluate), so every variant's result is DRC-clean."""
            vwork.mkdir(parents=True, exist_ok=True)
            v = {"pcb": base_pcb, "open": dict(op0["open"]), "drc": orig, "board": None, "stages": []}

            def run_stage(st, name, nets):
                evaluate(proj, kpy, vwork, name, st, v["open"], orig, nets, v["pcb"])
                v["stages"].append(st)
                if st.get("accepted") and st.get("board"):
                    v["pcb"], v["drc"] = st["board"], st["drc"]
                    v["open"] = dict(st["open"]["open"])
                    v["board"] = st["board"]

            for step in steps:
                cur_open = v["open"]
                big = {n for n in chosen if n in zone_nets and cur_open.get(n, 0) > BIG_POUR}
                if step in ("krt", "krt2"):
                    # Signal nets and small pour nets in one KiCadRoutingTools run (small pour nets need the
                    # others: routed alone it routed none of them, stickhub), stopped by its stop file at the
                    # limit so it keeps what it routed. On a very big board its setup took more than 30 minutes
                    # before the first net (video, jetson): there it is skipped.
                    nets = [n for n in chosen if n not in zone_nets and n in cur_open] + \
                        [n for n in chosen if n in zone_nets and n not in big and n in cur_open]
                    if not nets:
                        continue
                    # the leftovers pass gets the full limit too: with half, how far it got depended on the load
                    # from the other variants (cm5: 10 or 24 open in two runs)
                    t = minutes
                    if sum(cur_open.values()) > KRT_MAX_OPEN:
                        # Big board: skipped. Its full setup took more than 30 minutes before the first net; its
                        # lean setup (an obstacle cache only for the routed nets) was fast, but routed in batches
                        # it left more open than Freerouting alone (video: 636 against 375) and every batch on
                        # jetson ran out of time. See docs/research/pathfinder-plan.md.
                        v["stages"].append({"engine": step, "seconds": 0.0, "accepted": False, "routed_nets": [],
                                            "why": f"skipped on a board this big ({sum(cur_open.values())} open "
                                                   "connections): Freerouting does better there"})
                        continue
                    run_stage(krt_stage(tools, kpy, v["pcb"], vwork, nets, t, step, proj, env=venv), step, nets)
                elif step == "planes":
                    # Big pour nets (the GND of a big board) joined to their pour with short taps and vias by the
                    # plane repair, not routed as tracks (GND alone took 15 minutes as tracks, jetson).
                    pours = [n for n in chosen if n in big and n in cur_open]
                    if pours:
                        run_stage(planes_stage(tools, kpy, v["pcb"], vwork, pours, min(minutes, 10), proj),
                                  "krt-planes", pours)
                elif step == "fr":
                    # Freerouting may only touch the nets still open; the merge keeps every other net as it was.
                    # On a big board it stops at the time limit long before it is done (video, jetson), so it runs
                    # again from the board as kept, while a round still closes at least 1 % of what is open.
                    rounds = FR_ROUNDS_BIG if sum(op0["open"].values()) > KRT_MAX_OPEN else 1
                    for r in range(1, rounds + 1):
                        todo = [n for n in chosen if n in v["open"]]
                        if not todo:
                            break
                        before = sum(v["open"].values())
                        tag = "freerouting" if r == 1 else f"freerouting-{r}"
                        run_stage(freerouting_stage(tools, kpy, v["pcb"], vwork / tag, minutes, board_limits),
                                  tag, todo)
                        if sum(v["open"].values()) > before * 0.99:
                            break
            for s in v["stages"]:
                s.pop("raw", None)
            return v

        # A small portfolio (research plan, rank 6): KiCadRoutingTools first, and Freerouting first (on an
        # independent benchmark of medium boards Freerouting passed clean more often). Both run at the same time
        # in their own folders; the one with the fewest open connections wins, ties go to the first, so the
        # choice is fixed for the same results. Each ends with a short KiCadRoutingTools pass on the leftovers.
        # (name, steps, environment for KiCadRoutingTools). "planned" switches on its global planning pass
        # (#589: rough-route every net first, then a plan-informed net order and light corridor reservations;
        # the order and the 0.05 cost are what its upstream tests found best). Its PathFinder-style history
        # costs (#590) are on in every variant (its default).
        planned = {"KICAD_GLOBAL_PLAN": "1", "KICAD_GLOBAL_PLAN_COST": "0.05"}
        sequences = {"krt-first": (["krt", "planes", "fr", "krt2"], None),
                     "freerouting-first": (["planes", "fr", "krt2"], None),
                     "planned-krt-first": (["krt", "planes", "fr", "krt2"], planned)}
        if sum(op0["open"].values()) > KRT_MAX_OPEN and "freerouting" in engines:
            sequences = {"planes-freerouting": (["planes", "fr"], None)}   # measured best on video and jetson
        elif "krt" not in engines:
            sequences = {"freerouting": (["planes", "fr"], None)} if "freerouting" in engines else {}
        elif "freerouting" not in engines:
            sequences = {"krt": (["krt", "planes", "krt2"], None), "planned-krt": (["krt", "planes", "krt2"], planned)}
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(sequences) or 1) as ex:
            futs = {name: ex.submit(route_variant, steps, work / f"variant_{name}", venv)
                    for name, (steps, venv) in sequences.items()}
            variants = {name: f.result() for name, f in futs.items()}
        best_name = min(variants, key=lambda n: (sum(variants[n]["open"].values()), list(variants).index(n))) \
            if variants else None
        best = variants.get(best_name) or {"pcb": base_pcb, "open": dict(op0["open"]), "drc": orig, "board": None,
                                           "stages": []}
        cur_open, cur_drc, result_board = best["open"], best["drc"], best["board"]
        stages = [dict(s, engine=f"{s['engine']}" if len(variants) == 1 else f"{best_name}: {s['engine']}")
                  for s in best["stages"]]
        variant_summary = {n: sum(v["open"].values()) for n, v in variants.items()}
        final_drc = cur_drc

        def routed_by(prefix):
            return sum(len(s.get("routed_nets", [])) for s in stages
                       if s["engine"].split(": ")[-1].startswith(prefix) and s.get("accepted"))
        nk, nf = routed_by("krt"), routed_by("freerouting")
        routed_total = len([n for n in chosen if n not in cur_open])
        drc_lines, new_err = bw_edit.drc_diff(orig, final_drc)
        before_total = op0["total"]
        after_total = sum(cur_open.values())
        drc_lines[0] = re.sub(r"unconnected \d+ -> \d+", f"open connections {before_total} -> {after_total}",
                              drc_lines[0])
        left_rows = leftover_rows(final_drc, cur_open)
        left_now = {n: w for n, w in left.items()}
        result = (f"routed {routed_total} of {len(chosen)} chosen net(s) (krt {nk}, freerouting {nf}); "
                  f"open connections {before_total} -> {after_total}" if chosen else "no net to route")
        data = {"result": result, "dry_run": dry, "chosen": chosen, "left_out": left_now, "leftovers": left_rows,
                "open_before": before_total, "open_after": after_total, "variants": variant_summary,
                "drc_lines": drc_lines, "seconds": round(time.time() - t_start, 1),
                "stages": [{k: v for k, v in s.items() if k in
                            ("engine", "seconds", "routed_nets", "still_open", "accepted", "why", "error",
                             "failed", "drc_lines", "dropped")} for s in stages]}
        if result_board is not None and not dry:                      # 7
            if lck.exists():
                raise Setup(f"KiCad opened the board while the engine ran ({lck.name}); nothing was written")
            # the board written is refilled by kicad-cli with the project's rules (the routers' chained boards
            # were refilled by KiCad's Python), and checked once more: written only if it still adds no error
            final = make_copy(proj, work / "final", result_board)
            fd = drc_full(final, refill=True)
            if fd is None:
                raise Setup("KiCad's DRC could not check the final board; nothing was written")
            flines, fbad = bw_edit.drc_diff(orig, fd)
            if fbad:
                raise Setup("the final board did not pass KiCad's DRC after its zones were refilled; nothing was "
                            "written (" + "; ".join(l.strip() for l in flines[1:3]) + ")")
            shutil.copyfile(final, pcb)
            history.Store(proj).snap(f"engine: routed {routed_total} nets (krt {nk}, freerouting {nf})")
        if not dry:                                                   # 8
            write_reports(proj, data)
        # summary
        out = [f"engine run{' (dry run, nothing written)' if dry else ''}: {result}"]
        out.append(f"chosen {len(chosen)}: {', '.join(chosen[:40]) or 'none'}"
                   + (f" ... and {len(chosen) - 40} more" if len(chosen) > 40 else ""))
        for n, w in left.items():
            out.append(f"left out {n}: {w[:110]}")
        if len(variant_summary) > 1:
            out.append("variants (open connections after): " + ", ".join(f"{n} {k}" for n, k in variant_summary.items())
                       + f"; kept {best_name}")
        for s in stages:
            out.append(f"{s['engine']}: {'ACCEPTED' if s.get('accepted') else 'REJECTED'} in {s['seconds']} s; "
                       f"routed {len(s.get('routed_nets', []))} net(s)"
                       + (f"; {s['why'][:150]}" if s.get("why") else ""))
        out += [l[:200] for l in drc_lines[:4]]
        if result_board is None and chosen:
            out.append("no stage was accepted: the project board is unchanged")
        out.append(f"time {round(time.time() - t_start, 1)} s")
        out.append(f"Leftovers for Claude: {after_total} connection(s) on {len(cur_open)} net(s)")
        for r in left_rows[:12]:
            out.append("  " + r[:160])
        if len(left_rows) > 12:
            out.append(f"  ... {len(left_rows) - 12} more in reports/engine.md")
        if left_rows:
            out.append("Handle them with bw_edit.py ({\"route\": [net]} or {\"add\": ...}); protected nets "
                       "(hazardous, fast) by hand, then check.")
        print("\n".join(out))
        return 1 if after_total or new_err else 0
    finally:
        if holder:
            history.lock_release(proj, who)
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list) -> int:
    if len(argv) < 2 or argv[1] not in ("run", "status", "leftovers"):
        print(__doc__)
        return 2
    proj = Path(argv[0]).resolve()
    try:
        project_files(proj)
        if argv[1] == "status":
            return cmd_status(proj)
        if argv[1] == "leftovers":
            return cmd_leftovers(proj)
        return cmd_run(proj, argv[2:])
    except (Setup, SetupError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main(sys.argv[1:]))
