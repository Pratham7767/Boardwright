#!/usr/bin/env python3
"""Offline test of fab_rules.copper_layers / check on a fake 4-layer board (standard library only).

    python plugin/tests/test_fab_rules.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fab_rules as fr  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


PCB = '''(kicad_pcb (version 20240108) (generator "test")
  (layers
    (0 "F.Cu" signal)
    (1 "In1.Cu" power)
    (2 "In2.Cu" mixed)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user)
    (36 "B.SilkS" user "B.Silkscreen")
  )
  (segment (start 0 0) (end 1 1) (width 0.2) (layer "F.Cu") (net 1))
)
'''


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bwfab_"))
    (tmp / "t.kicad_pcb").write_text(PCB, "utf-8")
    (tmp / "t.kicad_pro").write_text(json.dumps({"board": {"design_settings": {"rules": {"min_track_width": 0.2}}}}), "utf-8")
    n = fr.copper_layers({}, tmp / "t.kicad_pcb")
    check("power and mixed inner layers are counted: 4 copper layers", n == 4, str(n))
    (tmp / "u.kicad_pcb").write_text('(kicad_pcb (layers (0 "F.Cu" signal) (31 "B.Cu" signal)))', "utf-8")
    check("2-layer board counts 2", fr.copper_layers({}, tmp / "u.kicad_pcb") == 2)
    check("jumper type is counted too",
          fr.copper_layers({}, _w(tmp, '(layers (0 "F.Cu" signal) (1 "In1.Cu" jumper) (2 "In2.Cu" jumper) (31 "B.Cu" signal))')) == 4)
    rc = fr.cmd_check(tmp, ["--fab", "jlcpcb"])
    data = json.loads((tmp / "reports" / "fab-check.json").read_text("utf-8"))
    rows = {r[0]: r for r in data["rows"]}
    check("check uses the 4-6 layer rows of JLCPCB (track 0.09)", rows["track_width"][1] == 0.09, str(rows.get("track_width")))
    check("check ran (no conflicts: board setup 0.2 is above the minimum)", rc == 0, str(rc))
    print("PASS" if not FAILS else f"FAILED: {FAILS}")
    return 1 if FAILS else 0


def _w(tmp: Path, layers: str) -> Path:
    p = tmp / "j.kicad_pcb"
    p.write_text("(kicad_pcb " + layers + ")", "utf-8")
    return p


if __name__ == "__main__":
    sys.exit(main())
