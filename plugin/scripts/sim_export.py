#!/usr/bin/env python3
"""Export the board for external analysis tools: IPC-2581, ODB++ and STEP into <project>/sim/.

Usage:  python scripts/sim_export.py <project_dir>

Commercial and open field solvers and rule checkers read these formats: Siemens HyperLynx DRC reads
ODB++ and IPC-2581; CST Studio Suite, Ansys SIwave/HFSS and Cadence Sigrity import ODB++ or IPC-2581;
mechanical tools take STEP (research notes: vendor documentation, 2025-2026). Running those tools is a
human step: this script only writes the files, and a README that says what each file is for.
Nothing in sim/ is a release file. Exit 0 all written, 1 an export failed, 2 setup problem.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, project_files  # noqa: E402

EXPORTS = [("ipc2581", "{stem}.ipc2581.xml", "HyperLynx DRC, CST, SIwave, Sigrity (IPC-2581 rev C)"),
           ("odb", "{stem}.odb.zip", "HyperLynx DRC, CST, SIwave (ODB++)"),
           ("step", "{stem}.step", "mechanical checks: enclosure fit, 3-D clearance over part bodies")]


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        f = project_files(project)
        from run_gates import find_kicad_cli
        cli = find_kicad_cli()
        if not cli:
            raise SetupError("kicad-cli not found")
        if not f["pcb"].is_file():
            raise SetupError(f"{f['pcb'].name} not found")
    except SetupError as exc:
        print(f"sim_export: setup problem: {exc}")
        return 2
    out = project / "sim"
    out.mkdir(exist_ok=True)
    lines, failed = [], 0
    for fmt, name, use in EXPORTS:
        target = out / name.format(stem=f["stem"])
        r = subprocess.run([cli, "pcb", "export", fmt, "-o", str(target), str(f["pcb"])], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        text = (r.stdout or "") + (r.stderr or "")
        # kicad-cli can return non-zero for warnings (e.g. VRML part models left out of a STEP file)
        ok = target.exists() and target.stat().st_size > 0
        failed += not ok
        warn = sorted({ln.strip() for ln in text.splitlines() if "cannot" in ln.lower() or "warning" in ln.lower()})
        lines.append(f"- `{target.name}`: {use}" + ("" if ok else f"  (FAILED: {text.strip()[:200]})")
                     + (f"  Note: {'; '.join(warn)[:200]}" if ok and warn else ""))
        print(("ok    " if ok else "FAIL  ") + target.name)
    (out / "README.md").write_text("\n".join([
        "# Files for external analysis (not release files)", "",
        "Written by `scripts/sim_export.py` from the board as it is now. Re-export after any board change.", ""]
        + lines + ["", "Import into the tool you are licensed for, run its checks, and record the tool, version, "
                   "settings and results in reports/06-emc.md or 05-layout.md. Boardwright does not run these tools."]) + "\n",
        "utf-8")
    print(f"written to {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
