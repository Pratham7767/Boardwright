"""Shared helpers for the boardwright gate scripts (standard library only).

Imported by safety_class.py, creepage_rules.py, mains_check.py, hs_rules.py, emc_harmonics.py
and run_gates.py. Works with the system Python and with KiCad's bundled Python (-I).
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent


class SetupError(Exception):
    """A problem with the inputs (missing file, bad config): exit code 2."""


def project_files(project: Path) -> dict:
    """The single .kicad_pro/.kicad_pcb/.kicad_sch/.kicad_dru of a project (by the .kicad_pro stem)."""
    pros = sorted(project.glob("*.kicad_pro"))
    if len(pros) != 1:
        raise SetupError(f"expected exactly one *.kicad_pro in {project}, found {len(pros)}")
    stem = pros[0].stem
    return {"stem": stem, "pro": pros[0], "pcb": project / f"{stem}.kicad_pcb",
            "sch": project / f"{stem}.kicad_sch", "dru": project / f"{stem}.kicad_dru"}


def load_config(project: Path) -> dict:
    cfg = project / "boardwright.json"
    if not cfg.is_file():
        return {}
    try:
        return json.loads(cfg.read_text("utf-8"))
    except ValueError as exc:
        raise SetupError(f"boardwright.json is not valid JSON: {exc}")


def board_nets(pcb: Path) -> list:
    """Net names in a .kicad_pcb (KiCad 9 '(net N "name")' and KiCad 10 '(net "name")')."""
    if not pcb.is_file():
        return []
    text = pcb.read_text("utf-8", errors="replace")
    names = set(re.findall(r'\(net\s+\d+\s+"((?:[^"\\]|\\.)*)"\)', text))
    names |= set(re.findall(r'\(net\s+"((?:[^"\\]|\\.)*)"\)', text))
    names.discard("")
    return sorted(names)


def netclass_settings(pro: Path) -> dict:
    try:
        ns = json.loads(pro.read_text("utf-8")).get("net_settings") or {}
    except (OSError, ValueError) as exc:
        raise SetupError(f"cannot read {pro.name}: {exc}")
    return {"classes": {c.get("name") for c in (ns.get("classes") or []) if c.get("name")},
            "patterns": [(p.get("netclass"), p.get("pattern")) for p in (ns.get("netclass_patterns") or [])
                         if p.get("netclass") and p.get("pattern")],
            "assignments": ns.get("netclass_assignments") or {}}


def pattern_matches(pattern: str, net: str) -> bool:
    """KiCad net-class patterns are wildcards (* and ?), matched against the full net name.
    A pattern without a leading '/' also matches a hierarchical name ending in it."""
    if fnmatch.fnmatchcase(net, pattern):
        return True
    return not pattern.startswith("/") and fnmatch.fnmatchcase(net.rsplit("/", 1)[-1], pattern)


def nets_by_class(pro: Path, nets: list) -> dict:
    """{netclass: [nets]} from the project's patterns and explicit assignments."""
    st = netclass_settings(pro)
    out: dict = {c: [] for c in st["classes"]}
    for cls, pat in st["patterns"]:
        hits = [n for n in nets if pattern_matches(pat, n)]
        out.setdefault(cls, [])
        out[cls] += [n for n in hits if n not in out[cls]]
    for net, cls in st["assignments"].items():
        for c in (cls if isinstance(cls, list) else [cls]):
            out.setdefault(c, [])
            if net not in out[c]:
                out[c].append(net)
    return out


def unmatched_patterns(pro: Path, nets: list) -> list:
    """(netclass, pattern) pairs that match no net on the board."""
    return [(c, p) for c, p in netclass_settings(pro)["patterns"] if not any(pattern_matches(p, n) for n in nets)]


def write_report(project: Path, name: str, data: dict, md_lines: list) -> None:
    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", "utf-8")
    (reports / f"{name}.md").write_text("\n".join(md_lines).rstrip() + "\n", "utf-8")


def md_table(head: list, rows: list) -> list:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}


def parse_value(text: str, unit: str) -> float | None:
    """'100n', '0.1uF', '4u7', '1M', '470k', '2.2nF 275V X2' -> SI value; None when unreadable.
    unit: 'F', 'R' (ohm) or 'A'."""
    if not text:
        return None
    t = text.strip().replace(",", ".")
    t = re.sub(r"(?i)meg", "M", t)
    t = re.sub(r"(?i)ohms?|Ω", "R" if unit == "R" else "", t)
    letter = {"F": "F", "R": "R", "A": "A"}[unit]
    lb = "" if unit == "A" else r"(?<![A-Za-z])"   # "T2A" is a 2 A fuse; "X2" before a capacitor value is a class
    # prefer a number that carries a multiplier or the unit letter ("X2 0.33uF": 0.33uF, not the 2 of X2)
    m = re.search(lb + r"(\d+(?:\.\d+)?)\s*([pnuµmkKMG]?)(\d*)\s*" + letter + r"?(?![\w.])", t)
    strong = re.search(lb + r"(\d+(?:\.\d+)?)\s*([pnuµmkKMG])(\d*)\s*" + letter + r"?(?![\w.])", t) or         re.search(lb + r"(\d+(?:\.\d+)?)\s*()()" + letter + r"(?![\w.])", t)
    if strong:
        m = strong
    if not m:
        m = re.search(r"(\d+)([pnuµmkKMGR])(\d+)", t)          # 4u7, 4k7, 4R7
        if not m:
            return None
    num, prefix, frac = m.group(1), m.group(2), m.group(3)
    if frac and "." not in num:
        num = f"{num}.{frac}"
    mult = _SI.get(prefix, 1.0) if prefix != "R" else 1.0
    try:
        return float(num) * mult
    except ValueError:
        return None


def fmt_si(v: float, unit: str) -> str:
    for p, m in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if abs(v) >= m:
            return f"{v / m:.3g} {p}{unit}"
    return f"{v:.3g} {unit}"
