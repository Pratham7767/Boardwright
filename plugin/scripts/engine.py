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
from bw_project import SetupError, board_nets, load_config, md_table, project_files, write_report  # noqa: E402

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
    if os.environ.get("BOARDWRIGHT_KRT_DIR"):             # another KiCadRoutingTools, e.g. to compare versions
        t["krt"] = os.environ["BOARDWRIGHT_KRT_DIR"]
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
    """(chosen, left_out {net: why}, fast: the chosen nets that are fast). open_map: {net: open connections}."""
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
    return chosen, left, [n for n in chosen if n in prot]


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


# set by cmd_run: the nets no router may move (pairs, and the fast and hazardous nets it left out)
FROZEN: dict = {"nets": []}


def guard_text(kpy: str, pcb: Path, out: Path) -> Path:
    """out = pcb with keep-outs over its copper-layer text and the FROZEN nets' copper locked (see engine_kicad
    textguard); pcb itself if that fails. Only the routers' working copies get this."""
    extra = []
    if FROZEN["nets"]:
        extra = [out.with_suffix(".frozen.json")]
        extra[0].write_text(json.dumps(sorted(FROZEN["nets"])), "utf-8")
    rc, _o, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "textguard", pcb, out, *extra], timeout=300)
    return out if rc == 0 and out.is_file() else pcb


def stage_dir(proj: Path, work: Path, base: Path, tag: str, kpy: str | None = None) -> tuple:
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
    if kpy:
        guard_text(kpy, src, src)
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
    fd, name = tempfile.mkstemp(prefix="bwrun", suffix=".log")
    os.close(fd)                                     # Windows cannot reopen or delete a file still open
    log = Path(name)
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
              proj: Path | None = None, env: dict | None = None, grace: float = 180.0,
              layout: dict | None = None) -> dict:
    src, raw, d = stage_dir(proj, work, base, tag, kpy)
    summary = d / "summary.json"
    stop = d / "STOP"
    router = Path(tools["krt"]) / "py_router"
    cmd = [tools["krt_python"], router / "route.py", src, "--output", raw, "--nets", *[krt_pattern(n) for n in nets],
           "--escalation", "off", "--strict-sizes", "--no-fix-drc-settings", "--fab-tier", "standard",
           "--json-out", summary, *no_via_in_pad(kpy, base)]
    if layout and layout.get("planes") and layout.get("copper"):
        # plane layers forbidden for tracks (vias may still pass through), the others at their usual cost
        names = layout.get("standard") or layout["copper"]
        cmd += ["--layers", *names,
                "--layer-costs", *["-1" if l in layout["planes"] else "1.0" for l in layout["copper"]]]
    # one run over all the nets, stopped by its own stop file at the time limit: it then keeps what it routed
    cmd += os.environ.get(f"BOARDWRIGHT_{tag.upper()}_ARGS", "").split()    # extra settings, for experiments
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


def planes_stage(tools: dict, kpy: str, base: Path, work: Path, nets: list, minutes: float, proj: Path,
                 layout: dict | None = None) -> dict:
    """Nets with a copper pour (GND, power planes): KiCadRoutingTools' plane repair joins their pads and split
    areas to the existing pour with short taps and vias, instead of routing them as tracks across the board.
    It does not rip up other nets (that needs --rip-blocker-nets, not passed)."""
    src, raw, d = stage_dir(proj, work, base, "planes", kpy)
    router = Path(tools["krt"]) / "py_router"
    cmd = [tools["krt_python"], router / "repair_planes.py", src, raw, "--nets", *[krt_pattern(n) for n in nets],
           # the same strict mode as the router: no smaller "last resort" vias or narrower tracks than the board
           # allows, and the project's rules file left as it is
           "--escalation", "off", "--fab-tier", "standard", "--no-fix-drc-settings"]
    if layout and layout.get("planes") and layout.get("copper"):
        # no tracks on any plane layer (it put GND tracks on kit-dev's +3.3V plane); vias still pass through
        cmd += ["--layers", *(layout.get("standard") or layout["copper"]),
                "--layer-costs", *["-1" if l in layout["planes"] else "1.0" for l in layout["copper"]]]
    # the board's own sizes and clearances (its defaults made 0.15 mm drills on a board that allows 0.4 mm)
    r = board_rules(kpy, base)
    # the repaired nets' own net classes (GND at 0.4 mm on kit-dev, not the board's 0.2 mm default): one run
    # repairs them all, so the largest class size of those nets is used for each, never one below its class
    cls = [v for n, v in (r.get("pour_classes") or {}).items() if n in nets]
    for i, key in enumerate(("width_um", "via_um", "drill_um")):
        if cls:
            r[key] = max([r.get(key) or 0] + [c[i] for c in cls])
    for flag, key in (("--via-size", "via_um"), ("--via-drill", "drill_um"), ("--clearance", "clearance_um"),
                      ("--board-edge-clearance", "edge_um"), ("--hole-to-hole-clearance", "hole_to_hole_um"),
                      ("--min-track-width", "width_um"), ("--track-width", "width_um")):
        if r.get(key):
            cmd += [flag, f"{r[key] / 1000:.4f}"]
    cmd += no_via_in_pad(kpy, base)
    cmd += os.environ.get("BOARDWRIGHT_PLANES_ARGS", "").split()          # extra settings, for experiments
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


