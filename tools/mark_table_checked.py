#!/usr/bin/env python3
"""Maintainer tool: record that a spacing table was checked against the purchased standard.

    python tools/mark_table_checked.py                       list every table and its status
    python tools/mark_table_checked.py creepage_F5 --by "Name" --against "IEC 60664-1:2020 Table F.5" \
        [--changed "row 250 V: 2.5 -> 2.5 (no change)"]

Edits plugin/scripts/spacing_tables.json: the table's status becomes
"checked against <standard> by <name> on <date>", and the check is appended to its "checked" log.
Read every row of the table against the standard before marking it; fix any row that differs in the
same commit and say so with --changed. Commit the result: every user's reports then show the new status.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

TABLES = Path(__file__).resolve().parent.parent / "plugin" / "scripts" / "spacing_tables.json"


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("table", nargs="?")
    ap.add_argument("--by")
    ap.add_argument("--against")
    ap.add_argument("--changed", default="no rows changed")
    a = ap.parse_args(argv)
    d = json.loads(TABLES.read_text("utf-8"))
    names = [k for k, v in d.items() if isinstance(v, dict) and "status" in v]
    if not a.table:
        for k in names:
            print(f"{k:32} {d[k]['status']}")
        return 0
    if a.table not in names:
        print(f"unknown table '{a.table}'; tables: {', '.join(names)}")
        return 2
    if not a.by or not a.against:
        print("--by and --against are required (who checked it, against which standard, edition and table)")
        return 2
    day = time.strftime("%Y-%m-%d")
    t = d[a.table]
    t.setdefault("checked", []).append({"by": a.by, "against": a.against, "date": day, "changes": a.changed})
    t["status"] = f"checked against {a.against} by {a.by} on {day}"
    TABLES.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"{a.table}: {t['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
