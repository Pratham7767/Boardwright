#!/usr/bin/env python3
"""Smoke test for the boardwright scripts: run every read-only script on a project and check that
each one finishes without a crash or a setup error and writes parseable output.

Usage:  python selftest.py <project_dir>

It runs the scripts from its own folder (the plugin's), not the project's copies, on a temporary COPY
of the project, so the project itself is never written. It does not judge the design: a gate that
fails (exit 1) is a valid result here. Exit 0 = every script ran, 1 = a script crashed or reported a
setup problem, 2 = this test could not start.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_gates import find_kicad_cli  # noqa: E402

SKIP_DIRS = {".git", ".history", "fab", "__pycache__"}


def kicad_python(cli):
    for name in ("python.exe", "python3", "python"):
        p = Path(cli).resolve().parent / name
        if p.exists():
            return str(p)
    return None


def main():
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        print(__doc__)
        return 2
    src = Path(sys.argv[1]).resolve()
    cli = find_kicad_cli()
    if not cli:
        print("kicad-cli not found; set KICAD_CLI")
        return 2
    kpy = kicad_python(cli)
    cfg = {}
    if (src / "boardwright.json").is_file():
        cfg = json.loads((src / "boardwright.json").read_text(encoding="utf-8"))
    rows, bad = [], 0
    with tempfile.TemporaryDirectory(prefix="bw-selftest-") as tmp:
        proj = Path(tmp) / src.name
        shutil.copytree(src, proj, ignore=lambda d, names: [n for n in names if n in SKIP_DIRS
                                                            or n.endswith((".lck", "-backups"))])
        (proj / "reports").mkdir(exist_ok=True)
        py = sys.executable
        jobs = [
            ("plan.py (graph valid)", [py, HERE / "plan.py", proj, "--all"], (0,), None),
            ("status.py", [py, HERE / "status.py", proj], (0,), None),
            ("run_gates.py --sch-only", [py, HERE / "run_gates.py", proj, "--sch-only"], (0, 1), "reports/gates.json"),
            ("run_gates.py --no-export", [py, HERE / "run_gates.py", proj, "--no-export"], (0, 1), "reports/gates.json"),
            ("sch_check.py", [py, HERE / "sch_check.py", proj], (0, 1), "reports/sch-check.json"),
            ("safety_class.py", [py, HERE / "safety_class.py", proj], (0, 1), "reports/safety-class.json"),
            ("mains_check.py", [py, HERE / "mains_check.py", proj], (0, 1), "reports/mains-check.json"),
            ("creepage_rules.py", [py, HERE / "creepage_rules.py", proj], (0, 1), "reports/creepage.json"),
            ("emc_harmonics.py", [py, HERE / "emc_harmonics.py", proj], (0,), "reports/emc-harmonics.json"),
            ("impedance_check.py", [py, HERE / "impedance_check.py", proj], (0, 1), "reports/impedance.json"),
            ("pdn_check.py", [py, HERE / "pdn_check.py", proj], (0, 1), "reports/pdn.json"),
            ("parts_register.py", [py, HERE / "parts_register.py", proj], (0,), "reports/parts-register.json"),
        ]
        if kpy:
            jobs += [
                ("board_digest.py summary", [kpy, "-I", HERE / "board_digest.py", proj], (0,), None),
                ("block_check.py", [kpy, "-I", HERE / "block_check.py", proj], (0, 1), "reports/block-check.json"),
                ("hs_rules.py", [kpy, "-I", HERE / "hs_rules.py", proj], (0, 1), "reports/hs-check.json"),
                ("emc_rules.py", [kpy, "-I", HERE / "emc_rules.py", proj], (0, 1), "reports/emc-rules.json"),
            ]
            if "barrier" in cfg:
                jobs.append(("barrier_check.py", [kpy, "-I", HERE / "barrier_check.py", proj], (0, 1), "reports/barrier.json"))
            if "emc" in cfg:
                jobs.append(("emc_geometry.py", [kpy, "-I", HERE / "emc_geometry.py", proj], (0, 1), "reports/emc-geometry.json"))
        else:
            rows.append(("KiCad python", "skipped", "not found next to kicad-cli; geometry scripts not run"))
        for name, cmd, ok_codes, out in jobs:
            t = time.time()
            try:
                p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
                code, text = p.returncode, (p.stdout or "") + (p.stderr or "")
            except (OSError, subprocess.TimeoutExpired) as exc:
                code, text = -1, str(exc)
            status, detail = "ok", f"exit {code}, {time.time() - t:.1f} s"
            if code not in ok_codes or "Traceback (most recent call last)" in text:
                status = "FAIL"
                detail += " | " + (text.strip().splitlines()[-1][:160] if text.strip() else "no output")
            elif out:
                try:
                    json.loads((proj / out).read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    status, detail = "FAIL", f"{out} not readable: {exc}"
            if code == 1 and status == "ok":
                detail += " (a check failed on this design; that is a design result, not a script fault)"
            bad += status == "FAIL"
            rows.append((name, status, detail))
    w = max(len(r[0]) for r in rows)
    for name, status, detail in rows:
        print(f"{name.ljust(w)} | {status:7} | {detail}")
    print(f"\n{len(rows)} scripts, {bad} failed. The export path (run_gates.py without flags) is not exercised here.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