PAIR_ENDS = (("_P", "_N"), ("_DP", "_DM"), ("DP", "DM"), ("P", "N"), ("+", "-"))


def pair_members(nets: list, board: list | None = None) -> list:
    """The nets of `nets` whose partner (same name, the other end of P/N, DP/DM or +/-) is in `nets`, or on the
    board (`board`: all its nets), with those partners: a pair is routed whole even if one half was done."""
    have, out = set(board if board is not None else nets), set()
    for n in nets:
        for a, b in PAIR_ENDS:
            for x, y in ((a, b), (b, a)):
                if n.endswith(x) and n[:-len(x)] + y in have:
                    out.update((n, n[:-len(x)] + y))
    return sorted(out)


def accepted_pairs(report: dict) -> list:
    """[p, n, p, n ...] of the pair router's report that may be merged: pairs routed coupled the whole way with
    both members complete. Not a pair it routed as two single tracks, even one it calls electrically short: that
    length floor grows with the class's pair spacing and was 100 mm on jetson, where PCIe pairs must couple."""
    return [n for pr in report.get("pair_reports", [])
            if pr.get("outcome") == "coupled" and not pr.get("incomplete_members")
            for n in (pr["p_net"], pr["n_net"])]


def pair_groups(sizes_file: str, pairs: list, layout: dict) -> list:
    """[(layers, width mm, gap mm, [nets])]: the pair members grouped by the layers they may use and the width
    and gap the project's rules give them there (engine_rules.py). Where a pair's sizes are the same on every
    non-plane layer it may use all of them; where they differ by layer (jetson: 0.17/0.18 mm outside, 0.125/0.10
    mm inside) only the layers sharing the outer layers' sizes, where the pads are: the pair router takes one
    width and gap per run, and a pair laid at another layer's size has the wrong impedance. Pairs whose sizes
    are unknown form one group with no explicit size (the router's own reading of the rules)."""
    try:
        sizes = json.loads(Path(sizes_file).read_text("utf-8"))["sizes"] if sizes_file else {}
    except (OSError, ValueError, KeyError):
        sizes = {}
    std = layout.get("standard") or layout.get("copper") or []
    plane_std = {std[i] for i, l in enumerate(layout.get("copper") or []) if l in (layout.get("planes") or {})}
    groups: dict = {}
    for n in pairs:
        per = {l: v for l, v in (sizes.get(n) or {}).items() if l not in plane_std and v and v[0] and v[3]}
        if not per or not std:
            groups.setdefault(((), 0.0, 0.0), []).append(n)
            continue
        outer = per.get(std[0]) or per.get(std[-1]) or next(iter(per.values()))
        w, g = outer[0], outer[3]
        layers = tuple(l for l in std if l in per and per[l][0] == w and per[l][3] == g)
        groups.setdefault((layers, w, g), []).append(n)
    return [(k[0], k[1], k[2], v) for k, v in groups.items()]


# pairs per pair router run: jetson's 42-pair group ran out of 15 minutes in one run and kept nothing
PAIR_CHUNK = int(os.environ.get("BOARDWRIGHT_PAIR_CHUNK", "") or 12)


