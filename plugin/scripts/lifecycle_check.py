#!/usr/bin/env python3
"""Part lifecycle check: flags parts that LCSC lists as discontinued or not recommended.

Usage:  python scripts/lifecycle_check.py <project_dir> [--refresh] [--offline]

Parts come from fab/*-bom.csv when present (columns Reference, MPN, LCSC), else from the schematic
symbol fields (MPN and LCSC). Each unique LCSC number is looked up, one request at a time, at least
1 s apart, on LCSC's public product JSON (no key, no sign-in, nothing is sent but the C-number):

    https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=<LCSC number>

Fields read from result: productCycle, isNotOverstock, productModel.
LCSC's own product page script shows "Discontinued" when productCycle == "stop_product" and the part is
flagged isNotOverstock, and "Not recommended" for isNotOverstock with any other productCycle. Here:
    productCycle "stop_product"                          -> eol
    isNotOverstock true (other productCycle)             -> nrnd
    productCycle "normal" or "on_sale", not flagged      -> active
    anything else (no answer, not found, field missing,
    unknown productCycle value, C-number is another part) -> unverified
This is the distributor's listing status, not the manufacturer's lifecycle: "active" means "LCSC lists it
as normal". Only the value "normal" was seen live; "stop_product" comes from LCSC's page code.
Answers are cached in reports/lifecycle-cache.json (reused for 7 days; --refresh ignores the cache;
--offline uses only the cache). Writes reports/lifecycle.md/.json.
Exit: 0 no eol part (nrnd and unverified parts are listed for a person to check, not failed), 1 any eol part,
2 setup problem. nrnd rests on LCSC's isNotOverstock flag, read from its page code: confirm it by hand.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bw_project import SetupError, md_table, project_files, write_report  # noqa: E402

URL = "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={}"
USER_AGENT = "boardwright-lifecycle-check/1.0 (public product page lookup)"
CACHE_DAYS = 7
MIN_GAP_S = 1.1
TIMEOUT_S = 15
MPN_NAMES = ("mpn", "mfr part", "manufacturer_part_number", "manufacturer part number")
LCSC_NAMES = ("lcsc", "lcsc part", "lcsc part #", "lcsc part number", "lcsc#", "jlcpcb part #", "jlcpcb part")
LCSC_RE = re.compile(r"^C\d{2,}$")


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def extract(payload) -> dict:
    """The small part of LCSC's JSON that is kept (and cached)."""
    res = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(res, dict):
        return {"found": False}
    return {"found": True, "model": res.get("productModel"), "productCycle": res.get("productCycle"),
            "isNotOverstock": res.get("isNotOverstock")}


def classify(ans: dict | None, mpn: str = "") -> tuple:
    """(status, the source's words) from an extracted answer. Pure function: no network."""
    if not ans:
        return "unverified", "no answer"
    if ans.get("error"):
        return "unverified", f"no answer: {ans['error']}"
    if not ans.get("found"):
        return "unverified", "LCSC returned no product for this number"
    cyc, nos, model = ans.get("productCycle"), ans.get("isNotOverstock"), ans.get("model") or ""
    words = f"productCycle={cyc!r}, isNotOverstock={nos!r}"
    if mpn and model:
        a, b = _norm(mpn), _norm(model)
        if a and b and not (a.startswith(b) or b.startswith(a)):
            return "unverified", f"LCSC number belongs to '{model}', not '{mpn}' ({words})"
    if cyc is None or nos is None:
        return "unverified", f"field missing ({words})"
    if cyc == "stop_product":
        return "eol", words + " (LCSC page shows: discontinued)"
    if nos is True:
        return "nrnd", words + " (LCSC page shows: not recommended)"
    if cyc in ("normal", "on_sale") and nos is False:
        return "active", words
    return "unverified", f"unknown productCycle value ({words})"


