#!/usr/bin/env python3
"""Offline test of the lifecycle classifier (standard library only; no network).

    python plugin/tests/test_lifecycle.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lifecycle_check as lc  # noqa: E402

FAILS = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def ans(cyc, nos, model="PART-1"):
    return lc.extract({"result": {"productModel": model, "productCycle": cyc, "isNotOverstock": nos}})


def main() -> int:
    check("active", lc.classify(ans("normal", False), "PART-1")[0] == "active")
    check("nrnd", lc.classify(ans("normal", True), "PART-1")[0] == "nrnd")
    check("obsolete/discontinued", lc.classify(ans("stop_product", True), "PART-1")[0] == "eol")
    check("missing field", lc.classify(ans(None, False), "PART-1")[0] == "unverified")
    check("unknown value", lc.classify(ans("weird", False), "PART-1")[0] == "unverified")
    check("not found", lc.classify(lc.extract({"result": None}), "PART-1")[0] == "unverified")
    check("network error", lc.classify({"error": "timeout"}, "PART-1")[0] == "unverified")
    check("wrong part", lc.classify(ans("normal", False, "OTHER"), "PART-1")[0] == "unverified")

    parts = [{"refs": ["U1"], "mpn": "PART-1", "lcsc": "C12345"}, {"refs": ["U2"], "mpn": "X", "lcsc": ""}]
    answers = {"C12345": ans("normal", False)}
    rows = lc.run(parts, {}, date(2026, 1, 1), fetcher=lambda k: answers[k], sleep=lambda s: None)
    check("exit 0 with active + unverified", lc.exit_code(rows) == 0 and rows[1]["status"] == "unverified")
    answers["C12345"] = ans("normal", True)
    rows = lc.run(parts, {}, date(2026, 1, 1), fetcher=lambda k: answers[k], sleep=lambda s: None)
    check("nrnd is listed, not failed (exit 0)", lc.exit_code(rows) == 0)
    data = lc.report_data(rows)
    check("json pass is true with only nrnd (agrees with exit 0)", data["pass"] is True, str(data["pass"]))
    check("check_by_hand lists the nrnd and the unverified part",
          sorted(h["status"] for h in data["check_by_hand"]) == ["nrnd", "unverified"], str(data["check_by_hand"]))
    answers["C12345"] = ans("stop_product", True)
    rows = lc.run(parts, {}, date(2026, 1, 1), fetcher=lambda k: answers[k], sleep=lambda s: None)
    check("exit 1 with eol", lc.exit_code(rows) == 1)
    check("json pass is false with eol", lc.report_data(rows)["pass"] is False)

    cache = {"C12345": {"date": "2026-01-01", "answer": ans("normal", False)}}
    boom = lambda k: (_ for _ in ()).throw(AssertionError("network used"))  # noqa: E731
    rows = lc.run(parts, cache, date(2026, 1, 5), fetcher=boom, sleep=lambda s: None)
    check("fresh cache used", rows[0]["status"] == "active" and rows[0]["cached"])
    rows = lc.run(parts, cache, date(2026, 3, 1), offline=True, fetcher=boom, sleep=lambda s: None)
    check("offline uses stale cache", rows[0]["status"] == "active")
    rows = lc.run(parts, {}, date(2026, 3, 1), offline=True, fetcher=boom, sleep=lambda s: None)
    check("offline without cache is unverified", rows[0]["status"] == "unverified")
    rows = lc.run(parts, cache, date(2026, 1, 5), refresh=True, fetcher=lambda k: ans("normal", True), sleep=lambda s: None)
    check("refresh ignores cache", rows[0]["status"] == "nrnd")
    print("PASS" if not FAILS else f"FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
