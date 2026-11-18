#!/usr/bin/env python3
"""Tests for the plan.py `file_contains` gate evidence (standard library only).

    python plugin/tests/test_plan_evidence.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "plugin" / "scripts"))
import plan  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def state(text):
    return plan._gate_line_evidence("r.md", "PASS", text, 0.0)[0]


def old_state(text):
    """The previous rule: any line with PASS counts."""
    pat = re.compile(r"\bPASS(ED)?\b", re.I)
    bad = re.compile(r"NOT\s+PASS|\bFAIL", re.I)
    failed = False
    for ln in text.splitlines():
        if bad.search(ln):
            failed = True
            continue
        if pat.search(ln):
            return "ok"
    return "fail" if failed else "none"


HEADER = "| Item | Pass (20 % needed) |\n|---|---|\n| 3V3 | 30 % |\n\n"
check("header 'Pass' + gate FAILED -> not done", state(HEADER + "Gate: FAILED\n") == "fail", state(HEADER + "Gate: FAILED\n"))
check("header 'Pass' alone -> not done", state(HEADER) == "none")
check("Gate: PASS -> done", state("# R\n\nGate: PASS\n") == "ok")
check("**Gate status: PASSED** -> done", state("**Gate status: PASSED**, with stage 2 still open.\n") == "ok")
check("Gate status: NOT PASSED (open) -> not done", state("Gate status: NOT PASSED (open) on items 1\n") != "ok")
check("Result: PASS -> done", state("Result: PASS\n") == "ok")
check("Result: PASS then Result: FAIL -> not done", state("Result: PASS\nResult: FAIL\n") == "fail")
check("Gate: open -> not done", state("Gate: open\n") != "ok")
check("## Gate section line -> done", state("## Gate\nAll fine: **PASS**\n\n## Next\n") == "ok")
check("PASS outside a gate line -> not done", state("## Notes\nThe fit passes, PASS.\n") == "none")

# The example project's real reports.
ex = ROOT / "examples" / "usb-sensor-test"
import json  # noqa: E402
nodes = json.loads((ROOT / "plugin" / "scripts" / "pipeline.json").read_text(encoding="utf-8"))["nodes"]
seen = 0
for n in (nodes.values() if isinstance(nodes, dict) else nodes):
    ev = n.get("evidence") or {}
    if "file_contains" not in ev:
        continue
    rel, needle = ev["file_contains"]
    p = ex / rel
    if not p.is_file():
        continue
    text = p.read_text(encoding="utf-8", errors="replace")
    new = plan._gate_line_evidence(rel, needle, text, 0.0)[0]
    old = old_state(text)
    seen += 1
    print(f"     {rel}: before={old} after={new}")
    check(f"example {rel} same state as before", new == old, f"{old} -> {new}")
check("example reports were found", seen >= 4, str(seen))

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "all ok")
sys.exit(1 if FAILS else 0)
