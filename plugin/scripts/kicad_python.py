"""Run a board script with KiCad's own Python, whichever Python started it (standard library only).

Scripts that read the board need `pcbnew`, which only KiCad's bundled Python has. Each such script
calls ensure(__file__) first: under KiCad's Python it returns at once; under any other Python it finds
KiCad (the way run_gates.py finds kicad-cli: KICAD_CLI, PATH, the usual install folders), runs the
same script and arguments with KiCad's Python, and exits with its exit code. So
`python scripts/bw_edit.py . '...'` works without knowing where KiCad is installed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def find() -> str | None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from run_gates import find_kicad_cli
    cli = find_kicad_cli()
    if not cli:
        return None
    for name in ("python.exe", "python3", "python"):
        p = Path(cli).resolve().parent / name
        if p.exists():
            return str(p)
    return None


def ensure(script: str) -> None:
    try:
        import pcbnew  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("BOARDWRIGHT_KICAD_REEXEC"):
        print("ERROR: KiCad's Python was started but cannot import pcbnew. Check the KiCad install.")
        sys.exit(2)
    kpy = find()
    if not kpy:
        print("ERROR: this script needs KiCad's Python (it reads the board), and KiCad 9 or 10 was not found. "
              "Install KiCad, or set KICAD_CLI to the full path of kicad-cli.")
        sys.exit(2)
    env = dict(os.environ, BOARDWRIGHT_KICAD_REEXEC="1")
    sys.exit(subprocess.run([kpy, "-I", str(Path(script).resolve()), *sys.argv[1:]], env=env).returncode)
