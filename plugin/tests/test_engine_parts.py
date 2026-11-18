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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL PASSED" if not BAD else f"{len(BAD)} FAILED")
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