def fetch(lcsc: str) -> dict:
    req = urllib.request.Request(URL.format(urllib.parse.quote(lcsc)),
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            payload = json.loads(r.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return extract(payload)


def read_bom(path: Path) -> list:
    out = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            low = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            out.append({"refs": low.get("reference", ""), "mpn": next((low[n] for n in MPN_NAMES if low.get(n)), ""),
                        "lcsc": next((low[n] for n in LCSC_NAMES if low.get(n)), "")})
    return out


def read_schematic(project: Path, sch: Path) -> list:
    from run_gates import find_kicad_cli
    from sch_check import export_netlist, parse_netlist
    cli = find_kicad_cli()
    if not cli or not sch.is_file():
        raise SetupError("no fab/*-bom.csv, and kicad-cli or the schematic is missing")
    comps, _l, _n = parse_netlist(export_netlist(cli, sch)[0])
    out = []
    for c in comps:
        if c["skip"] or c["ref"].startswith("#"):
            continue
        f = c["fields"]
        out.append({"refs": c["ref"], "mpn": next((f[n] for n in MPN_NAMES if f.get(n)), ""),
                    "lcsc": next((f[n] for n in LCSC_NAMES if f.get(n)), "")})
    return out


def group(rows: list) -> list:
    """Unique parts by (LCSC number, MPN); references merged."""
    seen: dict = {}
    for r in rows:
        key = (r["lcsc"].upper(), r["mpn"].upper())
        if not key[0] and not key[1]:
            continue
        g = seen.setdefault(key, {"refs": [], "mpn": r["mpn"], "lcsc": r["lcsc"]})
        g["refs"] += [x.strip() for x in r["refs"].split(",") if x.strip()]
    return list(seen.values())


def hand_links(p: dict) -> list:
    links = []
    if LCSC_RE.match(p["lcsc"]):
        links += [f"https://www.lcsc.com/product-detail/{p['lcsc']}.html", f"https://jlcpcb.com/partdetail/{p['lcsc']}"]
    if p["mpn"]:
        links.append("https://www.lcsc.com/search?q=" + urllib.parse.quote(p["mpn"]))
    return links


def load_cache(path: Path) -> dict:
    try:
        d = json.loads(path.read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def run(parts: list, cache: dict, today: date, refresh: bool = False, offline: bool = False,
        fetcher=fetch, sleep=time.sleep) -> list:
    """One row per part. Mutates cache. fetcher/sleep are injectable for tests."""
    rows, last = [], 0.0
    for p in parts:
        row = {"refs": p["refs"], "mpn": p["mpn"] or "unverified", "lcsc": p["lcsc"] or "unverified",
               "url": "", "date": "", "links": hand_links(p)}
        if not LCSC_RE.match(p["lcsc"]):
            row.update(status="unverified", words="no LCSC number on the part (the key-free source is looked up by LCSC number)")
            rows.append(row)
            continue
        key = p["lcsc"].upper()
        row["url"] = URL.format(key)
        hit = cache.get(key)
        age = None
        if hit:
            try:
                age = (today - datetime.strptime(hit["date"], "%Y-%m-%d").date()).days
            except (KeyError, ValueError):
                hit = None
        if hit and ((not refresh and age is not None and age < CACHE_DAYS) or offline):
            ans, row["date"] = hit["answer"], hit["date"]
            row["cached"] = True
        elif offline:
            ans, row["cached"] = {"error": "offline and not in the cache"}, False
            row["date"] = today.isoformat()
        else:
            wait = MIN_GAP_S - (time.monotonic() - last)
            if last and wait > 0:
                sleep(wait)
            ans = fetcher(key)
            last = time.monotonic()
            row["date"], row["cached"] = today.isoformat(), False
            if not ans.get("error"):
                cache[key] = {"date": row["date"], "answer": ans}
        row["status"], row["words"] = classify(ans, p["mpn"])
        rows.append(row)
    return rows


def exit_code(rows: list) -> int:
    """Only a discontinued part fails. "nrnd" comes from LCSC's isNotOverstock flag, whose meaning is
    read from LCSC's page code and not confirmed in words: it is listed for a person to check."""
    return 1 if any(r["status"] == "eol" for r in rows) else 0


def main(argv: list) -> int:
    args = [a for a in argv if not a.startswith("--")]
    refresh, offline = "--refresh" in argv, "--offline" in argv
    project = Path(args[0]).resolve() if args else Path.cwd()
    try:
        f = project_files(project)
        boms = sorted((project / "fab").glob("*-bom.csv"))
        parts = group(read_bom(boms[0]) if boms else read_schematic(project, f["sch"]))
        if not parts:
            raise SetupError("no parts with an MPN or LCSC number found")
    except (SetupError, Exception) as exc:
        print(f"lifecycle_check: setup problem: {exc}")
        return 2
    cache_path = project / "reports" / "lifecycle-cache.json"
    cache = load_cache(cache_path)
    rows = run(parts, cache, date.today(), refresh, offline)
    if not offline:
        cache_path.parent.mkdir(exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1) + "\n", "utf-8")
    bad = [r for r in rows if r["status"] in ("eol", "nrnd")]
    unv = [r for r in rows if r["status"] == "unverified"]
    table = [[", ".join(r["refs"]), r["mpn"], r["lcsc"], r["status"], r["words"], r["url"] or "-", r["date"] or "-"]
             for r in rows]
    head = ["refs", "MPN", "LCSC", "status", "source's words", "URL checked", "date"]
    md = ["# Part lifecycle (lifecycle_check.py)", "",
          "Source: LCSC public product JSON (no key). It is the distributor's listing status, not the manufacturer's "
          "lifecycle: confirm any eol/nrnd part, and any part you care about, on the manufacturer's page.", ""]
    md += md_table(head, table) + [""]
    if bad:
        md.append(f"- {len(bad)} part(s) eol or nrnd: " + ", ".join(f"{r['mpn']} ({r['status']})" for r in bad))
    if unv:
        md += ["", "## Unverified: check by hand", ""]
        md += [f"- {', '.join(r['refs'])} {r['mpn']}: {r['words']}. " + " ; ".join(r["links"]) for r in unv]
    write_report(project, "lifecycle", {"rows": rows, "eol_or_nrnd": len(bad), "unverified": len(unv),
                                        "pass": not bad, "errors": len(bad)}, md)
    w = [max(len(str(c)) for c in col) for col in zip(head[:4], *[t[:4] for t in table])]
    for t in [head[:4]] + [t[:4] for t in table]:
        print("  ".join(str(c).ljust(n) for c, n in zip(t, w)))
    print(f"Lifecycle: {len(rows)} part(s), {len(bad)} eol/nrnd, {len(unv)} unverified (details: reports/lifecycle.md)")
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