def pair_chunks(nets: list, size: int = PAIR_CHUNK) -> list:
    """The nets in runs of at most `size` pairs, both members of a pair always in the same run, pairs sorted by
    name so one interface's lanes stay together. The pair router keeps nothing when it runs out of time (it does
    not read the stop file), so a big group in one run can lose every pair."""
    base: dict = {}
    for n in nets:
        b = next((n[:-len(x)] for a, c in PAIR_ENDS for x in (a, c) if n.endswith(x)), n)
        base.setdefault(b, []).append(n)
    keys = sorted(base)
    return [[n for k in keys[i:i + size] for n in sorted(base[k])] for i in range(0, len(keys), size)]


def pairs_stage(tools: dict, kpy: str, base: Path, work: Path, nets: list, minutes: float, proj: Path,
                layout: dict | None = None, layers: tuple = (), width: float = 0.0, gap: float = 0.0) -> dict:
    """Differential pairs routed together by KiCadRoutingTools' pair router, strict like the others. Only the
    pairs it reports as coupled with both members complete are offered for the merge ("coupled"); a pair it
    routed partly, or as two single tracks, is left open (half a pair routed alone is worse than none)."""
    src, raw, d = stage_dir(proj, work, base, "pairs", kpy)
    summary = d / "summary.json"
    router = Path(tools["krt"]) / "py_router"
    cmd = [tools["krt_python"], router / "route_diff.py", src, "--output", raw,
           "--nets", *[krt_pattern(n) for n in nets], "--escalation", "off", "--strict-sizes",
           "--no-fix-drc-settings", "--fab-tier", "standard", "--json-out", summary, *no_via_in_pad(kpy, base)]
    r = board_rules(kpy, base)
    for flag, key in (("--board-edge-clearance", "edge_um"), ("--hole-to-hole-clearance", "hole_to_hole_um")):
        if r.get(key):
            cmd += [flag, f"{r[key] / 1000:.4f}"]
    if layout and layout.get("planes") and layout.get("copper"):
        cmd += ["--layers", *(layout.get("standard") or layout["copper"]),
                "--layer-costs", *["-1" if l in layout["planes"] else "1.0" for l in layout["copper"]]]
    if width and gap:
        # the project's rule sizes: the router's default reads the Default class (5 mm placeholders on jetson)
        cmd += ["--track-width", f"{width:g}", "--diff-pair-gap", f"{gap:g}"]
    if layers and layout and layout.get("copper"):
        std = layout.get("standard") or layout["copper"]
        cmd += ["--layer-costs", *["1.0" if l in layers else "-1" for l in std]]
    cmd += os.environ.get("BOARDWRIGHT_PAIRS_ARGS", "").split()           # extra settings, for experiments
    # the pair router does not read the stop file: at the limit it is killed and nothing is kept
    rc, out, killed, secs = run_until(cmd, minutes, str(router))
    res = {"engine": "krt-pairs", "seconds": round(secs, 1), "raw": None, "coupled": []}
    try:
        report = json.loads(summary.read_text("utf-8"))
    except (OSError, ValueError):
        report = {}
    res["coupled"] = accepted_pairs(report)
    if killed:
        res["error"] = f"timed out after {minutes:g} minutes"
    elif not raw.is_file():
        res["error"] = f"the pair router wrote no board (exit {rc}): " + " | ".join(
            l for l in out.splitlines() if l.strip())[-200:]
    elif not res["coupled"]:
        res["error"] = "no pair was routed coupled"
    else:
        res["raw"] = raw
    return res


# set by cmd_run: the sizes KiCad's rules give each routed net per layer (engine_rules.py), for the audit
SIZES: dict = {"file": ""}


