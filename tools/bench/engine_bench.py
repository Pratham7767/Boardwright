#!/usr/bin/env python3
"""Measure the routing engine (plugin/scripts/engine.py) on KiCad's demo boards (standard library only).

    python tools/bench/engine_bench.py [--boards a,b,c] [--work DIR] [--minutes 15] [--cap-min 30]
                                       [--only default|fast] [--out results.json] [--md docs/benchmark-engine.md]

For each demo: copy the folder to a work dir (never touches the KiCad install), strip every track, arc and via
with KiCad's Python (zones refilled), count the connections KiCad DRC reports as unconnected, then run
`engine.py <copy> run --minutes N` on one fresh copy (default settings) and `... --allow-fast` on another.
A run that exceeds --cap-min wall minutes is killed and the board is marked skipped.
Writes tools/bench/results/engine-<date>.json and the table docs/benchmark-engine.md (--md '' to skip).
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "plugin" / "scripts"
ENGINE = SCRIPTS / "engine.py"
DEMOS = Path(os.environ.get("KICAD_DEMOS", r"E:\KiCad\share\kicad\demos"))
DEFAULT_BOARDS = ["pic_programmer", "video", "stickhub", "kit-dev-coldfire-xilinx_5213", "cm5_minima",
                  "royalblue54L_feather", "jetson-agx-thor-baseboard"]
sys.path.insert(0, str(SCRIPTS))

STRIP = r'''
import glob, json, os, sys
sys.path.insert(0, r"E:\PCB\boardwright\plugin\scripts")
import kicad_python
kicad_python.quiet()          # KiCad's messages (e.g. a missing font) go to stderr, not a blocking dialog
import pcbnew
folder = sys.argv[1]
pcb = sys.argv[2]
b = pcbnew.LoadBoard(pcb)
tracks = list(b.GetTracks())
n = len(tracks)
for t in tracks:
    b.Remove(t)
zones = b.Zones()
pcbnew.ZONE_FILLER(b).Fill(zones)
b.Save(pcb)
b = pcbnew.LoadBoard(pcb)
nets = [x for x in b.GetNetInfo().NetsByName().keys() if str(x)]
print(json.dumps({"removed": n, "copper_layers": b.GetCopperLayerCount(), "footprints": len(list(b.GetFootprints())),
                  "nets": len(nets), "zones": len(list(b.Zones()))}))
'''


COUNT = r'''
import sys
sys.path.insert(0, r"E:\PCB\boardwright\plugin\scripts")
import kicad_python
kicad_python.quiet()
import pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
print("COUNT", b.GetConnectivity().GetUnconnectedCount(True))
'''


def kicad_python():
    import kicad_python
    return kicad_python.find()


def pick_pro(folder: Path, board_hint: str = "") -> Path:
    """The .kicad_pcb to use: the one named like the folder, else the only one, else the first alphabetically."""
    pcbs = sorted(folder.glob("*.kicad_pcb"))
    pcbs = [p for p in pcbs if "unrouted" not in p.stem] or pcbs
    return pcbs[0]


def make_project(src: Path, dest: Path) -> Path:
    """Copy the demo, keep exactly one .kicad_pro/.kicad_pcb pair (the engine wants a single .kicad_pro)."""
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("*.lck", "*-backups", "fp-info-cache", "*.pdf"))
    pcb = pick_pro(dest)
    for p in dest.glob("*.kicad_pcb"):
        if p != pcb:
            p.unlink()
    pros = sorted(dest.glob("*.kicad_pro"))
    keep = next((p for p in pros if p.stem == pcb.stem), pros[0])
    for p in pros:
        if p != keep:
            p.unlink()
    if keep.stem != pcb.stem:                       # the engine looks for <pro stem>.kicad_pcb
        pcb = pcb.rename(dest / (keep.stem + ".kicad_pcb"))
    return pcb


def strip(kpy, folder: Path, pcb: Path, scratch: Path) -> dict:
    s = scratch / "strip_tracks.py"
    s.write_text(STRIP, "utf-8")
    r = subprocess.run([kpy, "-I", str(s), str(folder), str(pcb)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if r.returncode != 0 or not lines:
        raise RuntimeError("strip failed: " + (r.stdout + r.stderr)[-400:])
    return json.loads(lines[-1])


def count_open(kpy, pcb: Path, scratch: Path):
    """Unrouted connections by KiCad's connectivity (not capped, unlike the DRC's unconnected list)."""
    f = scratch / f"count_{os.getpid()}.py"
    f.write_text(COUNT, "utf-8")
    r = subprocess.run([kpy, "-I", str(f), str(pcb)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"COUNT (\d+)", r.stdout)
    return int(m.group(1)) if m else None


def copper_items(pcb: Path) -> int:
    t = pcb.read_text("utf-8", errors="replace")
    return len(re.findall(r"^\s*\((?:segment|via|arc)\s", t, re.M))


def drc(pcb: Path):
    import engine
    return engine.drc_full(pcb)


def kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def run_engine(folder: Path, extra: list, minutes: float, cap_min: float) -> dict:
    t0 = time.time()
    p = subprocess.Popen([sys.executable, str(ENGINE), str(folder), "run", "--minutes", str(minutes), *extra],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                         errors="replace")
    try:
        out, _ = p.communicate(timeout=cap_min * 60)
        return {"exit": p.returncode, "wall_s": round(time.time() - t0, 1), "output": out, "skipped": False}
    except subprocess.TimeoutExpired:
        kill_tree(p.pid)
        try:
            out, _ = p.communicate(timeout=30)
        except Exception:
            out = ""
        return {"exit": None, "wall_s": round(time.time() - t0, 1), "output": out or "", "skipped": True}


def by_net(unc: list) -> dict:
    d = {}
    for net, _items in unc:
        d[net] = d.get(net, 0) + 1
    return d


def one_run(kind: str, src: Path, work: Path, kpy, minutes, cap_min, info_cache: dict) -> dict:
    folder = work / kind / src.name
    if folder.exists():
        def _rw(fn, path, _exc):
            os.chmod(path, 0o700)
            fn(path)
        shutil.rmtree(folder, onerror=_rw)          # demo files may be read-only
    folder.parent.mkdir(parents=True, exist_ok=True)
    pcb = make_project(src, folder)
    info = strip(kpy, folder, pcb, work)
    d0 = drc(pcb)
    if d0 is None:
        return {"error": "DRC failed on the stripped board"}
    drc_before = len(d0["unconnected_list"])
    before = count_open(kpy, pcb, work)
    info_cache.update(info)
    res = {"connections_before": before, "drc_unconnected_before": drc_before,
           "drc_list_capped": drc_before < before, "errors_before": len(d0["errors"]),
           "copper_items_before": copper_items(pcb)}
    r = run_engine(folder, ["--allow-fast"] if kind == "allow_fast" else [], minutes, cap_min)
    res.update(exit=r["exit"], wall_s=r["wall_s"], skipped=r["skipped"])
    if r["skipped"]:
        res["note"] = f"killed after {cap_min:g} min wall"
        res["output_tail"] = r["output"][-800:]
        return res
    res["output_tail"] = r["output"][-1500:]
    rep = folder / "reports" / "engine.json"
    data = {}
    if rep.is_file():
        data = json.loads(rep.read_text("utf-8-sig"))
    d1 = drc(pcb)
    after = count_open(kpy, pcb, work)
    res["drc_unconnected_after"] = len(d1["unconnected_list"]) if d1 else None
    res["copper_items_after"] = copper_items(pcb)
    res["connections_after"] = after
    res["completion"] = round(1 - after / before, 4) if (after is not None and before) else None
    if d1:
        res["new_drc_errors"] = len([k for k in d1["errors"] if k not in d0["errors"]])
        res["errors_after"] = len(d1["errors"])
    chosen = data.get("chosen", [])
    b0 = by_net(d0["unconnected_list"])
    b1 = by_net(d1["unconnected_list"]) if d1 else {}
    allowed = sum(b0.get(n, 0) for n in chosen)
    left_allowed = sum(b1.get(n, 0) for n in chosen)
    res["nets_open_before"] = len([n for n in b0 if n])
    res["chosen_nets"] = len(chosen)
    res["connections_allowed"] = allowed
    res["connections_allowed_after"] = left_allowed
    # per-net numbers come from the DRC list, which stops at 499 items: only trust them when it is not capped
    res["completion_allowed"] = round(1 - left_allowed / allowed, 4) if allowed and not res["drc_list_capped"] else None
    reasons = {}
    for n, why in data.get("left_out", {}).items():
        k = re.split(r"[:(]", why)[0].strip()
        reasons.setdefault(k, []).append(n)
    res["left_out_by_reason"] = {k: len(v) for k, v in reasons.items()}
    res["left_out_connections"] = sum(b0.get(n, 0) for v in reasons.values() for n in v)
    stages = {s["engine"]: s for s in data.get("stages", [])}
    res["stages"] = {}
    for name, s in stages.items():
        m = re.search(r"unconnected (\d+) -> (\d+)", " ".join(s.get("drc_lines", [])[:1]))
        res["stages"][name] = {"seconds": s.get("seconds"), "accepted": s.get("accepted"),
                               "unconnected_after_stage": int(m.group(2)) if m else None,
                               "new_errors_in_stage": (re.search(r"(\d+) new error", " ".join(s.get("drc_lines", [])[:1])) or [None, None])[1],
                               "nets_routed": len(s.get("routed_nets", [])), "why": (s.get("why") or s.get("error") or "")[:240]}
    res["krt_nets"] = res["stages"].get("krt", {}).get("nets_routed", 0) if res["stages"].get("krt", {}).get("accepted") else 0
    res["freerouting_nets"] = res["stages"].get("freerouting", {}).get("nets_routed", 0) if \
        res["stages"].get("freerouting", {}).get("accepted") else 0
    res["engine_seconds"] = data.get("seconds")
    res["engine_result"] = data.get("result")
    return res


def pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def secs(s):
    if s is None:
        return "-"
    return f"{s / 60:.1f} min" if s >= 120 else f"{s:.0f} s"


def write_md(results: dict, path: Path):
    L = []
    L.append("# Routing engine benchmark on KiCad's demo boards\n")
    L.append(f"Measured {results['date']} with KiCad {results.get('kicad','')} and the engine in "
             "`plugin/scripts/engine.py`. Reproduce with `python tools/bench/engine_bench.py`.\n")
    L.append("## Method\n")
    L.append("Each demo folder is copied to a work directory (the KiCad install is never touched). Every track, arc and "
             "via is removed with KiCad's Python and the zones are refilled; footprints, zones and the outline stay. "
             "KiCad's connectivity then counts the unrouted connections (this count is not capped; the DRC `unconnected_items` list stops at 499, see Observations). The engine runs twice, each time on "
             "a fresh stripped copy: once with its defaults (fast nets such as USB and hazardous nets are left out) and "
             "once with `--allow-fast`. The engine runs KiCadRoutingTools in strict mode, then Freerouting on what is "
             "left, and accepts a stage only if KiCad DRC shows no new error. `--minutes 15` is the engine's time limit "
             "per stage. After the run the board is checked again with KiCad DRC.\n")
    L.append("Completion is `1 - connections after / connections before`, over all connections. \"Allowed\" completion "
             "counts only the connections on nets the engine was permitted to route (it skips hazardous nets, and fast "
             "nets unless `--allow-fast`). \"New errors\" is the number of DRC errors not present on the stripped board.\n")
    L.append("## Results\n")
    L.append("| Board | Layers | Footprints | Nets | Connections | Default: done / allowed | Default: new DRC errors | Default: time | Fast allowed: done / allowed | Fast allowed: new DRC errors | Fast allowed: time |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for b in results["boards"]:
        if b.get("error"):
            L.append(f"| {b['name']} | | | | | error: {b['error'][:80]} | | | | | |")
            continue
        d, f = b.get("default", {}), b.get("allow_fast", {})

        def cell(r):
            if not r:
                return "not run", "-", "-"
            if r.get("skipped"):
                return "skipped (over time cap)", "-", secs(r["wall_s"]) + "+"
            if r.get("error"):
                return "error", "-", "-"
            return (f"{pct(r.get('completion'))} / {pct(r.get('completion_allowed'))}",
                    str(r.get("new_drc_errors", "-")),
                    secs(r.get("wall_s")) + (" (over 30 min)" if r.get("wall_s", 0) > 1800 else ""))
        dc, de, dt = cell(d)
        fc, fe, ft = cell(f)
        L.append(f"| {b['name']} | {b.get('copper_layers','')} | {b.get('footprints','')} | {b.get('nets','')} | "
                 f"{d.get('connections_before', f.get('connections_before',''))} | {dc} | {de} | {dt} | {fc} | {fe} | {ft} |")
    L.append("")
    L.append("## Who routed what, and what was left out\n")
    L.append("| Board | Run | Nets routed by KiCadRoutingTools | Nets routed by Freerouting | Nets left out (reason: count) | Connections left out | Stage seconds (krt / freerouting) |")
    L.append("|---|---|---|---|---|---|---|")
    for b in results["boards"]:
        for k, label in (("default", "default"), ("allow_fast", "allow-fast")):
            r = b.get(k)
            if not r or r.get("skipped") or r.get("error"):
                continue
            st = r.get("stages", {})
            lo = "; ".join(f"{a}: {n}" for a, n in r.get("left_out_by_reason", {}).items()) or "none"
            def who(name):
                x = st.get(name)
                if not x:
                    return "not run"
                if x.get("accepted"):
                    return str(x.get("nets_routed"))
                if x.get("unconnected_after_stage") is None:
                    return "0 (" + (x.get("why") or "no result")[:60] + ")"
                return f"0 (stage rejected; would have left {x.get('unconnected_after_stage')} open, {x.get('new_errors_in_stage')} new errors)"
            L.append(f"| {b['name']} | {label} | {who('krt')} | {who('freerouting')} | {lo} | "
                     f"{r.get('left_out_connections')} | {st.get('krt',{}).get('seconds','-')} / "
                     f"{st.get('freerouting',{}).get('seconds','-')} |")
    L.append("")
    L.append("## Observations\n")
    L.append("OBSERVATIONS_PLACEHOLDER")
    path.write_text("\n".join(L) + "\n", "utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boards", default=",".join(DEFAULT_BOARDS))
    ap.add_argument("--work", default=str(Path(tempfile.gettempdir()) / "bw-engine-bench"))
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--cap-min", type=float, default=30)
    ap.add_argument("--only", choices=["default", "fast"], default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--md", default=str(ROOT / "docs" / "benchmark-engine.md"))
    a = ap.parse_args()
    kpy = kicad_python()
    if not kpy:
        sys.exit("KiCad's Python was not found")
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    out = Path(a.out) if a.out else ROOT / "tools" / "bench" / "results" / f"engine-{date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    results = {"date": date, "kicad_python": kpy, "minutes_per_stage": a.minutes, "cap_min": a.cap_min, "boards": []}
    if out.is_file():                                # resume: keep boards from an earlier partial run
        try:
            old = json.loads(out.read_text("utf-8"))
            results["boards"] = [b for b in old.get("boards", []) if b["name"] not in a.boards.split(",")]
        except ValueError:
            pass
    for name in [n.strip() for n in a.boards.split(",") if n.strip()]:
        src = DEMOS / name
        entry = {"name": name}
        if not src.is_dir():
            entry["error"] = "demo folder not found"
        else:
            info = {}
            for kind in ([] if a.only == "fast" else ["default"]) + ([] if a.only == "default" else ["allow_fast"]):
                print(f"[{name}] {kind} ...", flush=True)
                try:
                    entry[kind] = one_run(kind, src, work, kpy, a.minutes, a.cap_min, info)
                except Exception as exc:                # keep going with the other boards
                    entry[kind] = {"error": str(exc)[:400]}
                r = entry[kind]
                print(f"[{name}] {kind}: {r.get('connections_before')} -> {r.get('connections_after')} "
                      f"exit {r.get('exit')} {r.get('wall_s')} s new errors {r.get('new_drc_errors')}", flush=True)
                entry.update(info)
        results["boards"].append(entry)
        out.write_text(json.dumps(results, indent=1, default=str), "utf-8")
    if a.md:
        write_md(results, Path(a.md))
    print("wrote", out)


if __name__ == "__main__":
    main()
