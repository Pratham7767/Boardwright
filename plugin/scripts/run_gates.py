#!/usr/bin/env python3
"""Run the KiCad gates (rule guard, ERC, DRC) and, only if all pass, export fab files.

Usage:  python run_gates.py [project_dir] [--no-export | --sch-only]

--sch-only is for stage 4: it runs the rule guard and ERC (it needs no .kicad_pcb), lists DRC
as "not run" and never exports. A run with a gate "not run" exits 0 only for the gates it ran;
the layout and release stages must use the other two forms.

project_dir defaults to the current working directory.
Exit code 0 = all gates passed, 1 = a gate failed, 2 = tool or setup problem.
Reports: <project_dir>/reports/gates.md and gates.json (+ erc.json, drc.json).
There is deliberately no option to skip, filter or waive a check.
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def find_kicad_cli():
    env = os.environ.get("KICAD_CLI")
    if env:
        return env
    found = shutil.which("kicad-cli")
    if found:
        return found
    candidates = []
    # Run with KiCad's bundled Python: kicad-cli sits next to python.exe.
    here = Path(sys.executable).resolve().parent
    candidates += [here / "kicad-cli.exe", here / "kicad-cli"]
    # A custom install on any drive, e.g. E:\KiCAD\bin or D:\KiCad\10.0\bin.
    if os.name == "nt":
        for letter in "CDEFGH":
            root = Path(f"{letter}:/KiCad")
            if root.is_dir():
                candidates.append(root / "bin" / "kicad-cli.exe")
                for ver in sorted(root.iterdir(), reverse=True):
                    candidates.append(ver / "bin" / "kicad-cli.exe")
    # A portable or custom install: look for bin/kicad-cli(.exe) in a parent folder of this script.
    for parent in Path(__file__).resolve().parents:
        for exe in ("kicad-cli.exe", "kicad-cli"):
            candidates.append(parent / "bin" / exe)
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if root:
            kicad = Path(root) / "KiCad"
            if kicad.is_dir():
                for ver in sorted(kicad.iterdir(), reverse=True):
                    candidates.append(ver / "bin" / "kicad-cli.exe")
    candidates.append(Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"))
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def run(cmd):
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")


def count_violations(node, counts=None):
    """Walk a kicad-cli JSON report and count entries by severity."""
    if counts is None:
        counts = {"error": 0, "warning": 0}
    if isinstance(node, dict):
        sev = node.get("severity")
        if sev in counts and ("description" in node or "type" in node):
            counts[sev] += 1
        for value in node.values():
            count_violations(value, counts)
    elif isinstance(node, list):
        for item in node:
            count_violations(item, counts)
    return counts


def result(name, status, detail=""):
    return {"name": name, "status": status, "detail": detail}


# ---------------------------------------------------------------- rule guard
def rule_guard(project, stem):
    """Check that every net class used by a custom DRC rule exists and has members."""
    pro = project / f"{stem}.kicad_pro"
    dru = project / f"{stem}.kicad_dru"
    cfg = project / "boardwright.json"
    if not pro.exists():
        return result("Rule guard", "tool-error", f"{pro.name} not found")
    try:
        ns = json.loads(pro.read_text(encoding="utf-8")).get("net_settings") or {}
    except (OSError, ValueError) as exc:
        return result("Rule guard", "tool-error", f"cannot read {pro.name}: {exc}")
    defined = {c.get("name") for c in (ns.get("classes") or []) if c.get("name")}
    patterns = ns.get("netclass_patterns") or []
    assignments = ns.get("netclass_assignments") or {}
    members = {}
    for p in patterns:
        if p.get("netclass"):
            members[p["netclass"]] = members.get(p["netclass"], 0) + 1
    for _net, cls in assignments.items():
        for c in (cls if isinstance(cls, list) else [cls]):
            members[c] = members.get(c, 0) + 1

    used = set()
    if dru.exists():
        text = dru.read_text(encoding="utf-8", errors="replace")
        text = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        for m in re.finditer(r"hasNetclass\(\s*(['\"])(.*?)\1\s*\)", text):
            used.add(m.group(2))
        for m in re.finditer(r"NetClass\s*==\s*(['\"])(.*?)\1", text):
            used.add(m.group(2))

    custom = defined - {"Default"}
    summary = f"{len(defined)} classes, {len(patterns)} patterns"
    problems = []
    # A pattern can exist and still match nothing (a typo, a renamed net): count the nets each class
    # really gets on the board, so a safety rule cannot go silent.
    matched = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from bw_project import board_nets, nets_by_class
        nets = board_nets(project / f"{stem}.kicad_pcb")
        if nets:
            matched = {c: len(v) for c, v in nets_by_class(pro, nets).items()}
    except Exception as exc:          # the pattern count below still applies
        print(f"  (rule guard: could not match net-class patterns to board nets: {exc})")
    for cls in sorted(used):
        if cls not in defined:
            problems.append(f"'{cls}' used by a rule but not defined in the project")
        elif members.get(cls, 0) == 0:
            problems.append(f"'{cls}' has no patterns or assignments (rule never fires)")
        elif matched is not None and matched.get(cls, 0) == 0:
            problems.append(f"'{cls}' has patterns but they match no net on the board (rule never fires)")
    if cfg.exists():
        try:
            expect = json.loads(cfg.read_text(encoding="utf-8")).get("expect_netclass_patterns")
        except (OSError, ValueError) as exc:
            return result("Rule guard", "tool-error", f"cannot read {cfg.name}: {exc}")
        if isinstance(expect, int) and not isinstance(expect, bool) and len(patterns) != expect:
            problems.append(f"expected {expect} netclass patterns, found {len(patterns)}")
    if problems:
        return result("Rule guard", "FAIL", f"{summary}; " + "; ".join(problems))
    if not dru.exists() and not custom:
        return result("Rule guard", "pass", f"no custom rules ({summary})")
    return result("Rule guard", "pass",
                  f"{len(used)} classes used by rules; {summary}")


# ------------------------------------------------------------------- ERC/DRC
def erc_gate(cli, sch, reports):
    report = reports / "erc.json"
    if report.exists():
        report.unlink()
    proc = run([cli, "sch", "erc", "--format", "json", "--severity-all",
                "--exit-code-violations", "-o", report, sch])
    if proc.returncode not in (0, 5) or not report.exists():
        return result("ERC", "tool-error", (proc.stderr or proc.stdout).strip()[:500])
    c = count_violations(json.loads(report.read_text(encoding="utf-8")))
    return result("ERC", "pass" if c["error"] == 0 else "FAIL",
                  f"{c['error']} errors, {c['warning']} warnings")


def drc_gate(name, cli, pcb, report, extra=()):
    if report.exists():
        report.unlink()
    cmd = [cli, "pcb", "drc", "--format", "json", "--severity-all",
           "--schematic-parity", "--exit-code-violations", *extra, "-o", report, pcb]
    proc = run(cmd)
    if proc.returncode not in (0, 5) or not report.exists():
        return result(name, "tool-error", (proc.stderr or proc.stdout).strip()[:500])
    data = json.loads(report.read_text(encoding="utf-8"))
    c = count_violations(data.get("violations", []))
    unconnected = len(data.get("unconnected_items") or [])
    parity = len(data.get("schematic_parity") or [])
    ok = c["error"] == 0 and unconnected == 0 and parity == 0
    return result(name, "pass" if ok else "FAIL",
                  f"{c['error']} errors, {c['warning']} warnings, "
                  f"{unconnected} unconnected, {parity} parity")


# -------------------------------------------------------------- compact detail
def _walk(node, out):
    """Collect violation dicts (same test as count_violations) from a kicad-cli report."""
    if isinstance(node, dict):
        if node.get("severity") in ("error", "warning") and ("description" in node or "type" in node):
            out.append(node)
        for value in node.values():
            _walk(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk(item, out)


def _instance(v):
    """One line: item descriptions, cut to 140 chars, plus the first position the JSON gives."""
    items = v.get("items") or []
    text = " | ".join(str(i.get("description", "")).strip() for i in items if i.get("description"))
    text = " ".join((text or str(v.get("description", ""))).split())
    if len(text) > 140:
        text = text[:137] + "..."
    pos = next((i["pos"] for i in items if isinstance(i.get("pos"), dict)), None)
    if pos is not None:
        text += f" @({pos.get('x', 0):.2f},{pos.get('y', 0):.2f})"
    return text


def report_entries(path, is_drc):
    """(errors, warnings): lists of violation dicts. For DRC, unconnected and parity items count as errors."""
    data = json.loads(path.read_text(encoding="utf-8"))
    found = []
    _walk(data.get("violations", []) if is_drc else data, found)
    errors = [v for v in found if v["severity"] == "error"]
    warnings = [v for v in found if v["severity"] == "warning"]
    if is_drc:
        for key in ("unconnected_items", "schematic_parity"):
            for v in data.get(key) or []:
                errors.append(dict(v, type=v.get("type") or key))
    return errors, warnings


def compact_detail(reports, specs):
    """specs: [(label, report file name, is_drc)]. Returns lines for the console and gates.md."""
    warn_lines, err_lines = [], []
    for label, fname, is_drc in specs:
        path = reports / fname
        if not path.exists():
            continue
        try:
            errors, warnings = report_entries(path, is_drc)
        except (OSError, ValueError):
            continue
        counts = {}
        for v in warnings:
            counts[v.get("type", "?")] = counts.get(v.get("type", "?"), 0) + 1
        warn_lines.append(f"{label} warnings: " + (", ".join(f"{t} x{n}" for t, n in sorted(counts.items()))
                                                   or "none"))
        if errors:
            err_lines += ["", f"### {label}"]
            groups = {}
            for v in errors:
                groups.setdefault(v.get("type", "?"), []).append(v)
            for t, vs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                err_lines.append(f"{t} x{len(vs)}")
                err_lines += ["  " + _instance(v) for v in vs[:5]]
                if len(vs) > 5:
                    err_lines.append(f"  +{len(vs) - 5} more in reports/{fname}")
    lines = []
    if err_lines:
        lines += ["", "## Errors"] + err_lines
    if warn_lines:
        lines += [""] + warn_lines
    return lines


# -------------------------------------------------------------------- export
def copy_project(project, dest):
    """Copy the project for the refill check: root files and every folder that may hold
    libraries (lib/, *.pretty, *.3dshapes ...). Output, history and tool folders are left out."""
    skip = {"fab", "reports", "datasheets", "scripts", "__pycache__"}
    for item in project.iterdir():
        if item.is_file():
            if not item.name.endswith((".lck", ".kicad_prl")):
                shutil.copy2(item, dest / item.name)
        elif item.is_dir() and not item.name.startswith(".") and item.name not in skip \
                and not item.name.endswith("-backups"):
            shutil.copytree(item, dest / item.name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.lck"))


def copper_layers(pcb):
    text = pcb.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"\(layers\b(.*?)\n\t\)", text, re.S)
    block = m.group(1) if m else text[:20000]
    names = re.findall(r'\(\d+\s+"([^"]+\.Cu)"\s+(?:signal|power|mixed|jumper)', block)
    order = ["F.Cu"] + sorted((n for n in names if n.startswith("In")),
                              key=lambda n: int(re.match(r"In(\d+)", n).group(1))) + ["B.Cu"]
    return [n for n in order if n in names] or ["F.Cu", "B.Cu"]


def export_all(cli, project, stem, sch, pcb_orig, reports):
    """Refill-zone DRC on a temp copy, then export fab files from that copy."""
    results = []
    fab = project / "fab"
    with tempfile.TemporaryDirectory(prefix="pcb-gates-") as tmp:
        tmpd = Path(tmp)
        copy_project(project, tmpd)
        pcb = tmpd / pcb_orig.name
        refill = drc_gate("DRC after zone refill", cli, pcb, reports / "drc-refill.json",
                          ["--refill-zones", "--save-board"])
        results.append(refill)
        if refill["status"] != "pass":
            return results
        gdir = fab / "gerbers"
        gdir.mkdir(parents=True, exist_ok=True)
        for f in gdir.iterdir():
            if f.is_file():
                f.unlink()
        layers = copper_layers(pcb) + ["F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen",
                                       "F.Mask", "B.Mask", "Edge.Cuts"]
        pos = fab / f"{stem}-pos.csv"
        bom = fab / f"{stem}-bom.csv"
        pdf = fab / f"{stem}-schematic.pdf"
        zpath = fab / f"{stem}-gerbers.zip"
        steps = [
            ("Gerbers", [cli, "pcb", "export", "gerbers", "-o", gdir, "--layers",
                         ",".join(layers), pcb], gdir),
            ("Drill", [cli, "pcb", "export", "drill", "-o", gdir, "--format", "excellon",
                       "--excellon-units", "mm", "--generate-map", "--map-format", "pdf",
                       pcb], gdir),
        ]
        for label, cmd, out in steps:
            proc = run(cmd)
            n = len([f for f in out.iterdir() if f.is_file()])
            if proc.returncode != 0 or n == 0:
                results.append(result(label, "tool-error",
                                      (proc.stderr or proc.stdout).strip()[:300]))
                return results
            results.append(result(label, "pass", f"{n} files in fab/gerbers"))
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(gdir.iterdir()):
                if f.is_file():
                    z.write(f, f.name)
        results.append(result("Gerber zip", "pass", f"{zpath.name}, {zpath.stat().st_size} bytes"))
        later = [
            ("Placement", [cli, "pcb", "export", "pos", "--format", "csv", "--units", "mm",
                           "--side", "both", "--exclude-dnp", "-o", pos, pcb], pos),
            ("BOM", [cli, "sch", "export", "bom", "--fields",
                     "Reference,Value,Footprint,${QUANTITY},MPN,LCSC",
                     "--labels", "Reference,Value,Footprint,Quantity,MPN,LCSC",
                     "--group-by", "Value,Footprint,MPN", "--exclude-dnp",
                     "--ref-range-delimiter", "",   # assemblers reject ranges such as R1-R8
                     "-o", bom, sch], bom),
            ("Schematic PDF", [cli, "sch", "export", "pdf", "-o", pdf, sch], pdf),
        ]
        for label, cmd, out in later:
            proc = run(cmd)
            if proc.returncode != 0 or not out.exists():
                results.append(result(label, "tool-error",
                                      (proc.stderr or proc.stdout).strip()[:300]))
                return results
            results.append(result(label, "pass", f"{out.name}, {out.stat().st_size} bytes"))
        jlc = jlc_assembly_files(fab, stem, bom, pos)
        results.append(jlc[0])
        mine = {pos.name, bom.name, pdf.name, zpath.name} | jlc[1]
        other = sorted(f.name + ("/" if f.is_dir() else "") for f in fab.iterdir()
                       if f.name not in mine and f.name != "gerbers")
        results.append(result("Other files in fab/", "note",
                              "none" if not other else
                              "NOT written by this run, may be stale: " + ", ".join(other)))
    return results


def jlc_assembly_files(fab, stem, bom, pos):
    """Write the BOM and placement list with the column names JLCPCB's assembly upload asks for.
    Values are copied from the KiCad exports unchanged: rotations are KiCad's, and JLCPCB's
    library can expect a different zero angle for some packages. Returns (result row, file names)."""
    import csv
    jbom, jcpl = fab / f"{stem}-jlc-bom.csv", fab / f"{stem}-jlc-cpl.csv"
    try:
        with open(bom, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        with open(pos, newline="", encoding="utf-8") as f:
            prow = list(csv.DictReader(f))
        no_num = 0
        with open(jbom, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
            for r in rows:
                num = (r.get("LCSC") or "").strip()
                if not re.fullmatch(r"C\d+", num):
                    num, no_num = "", no_num + 1
                w.writerow([r.get("Value", ""), r.get("Reference", ""),
                            (r.get("Footprint", "") or "").split(":")[-1], num])
        with open(jcpl, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
            for r in prow:
                side = "Bottom" if (r.get("Side", "").lower().startswith("b")) else "Top"
                w.writerow([r.get("Ref", ""), r.get("PosX", ""), r.get("PosY", ""), side, r.get("Rot", "")])
    except (OSError, csv.Error, KeyError) as exc:
        return result("JLCPCB assembly files", "tool-error", str(exc)[:200]), set()
    return (result("JLCPCB assembly files", "note",
                   f"{jbom.name} ({len(rows)} lines, {no_num} without an LCSC number), {jcpl.name} "
                   f"({len(prow)} parts). Rotations are KiCad's, unchanged: check every polarised and "
                   f"multi-pin part in JLCPCB's placement preview before confirming"),
            {jbom.name, jcpl.name})


def fab_up_to_date(project):
    """Fail when any file in fab/ is older than the newest board or schematic file: the factory
    files would not match the design. Only those two are compared: the factory files are made from
    them, and KiCad rewrites the .kicad_pro just from opening the project."""
    name = "Fab files up to date"
    fab = project / "fab"
    skip = {"fab", "reports", "scripts", ".git", ".boardwright", ".history"}
    try:
        fab_files = [] if not fab.is_dir() else [
            (f.stat().st_mtime, f) for f in fab.rglob("*")
            if f.is_file() and not f.name.startswith(".")]
        if not fab_files:
            return result(name, "note", "no fab files yet")
        design = []
        for root, dirs, files in os.walk(project):
            dirs[:] = [d for d in dirs if d not in skip and not d.endswith("-backups")]
            for fn in files:
                if fn.endswith((".kicad_sch", ".kicad_pcb")):
                    p = Path(root) / fn
                    design.append((p.stat().st_mtime, p))
    except OSError as exc:
        return result(name, "tool-error", f"cannot read file times: {exc}"[:200])
    if not design:
        return result(name, "note", "no design files found")
    newest_t, newest = max(design, key=lambda x: x[0])
    older = [(t, f) for t, f in fab_files if t < newest_t]
    if older:
        oldest = min(older, key=lambda x: x[0])[1]
        return result(name, "FAIL",
                      f"{len(older)} of {len(fab_files)} fab files are older than the design. "
                      f"Oldest: {oldest.relative_to(project).as_posix()}. "
                      f"Newer design file: {newest.relative_to(project).as_posix()}. "
                      f"Run python scripts/run_gates.py . again to make fresh files")
    return result(name, "pass", f"{len(fab_files)} fab files are newer than the newest design file "
                                f"({newest.relative_to(project).as_posix()})")


def class_sizes(pcb):
    """A note, not a failure: copper smaller than its own net class asks for (KiCad's DRC checks only the
    board's minimums, so a 0.3 mm track on a 0.4 mm power class passes it)."""
    import kicad_python
    kpy = kicad_python.find()
    if not kpy:
        return result("Net class sizes", "not run", "KiCad's Python not found")
    fd, name = tempfile.mkstemp(suffix=".json")
    os.close(fd)                                    # Windows cannot delete a file still open
    req = Path(name)
    # vias in pads are the designer's choice unless the project says otherwise (boardwright.json
    # "engine": {"via_in_pad": false}); then each one is listed
    try:
        cfg = json.loads((Path(pcb).parent / "boardwright.json").read_text("utf-8"))
    except (OSError, ValueError):
        cfg = {}
    vip_ok = (cfg.get("engine") or {}).get("via_in_pad") is not False
    req.write_text(json.dumps({"nets": ["*"], "planes": {}, "via_in_pad_ok": vip_ok}), "utf-8")
    r = subprocess.run([kpy, "-I", str(Path(__file__).resolve().parent / "engine_kicad.py"), "audit", str(pcb),
                        str(req)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    req.unlink()
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if not lines:
        return result("Net class sizes", "not run", (r.stderr or r.stdout).strip()[-200:])
    bad = json.loads(lines[-1])
    if not bad:
        return result("Net class sizes", "pass", "every track and via meets its net class")
    return result("Net class sizes", "note", f"{len(bad)} net(s) below their class or with a via in a pad: " +
                  "; ".join(f"{n} {w}" for n, w in list(bad.items())[:6]))


def write_reports(project, cli, results, detail=()):
    reports = project / "reports"
    lines = ["# Gate results", "", "| Gate | Status | Detail |", "| --- | --- | --- |"]
    for r in results:
        lines.append(f"| {r['name']} | {r['status']} | {r['detail']} |")
    lines += list(detail)
    lines += ["", "Power budget, EMC, SI and BOM-stock gates are run by Claude; "
                  "see the boardwright skill."]
    (reports / "gates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    passed = all(r["status"] in ("pass", "note", "not run") for r in results)
    ver = ""
    if cli:
        try:
            ver = subprocess.run([cli, "version"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
        except OSError:
            pass
    (reports / "gates.json").write_text(json.dumps({
        "project": project.name,
        "kicad_cli_version": ver,
        "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "results": results,
        "passed": passed,
    }, indent=2) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return passed


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sch_only = "--sch-only" in sys.argv
    export = "--no-export" not in sys.argv and not sch_only
    project = Path(args[0]).resolve() if args else Path.cwd().resolve()
    cli = find_kicad_cli()
    if not cli:
        print("kicad-cli not found. Install KiCad or set KICAD_CLI to its full path.")
        return 2
    print(f"kicad-cli: {cli}")
    sch = sorted(project.glob("*.kicad_sch"))
    pcb = sorted(project.glob("*.kicad_pcb"))
    if not sch or (not pcb and not sch_only):
        print(f"No .kicad_sch / .kicad_pcb found in {project}" + (" (--sch-only needs only the schematic)" if not sch else ""))
        return 2
    pro = sorted(project.glob("*.kicad_pro"))
    pcb = pcb[0] if pcb else None
    stem = pcb.stem if pcb else (pro[0].stem if pro else sch[0].stem)
    # The root sheet has the project name; sub-sheets may sort before it.
    root = project / f"{stem}.kicad_sch"
    sch = root if root.exists() else sch[0]
    reports = project / "reports"
    reports.mkdir(exist_ok=True)

    print("Gate 1: Rule guard")
    results = [rule_guard(project, stem)]
    print("Gate 2: ERC")
    results.append(erc_gate(cli, sch, reports))
    if sch_only:
        results.append(result("DRC", "not run", "schematic stage (--sch-only); required from stage 5 on"))
    else:
        print("Gate 3: DRC (with schematic parity)")
        results.append(drc_gate("DRC", cli, pcb, reports / "drc.json"))
        results.append(class_sizes(pcb))

    if export and all(r["status"] in ("pass", "note", "not run") for r in results):
        print("Exports: refill check, Gerbers, drill, placement, BOM, schematic PDF")
        results += export_all(cli, project, stem, sch, pcb, reports)
    if not sch_only:              # after the export, so a fresh export passes
        results.append(fab_up_to_date(project))

    specs = [("ERC", "erc.json", False)] + ([] if sch_only else [("DRC", "drc.json", True)])
    if any(r["name"] == "DRC after zone refill" for r in results):
        specs.append(("DRC after zone refill", "drc-refill.json", True))
    write_reports(project, cli, results, compact_detail(reports, specs))
    if any(r["status"] == "tool-error" for r in results):
        return 2
    return 0 if all(r["status"] in ("pass", "note", "not run") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