def net_sizes(tools: dict, pcb: Path, nets: list, pairs: list, out: Path) -> str:
    """Resolve the nets' sizes per layer with KiCadRoutingTools' rules reader (class, then .kicad_dru); the json
    path, or "" when that fails (the audit then uses the net classes)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    req = out.with_suffix(".req.json")
    mate = {}
    for n in pairs:
        for a, b in PAIR_ENDS:
            if n.endswith(a) or n.endswith(b):
                mate[n] = n[:-len(a if n.endswith(a) else b)]
                break
    req.write_text(json.dumps({"nets": list(nets), "pairs": mate}), "utf-8")
    rc, _o, _t, _s = sh([tools["krt_python"], "-I", HERE / "engine_rules.py", Path(tools["krt"]) / "py_router",
                         pcb, req, out], timeout=900)
    return str(out) if rc == 0 and out.is_file() else ""


# set by cmd_run: may new vias sit in SMD pads (see no_via_in_pad)
VIA_IN_PAD = {"ok": False}


def no_via_in_pad(kpy: str, pcb: Path) -> list:
    """KiCadRoutingTools allows a via in a same-net pad by default (98 on kit-dev, mostly plane taps on capacitor
    pads); that needs filled, capped vias at the fab or solder wicks into them. Unless the design uses them
    (VIA_IN_PAD), keep vias the board's clearance off same-net SMD pads and their paste openings."""
    if VIA_IN_PAD["ok"]:
        return []
    r = board_rules(kpy, pcb)
    return ["--same-net-pad-clearance", f"{(r.get('clearance_um') or 150) / 1000:.4f}"]


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


def freerouting_stage(tools: dict, kpy: str, base: Path, work: Path, minutes: float, rules: dict | None = None,
                      seed: int = 1, planes: dict | None = None) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    dsn, ses, raw = work / "fr.dsn", work / "fr.ses", work / "fr_raw.kicad_pcb"
    res = {"engine": "freerouting", "seconds": 0.0, "raw": None}
    t0 = time.time()
    guarded = guard_text(kpy, base, work / "fr_guarded.kicad_pcb")
    rc, out, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", "dsn", guarded, dsn], timeout=300)
    if rc != 0 or not dsn.is_file():
        res["error"] = "KiCad could not export the Specctra DSN: " + out.strip()[-200:]
        return res
    # KiCad exports every copper layer as a signal layer; the plane layers become power layers, which Freerouting
    # does not route signal tracks on
    if planes:
        txt = dsn.read_text("utf-8", errors="replace")
        for lay in planes:
            txt = re.sub(r"(\(layer " + re.escape(lay) + r"\s*\(type )signal\)", r"\1power)", txt)
        dsn.write_text(txt, "utf-8")
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
           f"--router.autorouter.item_order_seed={seed}", "--router.max_threads=1"]
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


def _kicad_json(kpy: str, *args) -> dict | list | None:
    rc, out, _t, _s = sh([kpy, "-I", HERE / "engine_kicad.py", *args], timeout=600)
    for line in reversed(out.splitlines()):
        if line.strip()[:1] in "{[":
            try:
                return json.loads(line)
            except ValueError:
                pass
    return None


def board_planes(kpy: str, pcb: Path) -> dict:
    """{"planes": {layer: net}, "copper": [layers]} (empty when it cannot be read)."""
    return _kicad_json(kpy, "planes", pcb) or {"planes": {}, "copper": []}


def audit(kpy: str, pcb: Path, nets: list, planes: dict, pairs: list | None = None,
          base: Path | None = None) -> dict:
    """{net: problem}: tracks below the net class's width, vias below its via size or drill, tracks on another
    net's plane. KiCad's DRC checks none of these (only the board's minimums)."""
    fd, name = tempfile.mkstemp(prefix="bwaudit", suffix=".json")
    os.close(fd)
    req = Path(name)
    try:
        req.write_text(json.dumps({"nets": nets, "planes": planes, "pairs": pairs or [],
                                   "base": str(base) if base else "", "via_in_pad_ok": VIA_IN_PAD["ok"],
                                   "sizes_file": SIZES["file"]}),
                       "utf-8")
        return _kicad_json(kpy, "audit", pcb, req) or {}
    finally:
        try:
            req.unlink()
        except OSError:
            pass


def nets_near(kpy: str, merged: Path, raw: Path, spots: list, nets: list, radius_mm: float = 1.5) -> list:
    """The listed nets that have router copper (in raw) within radius_mm of any of the spots (mm)."""
    if not spots or not nets:
        return []
    fd, name = tempfile.mkstemp(prefix="bwnear", suffix=".json")
    os.close(fd)
    req = Path(name)
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


