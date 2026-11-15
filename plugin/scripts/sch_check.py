#!/usr/bin/env python3
"""Deterministic schematic checks that run before layout.

Usage:  python sch_check.py [project_dir]

project_dir defaults to the current working directory.
Exports the netlist with kicad-cli (kicadxml), parses it, and checks fields,
footprints, pins, power nets and references (S1..S9, see CHECKS below).
Exit code 0 = no ERROR, 1 = at least one ERROR, 2 = tool or setup problem.
Reports: <project_dir>/reports/sch-check.json and sch-check.md.
There is deliberately no option to skip, filter or downgrade a check.

CHECKS
 S1 fields (Footprint, MPN ERROR; Datasheet WARN)   S2 datasheet file on disk (heuristic)
 S3 footprint exists, pads match symbol pins        S4 single-pin nets / unconnected pins
 S5 power_in net has a source (cheap sanity)        S6 IC power pins have a capacitor
 S7 duplicate or "?" references                     S8 two-pin diode/LED/polarised cap shorted
 S9 net names differing only by case or leading "/"
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_gates import find_kicad_cli  # noqa: E402

MAX_STDOUT_ROWS = 60
MPN_NAMES = ("mpn", "mfr part", "manufacturer_part_number", "manufacturer part number")
S2_EXEMPT = {"R", "C", "L", "FB", "TP", "H", "MH"}
GND_RE = re.compile(r"GND|VSS", re.I)


class SetupError(Exception):
    pass


# ------------------------------------------------------------------ helpers
def find_root_schematic(project):
    stems = set()
    for pattern in ("*.kicad_pro", "*.kicad_pcb"):
        found = sorted(project.glob(pattern))
        if len(found) > 1:
            raise SetupError(f"more than one {pattern} in {project}; cannot pick the project")
        stems.update(p.stem for p in found)
    if len(stems) != 1:
        raise SetupError(f"no single project stem found in {project} "
                         f"(*.kicad_pro / *.kicad_pcb give {sorted(stems) or 'nothing'})")
    sch = project / f"{stems.pop()}.kicad_sch"
    if not sch.exists():
        raise SetupError(f"root schematic {sch.name} not found in {project}")
    return sch


def export_netlist(cli, sch):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "netlist.xml"
        cmd = [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out), str(sch)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            raise SetupError("netlist export failed: " + (proc.stderr or proc.stdout).strip()[:500])
        try:
            return ET.parse(out).getroot(), " ".join(cmd)
        except ET.ParseError as exc:
            raise SetupError(f"cannot parse netlist XML: {exc}")


def parse_netlist(root):
    comps = []
    for c in root.findall("./components/comp"):
        fields = {}
        for f in c.findall("./fields/field"):
            fields[(f.get("name") or "").strip().lower()] = (f.text or "").strip()
        props = {(p.get("name") or "").strip().lower() for p in c.findall("./property")}
        ls = c.find("libsource")
        comps.append({
            "ref": c.get("ref") or "",
            "value": (c.findtext("value") or "").strip(),
            "footprint": (c.findtext("footprint") or "").strip(),
            "fields": fields,
            "skip": any(p == "dnp" or "exclude_from_board" in p for p in props),
            "lib": ls.get("lib") if ls is not None else "",
            "part": ls.get("part") if ls is not None else "",
        })
    libparts = {}
    for lp in root.findall("./libparts/libpart"):
        pins = {p.get("num"): (p.get("type") or "") for p in lp.findall("./pins/pin")}
        libparts[(lp.get("lib") or "", lp.get("part") or "")] = pins
    nets = OrderedDict()
    for n in root.findall("./nets/net"):
        nodes = [{"ref": nd.get("ref") or "", "pin": nd.get("pin") or "",
                  "func": nd.get("pinfunction") or "", "type": nd.get("pintype") or ""}
                 for nd in n.findall("node")]
        nets[n.get("name") or ""] = nodes
    return comps, libparts, nets


def mpn_of(comp):
    for name in MPN_NAMES:
        if comp["fields"].get(name):
            return comp["fields"][name]
    return ""


def ref_prefix(ref):
    m = re.match(r"[A-Za-z]+", ref)
    return m.group(0).upper() if m else ""


class Findings:
    """Collect findings, grouping identical (id, severity, message) into one row."""

    def __init__(self):
        self.groups = OrderedDict()
        self.count = {"ERROR": 0, "WARN": 0}

    def add(self, cid, sev, subject, msg):
        self.groups.setdefault((cid, sev, msg), []).append(subject)
        self.count[sev] += 1

    def rows(self):
        rows = [{"id": k[0], "severity": k[1], "subject": ", ".join(v), "message": k[2], "count": len(v)}
                for k, v in self.groups.items()]
        rows.sort(key=lambda r: (r["severity"] != "ERROR", r["id"]))
        return rows


def natural_key(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


# ---------------------------------------------------------------- footprints
def read_lib_table(path):
    libs = {}
    if not path.exists():
        return libs
    text = path.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'\(lib\s+\(name\s+"([^"]*)"\).*?\(uri\s+"([^"]*)"\)', text, re.S):
        libs[m.group(1)] = m.group(2)
    return libs


def stock_footprint_dirs(cli):
    dirs = []
    for var, val in os.environ.items():
        if re.fullmatch(r"KICAD\d*_FOOTPRINT_DIR", var) and val:
            dirs.append(Path(val))
    base = Path(cli).resolve().parent.parent
    dirs.append(base / "share" / "kicad" / "footprints")
    return [d for d in dirs if d.is_dir()]


def pads_of(path, cache):
    if path not in cache:
        text = path.read_text(encoding="utf-8", errors="replace")
        cache[path] = {m.group(1) for m in re.finditer(r'\(pad\s+"?([^"\s)]*)"?', text) if m.group(1)}
    return cache[path]


def find_footprint(fp, project, project_libs, stock, ):
    if ":" not in fp:
        return None
    lib, name = fp.split(":", 1)
    if lib in project_libs:
        uri = project_libs[lib].replace("${KIPRJMOD}", str(project))
        cand = Path(uri) / f"{name}.kicad_mod"
        if cand.exists():
            return cand
    for d in stock:
        cand = d / f"{lib}.pretty" / f"{name}.kicad_mod"
        if cand.exists():
            return cand
    return None


# -------------------------------------------------------------------- checks
def run_checks(project, cli, comps, libparts, nets):
    F = Findings()
    active = [c for c in comps if not c["ref"].startswith("#")]
    checked = [c for c in active if not c["skip"]]
    by_ref = {}
    for c in active:
        by_ref.setdefault(c["ref"], []).append(c)

    # S7 references
    for ref, lst in by_ref.items():
        if len(lst) > 1:
            F.add("S7", "ERROR", ref, f"duplicate reference ({len(lst)} components)")
        if ref.endswith("?"):
            F.add("S7", "ERROR", ref, "reference not annotated")

    # S1 fields
    for c in checked:
        if not c["footprint"]:
            F.add("S1", "ERROR", c["ref"], "Footprint empty")
        if not mpn_of(c):
            F.add("S1", "ERROR", c["ref"], "MPN empty")
        if c["fields"].get("datasheet", "") in ("", "~"):
            F.add("S1", "WARN", c["ref"], "Datasheet empty or ~")

    # S2 datasheet files (heuristic)
    ds_dir = project / "datasheets"
    if ds_dir.is_dir():
        files = [re.sub(r"[^a-z0-9]", "", p.name.lower()) for p in ds_dir.rglob("*") if p.is_file()]
        for c in checked:
            if ref_prefix(c["ref"]) in S2_EXEMPT:
                continue
            # tokens must contain a digit so that maker names ("Infineon") cannot match
            tokens = [t.lower() for t in re.split(r"[^A-Za-z0-9]+", mpn_of(c))
                      if len(t) >= 5 and re.search(r"\d", t)]
            tokens += [t.lower() for t in re.split(r"[^A-Za-z0-9]+", c["value"])
                       if len(t) >= 5 and re.search(r"\d", t)]
            vnorm = re.sub(r"[^a-z0-9]", "", c["value"].lower())
            if len(vnorm) >= 3 and re.search(r"\d", vnorm):
                tokens.append(vnorm)
            # family datasheets drop the variant suffix: also try prefixes down to 6 characters
            prefixes = [t[:n] for t in tokens for n in range(len(t) - 1, 5, -1)
                        if re.search(r"\d", t[:n])]
            if not any(t in f for t in tokens + prefixes for f in files):
                tried = ", ".join(dict.fromkeys(tokens)) or "no token >= 5 chars"
                F.add("S2", "WARN", c["ref"], f"no datasheet file matched (tried: {tried})")

    # S3 footprint vs pins
    project_libs = read_lib_table(project / "fp-lib-table")
    stock = stock_footprint_dirs(cli)
    cache = {}
    for c in checked:
        if not c["footprint"]:
            continue
        path = find_footprint(c["footprint"], project, project_libs, stock)
        if path is None:
            F.add("S3", "ERROR", c["ref"], f"footprint file not found: {c['footprint']}")
            continue
        pads = pads_of(path, cache)
        pins = set(libparts.get((c["lib"], c["part"]), {}))
        if not pins:  # fall back to pins that appear in nets
            pins = {n["pin"] for nodes in nets.values() for n in nodes if n["ref"] == c["ref"]}
        missing = sorted(pins - pads, key=natural_key)
        if missing:
            F.add("S3", "ERROR", c["ref"],
                  f"symbol pin(s) {','.join(missing)} have no pad in {c['footprint']}")
        extra = sorted(pads - pins, key=natural_key)
        if extra:
            F.add("S3", "WARN", c["ref"],
                  f"pad(s) {','.join(extra)} used by no symbol pin in {c['footprint']}")

    # node bookkeeping
    comp_by_ref = {c["ref"]: c for c in active}
    skipped = {c["ref"] for c in active if c["skip"]}

    def real_nodes(nodes):
        return [n for n in nodes if not n["ref"].startswith("#")]

    # S4 single-pin nets and unconnected pins
    for name, nodes in nets.items():
        nodes = real_nodes(nodes)
        if len(nodes) != 1:
            continue
        n = nodes[0]
        who = f"{n['ref']}.{n['pin']}"
        if name.startswith("unconnected-") or name.startswith("/unconnected-"):
            if n["type"] in ("power_in", "power_out", "input"):
                F.add("S4", "WARN", who, f"pin left unconnected ({n['type']}{' ' + n['func'] if n['func'] else ''})")
        elif n["type"] != "no_connect":
            F.add("S4", "WARN", f"{name} ({who})", "net has a single pin")

    # S5 power inputs need a source, S6 decoupling
    for name, nodes in nets.items():
        nodes = real_nodes(nodes)
        for n in nodes:
            if n["type"] != "power_in" or n["ref"] in skipped:
                continue
            others = [o for o in nodes if o is not n and o["ref"] not in skipped]
            has_out = any(o["type"] == "power_out" for o in others)
            has_passive = any(o["type"] not in ("power_in", "no_connect") for o in others) and len(nodes) >= 3
            if not (has_out or has_passive):
                F.add("S5", "WARN", f"{n['ref']}.{n['pin']} ({name})", "power input net has no source")
        if GND_RE.search(name):
            continue
        has_cap = any(re.match(r"C\d", o["ref"]) and o["ref"] not in skipped for o in nodes)
        if has_cap:
            continue
        for n in nodes:
            if n["type"] == "power_in" and n["ref"] not in skipped and re.match(r"(U|IC)", n["ref"]):
                F.add("S6", "WARN", f"{n['ref']}.{n['pin']} ({name})", "no capacitor on power input net")

    # S8 polarised / diode parts shorted
    pins_by_ref = {}
    for name, nodes in nets.items():
        for n in nodes:
            pins_by_ref.setdefault(n["ref"], []).append((n["pin"], name))
    for c in checked:
        pol = (re.match(r"(D|LED)", c["ref"]) or "Polarized" in c["part"] or re.search(r"CP", c["part"]))
        if not pol:
            continue
        pl = pins_by_ref.get(c["ref"], [])
        if len(libparts.get((c["lib"], c["part"]), {})) != 2 and len(pl) != 2:
            continue
        if len(pl) == 2 and pl[0][1] == pl[1][1]:
            F.add("S8", "ERROR", c["ref"], f"both pins on net {pl[0][1]} (shorted)")
        elif len(pl) == 1 and len(libparts.get((c["lib"], c["part"]), {})) == 2:
            F.add("S8", "ERROR", c["ref"], f"both pins on net {pl[0][1]} (shorted)")

    # S9 net-name hygiene
    norm = {}
    for name in nets:
        if name.startswith("unconnected-") or name.startswith("/unconnected-"):
            continue
        norm.setdefault(name.lstrip("/").lower(), []).append(name)
    for key, names in norm.items():
        if len(names) > 1:
            F.add("S9", "WARN", " vs ".join(names), "net names differ only by case or leading '/'")

    return F


# -------------------------------------------------------------------- output
def esc(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def table(rows):
    out = ["| id | sev | ref/net | message |", "|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['id']} | {r['severity']} | {esc(r['subject'])} | {esc(r['message'])} |")
    return out


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in argv if not a.startswith("-")]
    if len(args) > 1 or len(args) != len(argv):
        print(__doc__)
        return 2
    project = Path(args[0] if args else ".").resolve()
    try:
        if not project.is_dir():
            raise SetupError(f"{project} is not a directory")
        cli = find_kicad_cli()
        if not cli:
            raise SetupError("kicad-cli not found (set KICAD_CLI or add it to PATH)")
        sch = find_root_schematic(project)
        root, cmd = export_netlist(cli, sch)
        comps, libparts, nets = parse_netlist(root)
        F = run_checks(project, cli, comps, libparts, nets)
    except SetupError as exc:
        print(f"sch_check: setup problem: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # unexpected parse problem: do not pass silently
        print(f"sch_check: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    rows = F.rows()
    n_comp = len([c for c in comps if not c["ref"].startswith("#")])
    summary = (f"components {n_comp}, nets {len(nets)}, "
               f"errors {F.count['ERROR']}, warnings {F.count['WARN']}")

    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "sch-check.json").write_text(json.dumps({
        "schematic": sch.name, "command": cmd, "summary": summary,
        "components": n_comp, "nets": len(nets),
        "errors": F.count["ERROR"], "warnings": F.count["WARN"], "rows": rows,
    }, indent=2), encoding="utf-8")
    (reports / "sch-check.md").write_text(
        "# Schematic check\n\n" + summary + "\n\n" + "\n".join(table(rows)) + "\n", encoding="utf-8")

    print("\n".join(table(rows[:MAX_STDOUT_ROWS])))
    if len(rows) > MAX_STDOUT_ROWS:
        print(f"... {len(rows) - MAX_STDOUT_ROWS} more (see reports/sch-check.json)")
    print(summary)
    return 1 if F.count["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
