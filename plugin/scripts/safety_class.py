#!/usr/bin/env python3
"""Safety intake: sort the board's nets into voltage domains and energy classes, sort the supplies
into power-source classes, and check that the safety settings are complete.

Usage:  python scripts/safety_class.py <project_dir>

Reads the "safety" section of boardwright.json (format: references/high-voltage.md), the net-class
patterns in the .kicad_pro and the net names in the .kicad_pcb. Writes reports/safety-class.json/.md.

Energy classes (ES1/ES2/ES3) and power-source classes (PS1/PS2/PS3) follow IEC 62368-1:2023; the
thresholds are in spacing_tables.json with their status (secondary source until checked).

Fails when: the board is mains-connected or has a "barrier" section but no "safety" section; a domain
names a net class that does not exist or matches no net; a net sits in two domains; a domain above
ES1 has no barrier to the ES1 side; or no standard is named while a domain is above ES1.
Exit 0 pass, 1 a check failed, 2 setup problem. Changes nothing.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import (SetupError, board_nets, load_config, md_table, nets_by_class,  # noqa: E402
                        project_files, write_report)
from spacing import TABLES  # noqa: E402


def es_class(d: dict) -> str:
    """ES class of a domain from its declared vdc / vrms / vpeak (the worst one decides). A domain that
    is mains-referenced (e.g. a flyback controller's 15 V supply on the primary) is ES3 whatever its
    voltage: touching it is touching mains."""
    es = TABLES["energy_classes"]
    if d.get("mains_referenced") or d.get("kind") == "mains":
        return es["es_above"]
    for row in es["es"]:
        ok = all(d.get(k) is None or d[k] <= row[m] for k, m in
                 (("vdc", "max_vdc"), ("vrms", "max_vrms"), ("vpeak", "max_vpeak")))
        if ok:
            return row["class"]
    return es["es_above"]


def ps_class(w: float | None) -> str:
    if w is None:
        return "unverified"
    es = TABLES["energy_classes"]
    for row in es["ps"]:
        if w <= row["max_w"]:
            return row["class"]
    return es["ps_above"]


def mains_declared(project: Path) -> bool:
    pm = project / "PROJECT.md"
    if not pm.is_file():
        return False
    return bool(re.search(r"(?i)mains-connected[\s*:|`]*yes\b(?!\s*/)", pm.read_text("utf-8", errors="replace")))


def analyse(project: Path) -> tuple:
    f = project_files(project)
    cfg = load_config(project)
    s = cfg.get("safety")
    problems, notes = [], []
    if not isinstance(s, dict):
        if mains_declared(project) or "barrier" in cfg:
            problems.append("the board is mains-connected or has a barrier section, but boardwright.json has "
                            "no 'safety' section (see references/high-voltage.md)")
        else:
            notes.append("no 'safety' section: treated as a low-voltage board (all nets ES1). Add one with the "
                         "supply's rated power to record its PS class.")
        return {"domains": [], "supplies": [], "barriers": []}, problems, notes

    nets = board_nets(f["pcb"])
    if not nets:
        raise SetupError(f"no nets found in {f['pcb'].name} (is the board empty?)")
    by_class = nets_by_class(f["pro"], nets)
    domains, owner = [], {}
    for d in s.get("domains") or []:
        name = d.get("name") or "?"
        dn = set()
        for cls in d.get("netclasses") or []:
            if cls not in by_class:
                problems.append(f"domain '{name}': net class '{cls}' is not defined in {f['pro'].name}")
            elif not by_class[cls]:
                problems.append(f"domain '{name}': net class '{cls}' matches no net on the board")
            dn |= set(by_class.get(cls, []))
        for n in d.get("nets") or []:
            (dn.add(n) if n in nets else problems.append(f"domain '{name}': net '{n}' is not on the board"))
        domains.append({"name": name, "nets": dn, "rest": bool(d.get("rest")), "cfg": d,
                        "es": es_class(d), "netclasses": d.get("netclasses") or []})
    taken = set()
    for d in domains:
        if not d["rest"]:
            for n in d["nets"]:
                if n in owner:
                    problems.append(f"net {n} is in two domains: {owner[n]} and {d['name']}")
                owner[n] = d["name"]
            taken |= d["nets"]
    for d in domains:
        if d["rest"]:
            d["nets"] = set(nets) - taken
    if not any(d["rest"] for d in domains):
        loose = sorted(set(nets) - taken)
        if loose:
            notes.append(f"{len(loose)} net(s) in no domain are treated as ES1 (add a domain with \"rest\": true to "
                         f"state their voltage): {', '.join(loose[:8])}{' ...' if len(loose) > 8 else ''}")

    hazardous = [d for d in domains if d["es"] != "ES1"]
    if hazardous and not s.get("standard"):
        problems.append("a domain is above ES1 but no product safety standard is named (safety.standard, e.g. "
                        "'IEC 62368-1:2023'); choosing it is the user's decision")
    barriers = s.get("barriers") or []
    names = {d["name"] for d in domains}
    for b in barriers:
        for side in ("between", "and"):
            for dn in b.get(side) or []:
                if dn not in names:
                    problems.append(f"barrier '{b.get('name')}': unknown domain '{dn}'")
    low = [d for d in domains if d["es"] == "ES1"]
    for d in hazardous:
        if low and not any(d["name"] in (b.get("between") or []) + (b.get("and") or []) for b in barriers):
            problems.append(f"domain '{d['name']}' is {d['es']} but no barrier separates it from the ES1 side")
        if not d["netclasses"]:
            problems.append(f"domain '{d['name']}' is {d['es']} but has no net class, so no DRC rule can see it")

    supplies = []
    for p in s.get("supplies") or []:
        cls = ps_class(p.get("max_w"))
        supplies.append({"name": p.get("name"), "max_w": p.get("max_w"), "ps": cls, "source": p.get("source", "")})
        if cls == "unverified":
            notes.append(f"supply '{p.get('name')}': no max_w, so its PS class is unverified")
    out = {"standard": s.get("standard"), "product_class": s.get("product_class"),
           "domains": [{"name": d["name"], "es": d["es"], "netclasses": d["netclasses"], "nets": len(d["nets"]),
                        "vdc": d["cfg"].get("vdc"), "vrms": d["cfg"].get("vrms"), "vpeak": d["cfg"].get("vpeak")}
                       for d in domains],
           "supplies": supplies, "barriers": barriers}
    return out, problems, notes


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        out, problems, notes = analyse(project)
    except SetupError as exc:
        print(f"safety_class: setup problem: {exc}")
        return 2
    t = TABLES["energy_classes"]
    md = ["# Safety intake (safety_class.py)", "",
          f"Standard: {out.get('standard') or 'not named'}; product class: {out.get('product_class') or 'not stated'}",
          f"Class thresholds: {t['source']} ({t['status']}).", ""]
    if out["domains"]:
        md += md_table(["domain", "class", "nets", "Vdc", "Vrms", "Vpeak", "net classes"],
                       [[d["name"], d["es"], d["nets"], d["vdc"] or "", d["vrms"] or "", d["vpeak"] or "",
                         ", ".join(d["netclasses"]) or "(rest)"] for d in out["domains"]]) + [""]
    if out["supplies"]:
        md += md_table(["supply", "max W", "class", "source"],
                       [[p["name"], p["max_w"] if p["max_w"] is not None else "?", p["ps"], p["source"]]
                        for p in out["supplies"]]) + [""]
    md += [f"- FAIL: {p}" for p in problems] + [f"- note: {n}" for n in notes]
    md += ["", f"Result: {'FAIL' if problems else 'PASS'}"]
    out.update({"pass": not problems, "errors": len(problems), "problems": problems, "notes": notes})
    write_report(project, "safety-class", out, md)
    print("\n".join(md))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
