#!/usr/bin/env python3
"""Board factory profiles: check the design against a factory's published minimums, and add them to KiCad's rules.

    python scripts/fab_rules.py . list                    the factories and when their pages were read
    python scripts/fab_rules.py . check [--fab NAME]      board setup and net classes against the factory
    python scripts/fab_rules.py . write [--fab NAME]      put the factory's limits into the .kicad_dru

The factory is --fab, else "fab" in boardwright.json, else jlcpcb. Profiles are in
fab_profiles.json; every value names its page and the day it was read, and a value the factory does
not publish is "unverified", never guessed.

write adds one marked section right after (version 1):
    # BEGIN Boardwright fab profile <fab> ... # END Boardwright fab profile
It is replaced in place on every write; everything outside the markers stays byte for byte. KiCad lets
later rules win, so your own rules after the section keep precedence. Each value written is the
stricter of the factory's minimum and your board setup's, so the section never loosens anything.
Clearance and track width are not written (they belong to the net classes); check reports any net
class or board minimum below the factory's as a conflict, and changes nothing.
Standard library only. Exit 0 ok, 1 conflicts found, 2 setup problem.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from bw_project import SetupError, load_config, md_table, project_files, write_report  # noqa: E402

BEGIN, END = "# BEGIN Boardwright fab profile", "# END Boardwright fab profile"
MAX_AGE_DAYS = 180
# profile key -> (board setup key in .kicad_pro, KiCad rule text with {v})
RULES = {
    "edge_clearance": ("min_copper_edge_clearance", '(constraint edge_clearance (min {v}mm))', None),
    "hole_to_hole": ("min_hole_to_hole", '(constraint hole_to_hole (min {v}mm))', None),
    "via_drill": ("min_through_hole_diameter", '(constraint hole_size (min {v}mm))', "A.Type == 'Via'"),
    "via_diameter": ("min_via_diameter", '(constraint via_diameter (min {v}mm))', "A.Type == 'Via'"),
    "annular_width": ("min_via_annular_width", '(constraint annular_width (min {v}mm))', None),
    "silk_text_height": ("min_text_height", '(constraint text_height (min {v}mm))',
                         "A.Layer == 'F.Silkscreen' || A.Layer == 'B.Silkscreen'"),
    "silk_line": ("min_text_thickness", '(constraint text_thickness (min {v}mm))',
                  "A.Layer == 'F.Silkscreen' || A.Layer == 'B.Silkscreen'"),
}
CHECK_ONLY = {"track_width": "min_track_width", "clearance": "min_clearance"}


def profiles() -> dict:
    return json.loads((HERE / "fab_profiles.json").read_text("utf-8"))["fabs"]


def copper_layers(pro: dict, pcb: Path) -> int:
    try:
        text = pcb.read_text("utf-8", errors="replace")
        # every copper layer of the layer table counts, whatever its type (signal, power, mixed, jumper)
        return len(set(re.findall(r'\(\d+\s+"((?:F|B|In\d+)\.Cu)"\s+\w+', text))) or 2
    except OSError:
        return 2


def values_for(fab: dict, layers: int) -> dict:
    out = {}
    for v in fab["values"]:
        lo, hi = v.get("layers", [1, 32])
        if lo <= layers <= hi and v["key"] not in out:
            out[v["key"]] = v
    return out


def pick(proj: Path, argv: list) -> tuple:
    fabs = profiles()
    name = argv[argv.index("--fab") + 1] if "--fab" in argv else (load_config(proj).get("fab") or "jlcpcb")
    name = str(name).lower()
    if name not in fabs:
        raise SetupError(f"no profile '{name}'; known: {', '.join(fabs)}")
    return name, fabs[name]


def stale(fab: dict) -> int:
    try:
        return (dt.date.today() - dt.date.fromisoformat(fab["read"])).days
    except (KeyError, ValueError):
        return 9999


def cmd_list() -> int:
    for k, f in profiles().items():
        age = stale(f)
        known = sum(1 for v in f["values"] if v["value"] is not None)
        print(f"{k}: {f['name']}, read {f['read']} ({age} days ago{', re-read its pages' if age > MAX_AGE_DAYS else ''}), "
              f"{known} of {len(f['values'])} values published")
    return 0


def cmd_check(proj: Path, argv: list) -> int:
    f = project_files(proj)
    pro = json.loads(f["pro"].read_text("utf-8"))
    setup = ((pro.get("board") or {}).get("design_settings") or {}).get("rules") or {}
    classes = ((pro.get("net_settings") or {}).get("classes")) or []
    name, fab = pick(proj, argv)
    layers = copper_layers(pro, f["pcb"])
    vals = values_for(fab, layers)
    rows, conflicts, unverified = [], [], []
    for key in list(CHECK_ONLY) + list(RULES):
        v = vals.get(key)
        setup_key = CHECK_ONLY.get(key) or RULES[key][0]
        have = setup.get(setup_key)
        if v is None or v["value"] is None:
            unverified.append(key)
            rows.append([key, "unverified", have if have is not None else "-", "not published: check by hand"])
            continue
        state = "ok"
        if have is not None and have < v["value"] - 1e-9:
            state = f"board setup {have} is below the factory's {v['value']}"
            conflicts.append(f"{key}: {state}")
        rows.append([key, v["value"], have if have is not None else "-", state])
    for c in classes:
        for key, ck in (("track_width", "track_width"), ("clearance", "clearance")):
            v = vals.get(key)
            if v and v["value"] is not None and c.get(ck) is not None and c[ck] < v["value"] - 1e-9:
                conflicts.append(f"net class {c.get('name')}: {ck} {c[ck]} is below the factory's {v['value']}")
    age = stale(fab)
    print(f"factory: {fab['name']} ({layers} copper layers), pages read {fab['read']}"
          + (f" -- {age} days ago, re-read them" if age > MAX_AGE_DAYS else ""))
    for r in rows:
        print(f"  {r[0]}: factory {r[1]}, board setup {r[2]}: {r[3]}")
    for c in conflicts:
        print("CONFLICT " + c)
    if unverified:
        print(f"{len(unverified)} value(s) this factory does not publish: check them with the factory before ordering")
    md = [f"# Factory check: {fab['name']}", "", f"Pages read {fab['read']}: " +
          ", ".join(fab["pages"].values()), ""] + md_table(["rule", "factory min (mm)", "board setup (mm)", "result"], rows)
    md += ["", "Conflicts:" if conflicts else "No conflicts."] + [f"- {c}" for c in conflicts]
    write_report(proj, "fab-check", {"fab": name, "read": fab["read"], "conflicts": conflicts,
                                     "unverified": unverified, "rows": rows}, md)
    return 1 if conflicts else 0


def section(fab_key: str, fab: dict, vals: dict, setup: dict) -> str:
    lines = [f"{BEGIN} {fab_key}",
             f"# From {fab['name']}'s published minimums, read {fab['read']}. Written by fab_rules.py;",
             "# each value is the stricter of the factory's and this board's setup. Your own rules below win."]
    for key, (setup_key, text, cond) in RULES.items():
        v = vals.get(key)
        if not v or v["value"] is None:
            continue
        val = max(v["value"], setup.get(setup_key) or 0)
        name = f"fab_{key}"
        body = f'(rule "{name}"\n  {text.format(v=round(val, 4))}'
        if cond:
            body += f'\n  (condition "{cond}")'
        lines.append(f"# {v['note']}")
        lines.append(body + ")")
    lines.append(END)
    return "\n".join(lines)


def cmd_write(proj: Path, argv: list) -> int:
    f = project_files(proj)
    pro = json.loads(f["pro"].read_text("utf-8"))
    setup = ((pro.get("board") or {}).get("design_settings") or {}).get("rules") or {}
    name, fab = pick(proj, argv)
    vals = values_for(fab, copper_layers(pro, f["pcb"]))
    dru = f["dru"]
    text = dru.read_text("utf-8") if dru.exists() else "(version 1)\n"
    sec = section(name, fab, vals, setup)
    if BEGIN in text and END in text:
        a = text.index(BEGIN)
        b = text.index(END, a) + len(END)
        text = text[:a] + sec + text[b:]
    else:
        m = re.search(r"\(version\s+\d+\)\s*\n?", text)
        at = m.end() if m else 0
        if not m:
            text = "(version 1)\n" + text
            at = len("(version 1)\n")
        text = text[:at] + "\n" + sec + "\n\n" + text[at:].lstrip("\n")
    if dru.exists():
        dru.with_name(dru.name + ".bak").write_text(dru.read_text("utf-8"), "utf-8")
    dru.write_text(text, "utf-8")
    print(f"wrote the {fab['name']} section to {dru.name} (backup {dru.name}.bak). Run the DRC: a rules file KiCad "
          "cannot read is ignored whole, so check that run_gates.py's rule guard still passes.")
    return cmd_check(proj, argv)


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    proj = Path(argv[0]).resolve()
    try:
        if argv[1] == "list":
            return cmd_list()
        if argv[1] == "check":
            return cmd_check(proj, argv[2:])
        if argv[1] == "write":
            return cmd_write(proj, argv[2:])
    except SetupError as exc:
        print("ERROR: " + str(exc))
        return 2
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