def moved_nets(kpy: str, base: Path, raw: Path, nets: list) -> list:
    """Nets outside `nets` whose copper the router changed (moved out of the way, or ripped up)."""
    fd, name = tempfile.mkstemp(prefix="bwmoved", suffix=".json")
    os.close(fd)
    req = Path(name)
    try:
        req.write_text(json.dumps(list(nets)), "utf-8")
        got = _kicad_json(kpy, "moved", base, raw, req)
        return got if isinstance(got, list) else []
    finally:
        try:
            req.unlink()
        except OSError:
            pass


def trim(kpy: str, raw: Path, out: Path, nets: list) -> dict:
    """engine_kicad trim: {"trimmed": {net: segments cut}, "untrimmable": [nets]} ({} when it fails)."""
    fd, name = tempfile.mkstemp(prefix="bwtrim", suffix=".json")
    os.close(fd)
    req = Path(name)
    try:
        req.write_text(json.dumps({"nets": list(nets), "sizes_file": SIZES["file"]}), "utf-8")
        got = _kicad_json(kpy, "trim", raw, out, req)
        return got if isinstance(got, dict) and out.is_file() else {}
    finally:
        try:
            req.unlink()
        except OSError:
            pass


def evaluate(proj, kpy, work, name, st, base_open, orig_drc, nets, base_pcb, planes: dict | None = None,
             frozen: set | None = None) -> dict:
    """Merge a stage's copper (listed nets only) into the base and check it with KiCad's DRC. A net whose
    new copper causes a new DRC error is dropped (it stays open for the next stage or for Claude) and the
    rest is checked again, so one bad net no longer throws away a whole stage. Fills st."""
    if st.get("raw") is None:
        st["accepted"] = False
        st["why"] = st.get("error", "no result")
        return st
    import bw_edit
    # nets the router moved out of the way are merged and checked with the routed ones: merging only the routed
    # nets put kit-dev's plane-repair vias on the old positions of the tracks it had moved
    # never the nets the engine must not route (pairs, fast and hazardous nets): Freerouting rerouted cm5's
    # coupled pairs as single tracks; a stage whose copper clashes with them loses its own nets instead
    st["moved"] = [n for n in moved_nets(kpy, base_pcb, st["raw"], nets) if n not in (frozen or set())]
    # a pair is kept whole or not at all: the other half routed alone is a single track where a pair belongs
    c = st.get("coupled") or []
    mate = {**{c[i]: c[i + 1] for i in range(0, len(c) - 1, 2)}, **{c[i + 1]: c[i] for i in range(0, len(c) - 1, 2)}}

    def without(keep, gone):
        for n in keep:
            if n not in gone and mate.get(n) in gone:
                dropped.setdefault(n, f"its partner {mate[n]} was dropped")
        return [n for n in keep if n not in gone and mate.get(n) not in gone]
    keep = list(nets) + st["moved"]
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
            # copper KiCad's DRC does not judge: below the net class's sizes, or on another net's plane
            sized = audit(kpy, merged, keep, planes or {}, st.get("coupled"), base_pcb)
            if sized:
                # an undersized single-segment tap is cut from the router's result (its pad stays open) and the
                # rest of the net is kept; anything else undersized, or on another net's plane, drops the net
                small = [n for n, w in sized.items() if "it would cut the plane" not in w]
                cut = trim(kpy, st["raw"], work / f"{name}_trim{attempt}.kicad_pcb", small) if small else {}
                if cut.get("trimmed"):
                    st["raw"] = work / f"{name}_trim{attempt}.kicad_pcb"
                    for n, c in cut["trimmed"].items():
                        st.setdefault("trimmed", {})[n] = st.get("trimmed", {}).get(n, 0) + c
                    sized = {n: w for n, w in sized.items() if n not in cut["trimmed"]}
                    if not sized:
                        continue
                dropped.update(sized)
                keep = without(keep, sized)
                if not keep:
                    break
                continue
            # copper merged for a net replaces all of its old copper: if a router dropped existing segments,
            # the net is now more open than before; keep its old copper instead
            op = open_counts(kpy, merged)
            worse = {n: f"left it more open ({base_open.get(n, 0)} -> {op['open'].get(n, 0)} connections)"
                     for n in keep if op["open"].get(n, 0) > base_open.get(n, 0)}
            if not worse:
                break
            dropped.update(worse)
            keep = without(keep, worse)
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
        keep = without(keep, bad)
        if not keep:
            break
    if not any(n in nets for n in keep):
        keep = []                               # only moved nets left: nothing gained, keep the board as it was
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
def free_memory_gb() -> float:
    """Free physical memory in GB (0.0 when it cannot be read)."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("x", ctypes.c_ulonglong)]
            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.avail / 2 ** 30
        for line in open("/proc/meminfo", encoding="ascii"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2 ** 20
    except Exception:
        pass
    return 0.0


FR_SEEDS = 3                                    # Freerouting seeds tried at most per round (best DRC-clean kept)
FR_SEED_GB = 2.0                                # free memory needed per extra Freerouting run
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
        chosen, left, fast = choose(proj, files, op0["open"], patterns, allow_fast)   # 3
        zone_nets = set(op0.get("zone_nets", []))
        if not dry:                                                   # 4
            other = history.lock_take(proj, who, "engine run")
            if other:
                raise Setup("someone else is editing this project: " + history.describe(other))
            holder = True
            history.Store(proj).snap("before engine run")
        board_limits = board_rules(kpy, base_pcb)
        layout = board_planes(kpy, base_pcb)          # the designer's planes: no router may cut them up
        planes = layout["planes"]
        # vias in pads: the project's choice (boardwright.json "engine": {"via_in_pad": true/false}), else what
        # the board already does (a designer who put vias in pads ordered filled vias; one who did not, did not)
        vip = (load_config(proj).get("engine") or {}).get("via_in_pad")
        VIA_IN_PAD["ok"] = bool(layout.get("via_in_pad")) if vip is None else bool(vip)

        def route_variant(steps: list, vwork: Path, venv: dict | None = None) -> dict:
            """One routing sequence on its own copies, in its own folder. Every stage is checked by KiCad's DRC
            against the project as it was (evaluate), so every variant's result is DRC-clean."""
            vwork.mkdir(parents=True, exist_ok=True)
            v = {"pcb": start["pcb"], "open": dict(start["open"]), "drc": start["drc"], "board": start["board"],
                 "stages": []}

            def run_stage(st, name, nets):
                evaluate(proj, kpy, vwork, name, st, v["open"], orig, nets, v["pcb"], planes, frozen)
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
                    run_stage(krt_stage(tools, kpy, v["pcb"], vwork, nets, t, step, proj, env=venv, layout=layout),
                              step, nets)
                elif step == "planes":
                    # Big pour nets (the GND of a big board) joined to their pour with short taps and vias by the
                    # plane repair, not routed as tracks (GND alone took 15 minutes as tracks, jetson).
                    pours = [n for n in chosen if n in big and n in cur_open]
                    if pours:
                        run_stage(planes_stage(tools, kpy, v["pcb"], vwork, pours, min(minutes, 10), proj, layout),
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
                        # Best of N: Freerouting with different item-order seeds side by side, each checked by
                        # KiCad's DRC like any stage; the one leaving the fewest open connections is kept (ties to
                        # the lowest seed). N follows free memory: each run is a Java process.
                        n = max(1, min(FR_SEEDS, 1 + int(max(0.0, free_memory_gb() - FR_SEED_GB) // FR_SEED_GB)))
                        if os.environ.get("BOARDWRIGHT_FR_SEEDS", "").isdigit():      # to measure it
                            n = max(1, int(os.environ["BOARDWRIGHT_FR_SEEDS"]))
                        from concurrent.futures import ThreadPoolExecutor as _TP

                        def one(seed, base=v["pcb"], opn=dict(v["open"]), todo=todo, tag=tag):
                            stg = f"{tag}-s{seed}" if seed > 1 else tag
                            st = freerouting_stage(tools, kpy, base, vwork / stg, minutes, board_limits, seed,
                                                   planes)
                            return evaluate(proj, kpy, vwork, stg, st, opn, orig, todo, base, planes, frozen)
                        with _TP(max_workers=n) as px:
                            tries = list(px.map(one, range(1, n + 1)))
                        ok = [t for t in tries if t.get("accepted") and t.get("board")]
                        best = min(ok, key=lambda t: sum(t["open"]["open"].values())) if ok else tries[0]
                        best["seeds_tried"] = n
                        v["stages"].append(best)
                        if best.get("accepted") and best.get("board"):
                            v["pcb"], v["drc"] = best["board"], best["drc"]
                            v["open"] = dict(best["open"]["open"])
                            v["board"] = best["board"]
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
        # Differential pairs first, once (with --allow-fast only: their members are fast nets), routed together by
        # the pair router and never handed to the single-track routers, which would route each half alone.
        start = {"pcb": base_pcb, "open": dict(op0["open"]), "drc": orig, "board": None}
        pre: list = []
        pair_nets = pair_members(fast, board_nets(files["pcb"]))
        frozen = set(left) | set(pair_nets)          # no stage after this may move their copper
        SIZES["file"] = net_sizes(tools, base_pcb, chosen, pair_nets, work / "sizes.json")
        frozen |= {n for n in board_nets(files["pcb"]) if n and n not in op0["open"]}   # finished before the run
        FROZEN["nets"] = []
        chosen_all = chosen
        if pair_nets:
            chosen = [n for n in chosen if n not in pair_nets]
            if "krt" in engines:
                # the big pour nets joined to their planes before the pairs are laid: after 150 pair nets the
                # plane repair did not finish in 60 minutes on jetson; first, it took 290 s (round 9)
                pours = [n for n in chosen if n in zone_nets and start["open"].get(n, 0) > BIG_POUR]
                if pours:
                    st = planes_stage(tools, kpy, start["pcb"], work / "planes-first", pours, min(minutes, 10), proj,
                                      layout)
                    evaluate(proj, kpy, work / "planes-first", "krt-planes-first", st, start["open"], orig, pours,
                             start["pcb"], planes)
                    pre.append(st)
                    if st.get("accepted") and st.get("board"):
                        start = {"pcb": st["board"], "open": dict(st["open"]["open"]), "drc": st["drc"],
                                 "board": st["board"]}
            if "krt" in engines:
                # one run per size group, each from the board the last one left; a group that runs out of time
                # loses only itself (the pair router does not read the stop file)
                runs = [(lays, w, g, part) for lays, w, g, nets in pair_groups(SIZES["file"], pair_nets, layout)
                        for part in pair_chunks(nets)]
                for gi, (lays, w, g, nets) in enumerate(runs):
                    tag = "krt-pairs" + (f"-{gi + 1}" if gi else "")
                    st = pairs_stage(tools, kpy, start["pcb"], work / tag, nets, minutes, proj, layout, lays, w, g)
                    if w and g:
                        st["engine"] = f"{tag} ({w:g}/{g:g} mm)"
                    evaluate(proj, kpy, work / tag, tag, st, start["open"], orig, st["coupled"], start["pcb"],
                             planes)
                    pre.append(st)
                    if st.get("accepted") and st.get("board"):
                        start = {"pcb": st["board"], "open": dict(st["open"]["open"]), "drc": st["drc"],
                                 "board": st["board"]}
        FROZEN["nets"] = sorted(frozen)                # locked in the routers' copies from here on
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(sequences) or 1) as ex:
            futs = {name: ex.submit(route_variant, steps, work / f"variant_{name}", venv)
                    for name, (steps, venv) in sequences.items()}
            variants = {name: f.result() for name, f in futs.items()}
        best_name = min(variants, key=lambda n: (sum(variants[n]["open"].values()), list(variants).index(n))) \
            if variants else None
        best = variants.get(best_name) or dict(start, stages=[])
        chosen = chosen_all
        cur_open, cur_drc, result_board = best["open"], best["drc"], best["board"]
        for s in pre:
            s.pop("raw", None)
        stages = pre + [dict(s, engine=f"{s['engine']}" if len(variants) == 1 else f"{best_name}: {s['engine']}")
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
                             "failed", "drc_lines", "dropped", "seeds_tried", "moved", "trimmed")} for s in stages]}
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
        if planes:
            out.append("planes kept free of tracks: " + ", ".join(f"{l} ({n})" for l, n in planes.items()))
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
