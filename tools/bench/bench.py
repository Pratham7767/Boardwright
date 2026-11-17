#!/usr/bin/env python3
"""Measure what Claude Code spends on Boardwright editing tasks.

    python tools/bench/bench.py LABEL [--runs 2] [--tasks a,b] [--plugin-dir plugin] [--update-scripts] [--model sonnet]

Each run: copy examples/usb-sensor-test to a fresh folder, apply the task's prep, run one headless
Claude Code turn (`claude -p`, real model, real cost), then check the result with KiCad's DRC and
check.py. Results go to tools/bench/results/LABEL.json and a table is printed.

--plugin-dir DIR is the plugin under test (default: this repo's plugin; the installed one is switched off); --update-scripts copies its scripts into the
project copy first (as `init_project.py --update-scripts` does). Nothing outside the run folders
is changed. Needs KiCad 9/10 and a signed-in Claude Code.
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "plugin/scripts"))
from run_gates import find_kicad_cli  # noqa: E402

TOOLS = ["Bash", "Read", "Edit", "Write", "Glob", "Grep"]


def arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1]
    return default


def drc(cli: str, folder: Path) -> Path:
    pcb = next(folder.glob("*.kicad_pcb"))
    out = folder / "_bench_drc.json"
    subprocess.run([cli, "pcb", "drc", "--format", "json", "--severity-all", "--schematic-parity",
                    "-o", str(out), str(pcb)], capture_output=True)
    return out


def copy_example(dst: Path) -> None:
    shutil.copytree(ROOT / "examples/usb-sensor-test", dst,
                    ignore=shutil.ignore_patterns("fab", "*-backups", "_bench_*"))


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print(__doc__)
        return 2
    label = sys.argv[1]
    runs = int(arg("--runs", "2"))
    only = set(filter(None, (arg("--tasks", "") or "").split(",")))
    plugin_dir = arg("--plugin-dir")
    # The plugin under test: a frozen copy for a "before" run, this repo's plugin otherwise.
    pdir = (ROOT / plugin_dir).resolve() if plugin_dir else ROOT / "plugin"
    cli = find_kicad_cli()
    if not cli:
        print("kicad-cli not found")
        return 2
    kpy = next((str(Path(cli).parent / n) for n in ("python.exe", "python3", "python")
                if (Path(cli).parent / n).exists()), None)
    claude = shutil.which("claude")
    if not (kpy and claude):
        print("needs KiCad's Python and Claude Code")
        return 2
    tasks = [t for t in json.loads((HERE / "tasks.json").read_text("utf-8"))["tasks"] if not only or t["id"] in only]
    work = Path(os.environ.get("BENCH_DIR") or tempfile.mkdtemp(prefix="bw-bench-"))
    work.mkdir(parents=True, exist_ok=True)
    base_dir = work / "_base"
    if not base_dir.exists():
        copy_example(base_dir)
    base = json.loads(drc(cli, base_dir).read_text("utf-8"))
    base_errors = sum(1 for v in base.get("violations", []) if v.get("severity") == "error")
    print(f"work folder {work}; untouched board: {base_errors} DRC errors")
    results = []
    for task in tasks:
        for n in range(runs):
            folder = work / f"{label}-{task['id']}-{n + 1}"
            if folder.exists():
                shutil.rmtree(folder)
            copy_example(folder)
            if "--update-scripts" in sys.argv:
                shutil.rmtree(folder / "scripts", ignore_errors=True)
                subprocess.run([sys.executable, str(pdir / "scripts/init_project.py"), str(folder),
                                "--update-scripts"], capture_output=True)
            tf = folder / "_bench_task.json"
            tf.write_text(json.dumps(task), "utf-8")
            subprocess.run([kpy, "-I", str(HERE / "prep.py"), str(folder), str(tf)], check=True, capture_output=True)
            cmd = [claude, "-p", task["prompt"], "--output-format", "json", "--max-budget-usd", "4",
                   *(["--model", arg("--model")] if arg("--model") else []),
                   "--permission-mode", "acceptEdits", "--allowedTools", *TOOLS]
            # Only the plugin under test: the installed copy is switched off for the run.
            cmd += ["--plugin-dir", str(pdir), "--settings", json.dumps({"enabledPlugins": {"boardwright@boardwright": False}})]
            t0 = time.time()
            p = subprocess.run(cmd, cwd=str(folder), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=1800)
            wall = time.time() - t0
            try:
                out = json.loads(p.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                out = {"is_error": True, "result": (p.stdout + p.stderr)[-400:]}
            u = out.get("usage", {})
            ctx = sum(u.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            chk = subprocess.run([kpy, "-I", str(HERE / "check.py"), str(folder), str(tf), str(drc(cli, folder)),
                                  str(base_errors)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            try:
                verdict = json.loads(chk.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                verdict = {"pass": False, "why": [chk.stderr[-300:]]}
            row = {"task": task["id"], "run": n + 1, "pass": verdict["pass"], "why": verdict.get("why", []),
                   "context_tokens": ctx, "output_tokens": u.get("output_tokens", 0),
                   "turns": out.get("num_turns", 0), "wall_s": round(wall), "cost_usd": round(out.get("total_cost_usd", 0), 3),
                   "error": bool(out.get("is_error"))}
            results.append(row)
            print(json.dumps(row))
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{label}.json").write_text(json.dumps(results, indent=1), "utf-8")
    print(f"\n| task | passes | context tokens | turns | wall s | cost $ |  ({label}, medians)\n|---|---|---|---|---|---|")
    for tid in dict.fromkeys(r["task"] for r in results):
        rs = [r for r in results if r["task"] == tid]
        med = lambda k: statistics.median(r[k] for r in rs)  # noqa: E731
        print(f"| {tid} | {sum(r['pass'] for r in rs)}/{len(rs)} | {med('context_tokens'):,.0f} | {med('turns'):g} | "
              f"{med('wall_s'):g} | {med('cost_usd'):.2f} |")
    print(f"total cost ${sum(r['cost_usd'] for r in results):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
