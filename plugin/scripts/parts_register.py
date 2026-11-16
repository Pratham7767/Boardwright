#!/usr/bin/env python3
"""Register of safety-critical parts, for the release checklist and the certifier.

Usage:  python scripts/parts_register.py <project_dir>

Lists every part that carries safety: fuses, X and Y capacitors, varistors, X-capacitor discharge
parts (mains_check.py roles), every part that bridges a barrier in boardwright.json "safety"
(transformers, optocouplers, Y capacitors), and ESD/TVS parts on connectors. For each it reports the
symbol fields that a certifier asks for:
    cert            certificate or file number (UL file, VDE/TUV/CQC certificate)
    cert_standard   standard and edition the certificate is issued to (e.g. IEC 62368-1:2018)
    rating          the safety rating that matters (VIORM/VIOTM, X2 310 VAC, fuse I2t, Y1 500 VAC)
A missing field is "unverified". A certificate issued only to IEC 60950 or IEC 60065 is flagged:
IEC 62368-1 Ed.4 (2023) no longer accepts those without re-evaluation (research notes, secondary).
Writes reports/parts-register.json/.md. It never fails a design (exit 0; 2 = setup problem): the
register is evidence for a person to check against the certificates themselves.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, board_nets, load_config, md_table, nets_by_class, project_files, write_report  # noqa: E402
from mains_check import build  # noqa: E402

FIELDS = ("cert", "cert_standard", "rating")
SAFETY_ROLES = {"fuse", "X1", "X2", "Y1", "Y2", "MOV", "xcap_discharge"}
OLD_STD = re.compile(r"60950|60065")
PROTECT = re.compile(r"(?i)\b(ESD|TVS|USBLC|PESD|SMAJ|SMBJ|SMCJ|TPD\d|PRTR)")


def main(argv: list) -> int:
    project = Path(argv[0]).resolve() if argv else Path.cwd()
    try:
        f = project_files(project)
        s = load_config(project).get("safety") or {}
        from run_gates import find_kicad_cli
        from sch_check import export_netlist, parse_netlist
        cli = find_kicad_cli()
        if not cli or not f["sch"].is_file():
            raise SetupError("kicad-cli or the schematic is missing")
        root, _ = export_netlist(cli, f["sch"])
        comps, _lib, nets = parse_netlist(root)
    except (SetupError, Exception) as exc:
        print(f"parts_register: setup problem: {exc}")
        return 2
    parts = build(comps, nets)
    names = sorted(set(nets) | set(board_nets(f["pcb"]) if f["pcb"].is_file() else []))
    by_class = nets_by_class(f["pro"], names)
    domains = s.get("domains") or []

    def dnets(dn: list) -> set:
        out = set()
        for d in domains:
            if d.get("name") in dn:
                for c in d.get("netclasses") or []:
                    out |= set(by_class.get(c, []))
                out |= set(d.get("nets") or [])
        return out

    why = {}
    for ref, p in parts.items():
        if p["role"] in SAFETY_ROLES:
            why.setdefault(ref, []).append(f"{p['role']} (mains protection)")
    for b in s.get("barriers") or []:
        hot = dnets(b.get("between") or [])
        for ref, p in parts.items():
            pn = set(p["pins"].values())
            if pn & hot and pn - hot:
                why.setdefault(ref, []).append(f"bridges barrier '{b.get('name')}' ({b.get('insulation', 'basic')})")
    for ref, p in parts.items():
        c = p["comp"]
        text = " ".join([c["value"], c["fields"].get("mpn", ""), c["fields"].get("description", "")])
        if PROTECT.search(text):
            why.setdefault(ref, []).append("ESD / surge protection")

    rows, missing, old = [], 0, []
    for ref in sorted(why, key=lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r) or 0))):
        c = parts[ref]["comp"]
        vals = [c["fields"].get(k, "").strip() or "unverified" for k in FIELDS]
        missing += sum(v == "unverified" for v in vals)
        if OLD_STD.search(vals[1]) and "62368" not in vals[1]:
            old.append(ref)
        rows.append([ref, c["value"], c["fields"].get("mpn", "") or "-", "; ".join(why[ref])] + vals)
    md = ["# Safety-critical parts register (parts_register.py)", ""]
    if rows:
        md += md_table(["ref", "value", "MPN", "why it is listed", "cert", "cert standard", "rating"], rows)
    else:
        md.append("No safety-critical parts found (no mains parts, barrier-bridging parts or ESD/TVS parts).")
    md += [""]
    if missing:
        md.append(f"- {missing} field(s) unverified: add cert, cert_standard and rating to the symbols from each "
                  "part's certificate (not from the datasheet's marketing page).")
    if old:
        md.append(f"- Certificates only under IEC 60950/60065: {', '.join(old)}. IEC 62368-1 Ed.4 needs them "
                  "re-evaluated; ask the maker for a 62368-1 certificate.")
    md += ["", "This register is evidence for a person: every certificate must be read and checked, including its "
           "scope and conditions of acceptability."]
    write_report(project, "parts-register", {"rows": rows, "unverified_fields": missing, "old_standard": old,
                                             "pass": True, "errors": 0}, md)
    print(f"Parts register: {len(rows)} safety-critical part(s), {missing} unverified field(s)"
          + (f", {len(old)} with 60950/60065-only certificates" if old else "") + " (details: reports/parts-register.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
