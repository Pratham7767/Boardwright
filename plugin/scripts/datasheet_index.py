# /// script
# requires-python = ">=3.9"
# dependencies = ["pypdf", "cryptography"]
# ///
"""datasheet_index.py - find the few datasheet pages that matter and write them as plain text.

Run:  uv run --with pypdf python plugin/scripts/datasheet_index.py <project_dir> [name-or-MPN ...] [--all]
                                                                   [--pages N-M[,N,...]] [--force]
  (or:  uv run plugin/scripts/datasheet_index.py <project_dir> ...   - the inline metadata above pulls pypdf)

For every selected PDF in <project_dir>/datasheets/ it writes, into <project_dir>/datasheets/.index/ :
  <stem>.index.txt    one line per page: number, detected sections, characters, first line;
                      then "sections:" (section -> pages) and the pages with little or no text.
  <stem>.extract.txt  text of the pages classified pins / absmax / recommended / package / ordering.
With --pages the named pages are printed to stdout instead (follow-up reads); nothing is written.

PAGE NUMBERS ARE 1-BASED PDF PAGE INDICES (the n-th page of the file), NOT the number printed on the page.

How pages are scored (simple on purpose):
  * A line is "heading-like" when it is short (<= 90 chars) and STARTS with a section phrase
    (leading numbering such as "6.2" or "7)" is ignored).
  * heading-like line among the first 6 non-empty lines of the page : +10
  * heading-like line lower on the page                              : +5
  * phrase mentioned inside a longer line (body text)                : +1 each, at most +2
  * A section is assigned to a page when its score is >= 5, so body mentions alone never qualify.
  * Table-of-contents / list pages (dotted leaders, many lines ending in page numbers) score 0.
  * Lines repeated on more than 40% of the pages (running headers) are ignored.
Selection for the extract: best pages per section (pins 3, absmax 2, recommended 2, package 3,
ordering 2), at most 12 pages in total; the pages left out are named at the end of the extract.
Exit codes: 0 normal, 2 setup problem (no datasheets folder, no match, pypdf missing).
"""
import json
import logging
import re
import sys
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "pypdf is not installed. Run this script with:\n"
        "  uv run --with pypdf python plugin/scripts/datasheet_index.py <project_dir> [names] [--all]\n")
    sys.exit(2)

logging.getLogger("pypdf").setLevel(logging.CRITICAL)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SECTIONS = ["pins", "absmax", "recommended", "electrical", "package", "ordering", "application"]
EXTRACT_SECTIONS = ["pins", "absmax", "recommended", "package", "ordering"]
PER_SECTION_CAP = {"pins": 3, "absmax": 2, "recommended": 2, "package": 3, "ordering": 2}
MAX_EXTRACT_PAGES = 12
MIN_SCORE = 5
TOP_LINES = 6
HEAD_TOP, HEAD_LOW, BODY_HIT, BODY_CAP = 10, 5, 1, 2
LOW_TEXT_CHARS = 100

# Phrases (lowercase, regex). A line is heading-like if it starts with one of them.
PHRASES = {
    "pins": [r"pin configurations?", r"pin descriptions?", r"pin functions?", r"pin assignments?",
             r"pin out", r"pinouts?", r"pin definitions?", r"pin connections?", r"pin names?",
             r"terminal assignments?", r"terminal functions?", r"terminal configurations?",
             r"connection diagrams?", r"pin layout", r"pin list", r"pin table",
             ],
    "absmax": [r"absolute maximum ratings?", r"absolute maximum", r"maximum ratings?",
               r"stress ratings?", r"limiting values", r"absolute max"],
    "recommended": [r"recommended operating conditions?", r"recommended operating ranges?",
                    r"recommended operating", r"operating ratings?", r"operating conditions?"],
    "electrical": [r"electrical characteristics?", r"electrical specifications?",
                   r"electrical parameters?", r"dc characteristics", r"ac characteristics",
                   r"characteristics"],
    "package": [r"package outlines?", r"package dimen\w*", r"package information",
                r"package drawings?", r"mechanical data", r"mechanical drawings?",
                r"mechanical information", r"outline dimensions?", r"outline drawings?",
                r"physical dimensions?", r"dimensions", r"land patterns?",
                r"recommended footprints?", r"recommended land", r"recommended pad",
                r"recommended solder", r"soldering footprints?", r"solder pad",
                r"footprints?", r"pcb layout", r"example board layout", r"example stencil", r"board layout", r"packaging information", r"package details?"],
    "ordering": [r"ordering information", r"ordering codes?", r"order information",
                 r"device marking", r"package marking", r"marking information", r"marking code",
                 r"part numbering", r"part number system", r"type designation", r"how to order",
                 r"orderable"],
    "application": [r"typical applications?", r"application circuits?", r"applications? information",
                    r"reference designs?", r"layout guidelines?", r"layout recommendations?",
                    r"layout example", r"design examples?", r"typical circuit"],
}
# weak pin cues (pinout drawings): +3 per short line, at most +6, only when the page has no package heading
WEAK_PINS = [re.compile(r"\(?(?:top|bottom) view\)?"), re.compile(r"pin\s*\d+[.:]?\s*[a-z/]{0,12}$")]


def _tol(p):
    # some PDFs (e.g. Infineon) lose the spaces between words: a space in a phrase matches zero or more blanks
    return p.replace(" ", r"\s*")


COMPILED = {s: [re.compile(_tol(p)) for p in ps] for s, ps in PHRASES.items()}
BODY_RX = {s: re.compile(r"\b(?:" + "|".join(_tol(p) for p in ps) + r")\b") for s, ps in PHRASES.items()}
NUMBERING = re.compile(r"^\s*(?:(?:section|table)\s*)?(?:\d{1,2}(?:\.\d{1,2}){0,3}|[a-z]\.|\(?\d{1,2}\))[\s.):-]*(?=[a-z])")
LEADER = re.compile(r"(?:\.{4,}|(?:\. ){4,}|…{2,})")
ENDS_NUM = re.compile(r"\S\s{1,}\d{1,3}\s*$")


def norm_line(s):
    return re.sub(r"\s+", " ", s).strip()


def mask(s):
    """lower-case line with digits masked: 'Rev 2.5 ... 7' and 'Rev 2.5 ... 8' are the same running header"""
    return re.sub(r"\d", "#", norm_line(s).lower())


def heading_like(low, head, rx):
    m = rx.match(head)
    if not m:
        return False
    if len(low) <= 90:
        return True
    return head[m.end():].lstrip()[:1] in ("(", ":", "[")  # "MAXIMUM RATINGS (Tamb = 25 C ...)" is a heading too


def clean_text(text):
    # control characters act as blanks in some PDFs (Infineon)
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text.replace("\r", ""))
    lines = [ln.rstrip() for ln in text.split("\n")]
    out, blank = [], 0
    for ln in lines:
        if ln.strip() == "":
            blank += 1
            if blank == 1:
                out.append("")
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out).strip("\n")


def is_toc(lines):
    leaders = sum(1 for l in lines if LEADER.search(l))
    if leaders >= 4:
        return True
    ends = sum(1 for l in lines if ENDS_NUM.search(l) and len(l) < 90)
    heads = sum(1 for s in SECTIONS
                if any(any(rx.match(norm_line(l).lower()) for rx in COMPILED[s]) for l in lines))
    return ends >= 12 and heads >= 3 and ends > 0.5 * max(1, len(lines))


def score_page(lines, ignore):
    """Return ({section: score}, toc_flag). lines = non-empty stripped lines."""
    if is_toc(lines):
        return {}, True
    scores = {s: 0 for s in SECTIONS}
    body_hits = {s: 0 for s in SECTIONS}
    for idx, raw in enumerate(lines):
        low = norm_line(raw).lower()
        if not low or mask(low) in ignore:
            continue
        head = NUMBERING.sub("", low)
        for s in SECTIONS:
            matched_head = any(heading_like(low, head, rx) for rx in COMPILED[s])
            if matched_head:
                scores[s] += HEAD_TOP if idx < TOP_LINES else HEAD_LOW
            elif BODY_RX[s].search(low):
                body_hits[s] += 1
    for s in SECTIONS:
        scores[s] += min(body_hits[s], BODY_CAP) * BODY_HIT
    if scores["pins"] < MIN_SCORE and scores["package"] < MIN_SCORE:
        weak = sum(1 for l in lines if len(l) <= 60 and any(rx.match(norm_line(l).lower()) for rx in WEAK_PINS))
        scores["pins"] += min(3 * weak, 6)
    return scores, False


def read_pages(path):
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
    texts = []
    for i in range(len(reader.pages)):
        try:
            t = reader.pages[i].extract_text() or ""
        except Exception:
            t = ""
        texts.append(t)
    return texts


def parse_pages(spec, total):
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            pages.extend(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            pages.append(int(part))
        else:
            raise ValueError("bad --pages value: " + part)
    return [p for p in dict.fromkeys(pages) if 1 <= p <= total]


def analyse(texts):
    n = len(texts)
    cleaned = [clean_text(t) for t in texts]
    page_lines = [[l.strip() for l in c.split("\n") if l.strip()] for c in cleaned]
    # running headers/footers: identical normalised line on > 40% of pages
    ignore = set()
    if n >= 6:
        counts = {}
        for lines in page_lines:
            for l in {mask(x) for x in lines}:
                counts[l] = counts.get(l, 0) + 1
        ignore = {l for l, c in counts.items() if c > 0.4 * n}
    pages = []
    for i, lines in enumerate(page_lines):
        scores, toc = score_page(lines, ignore)
        secs = {s: sc for s, sc in scores.items() if sc >= MIN_SCORE}
        first = ""
        for l in lines:
            if mask(l) not in ignore and len(re.sub(r"[\W\d_]", "", l)) >= 3:
                first = norm_line(l)
                break
        pages.append({"n": i + 1, "chars": len(cleaned[i]), "toc": toc, "secs": secs,
                      "first": first[:80], "text": cleaned[i]})
    return pages


def select_extract(pages):
    chosen = {}
    for s in EXTRACT_SECTIONS:
        ranked = sorted((p for p in pages if s in p["secs"]), key=lambda p: (-p["secs"][s], p["n"]))
        for rank, p in enumerate(ranked[:PER_SECTION_CAP[s]]):
            # the best page of every section gets +1000 so it survives the total cap
            pri = (1000 if rank == 0 else 0) + p["secs"][s]
            chosen[p["n"]] = max(chosen.get(p["n"], 0), pri)
    ranked_pages = sorted(chosen, key=lambda n: (-chosen[n], n))
    keep = sorted(ranked_pages[:MAX_EXTRACT_PAGES])
    left_out = sorted(ranked_pages[MAX_EXTRACT_PAGES:])
    return keep, left_out


def index_one(pdf, outdir):
    texts = read_pages(pdf)
    pages = analyse(texts)
    n = len(pages)
    doc_chars = sum(p["chars"] for p in pages)
    keep, left_out = select_extract(pages)
    secmap = {s: [p["n"] for p in pages if s in p["secs"]] for s in SECTIONS}
    lowtext = [p["n"] for p in pages if p["chars"] < LOW_TEXT_CHARS]

    idx = ["# %s - %d pages. PAGE NUMBERS ARE 1-BASED PDF PAGE INDICES (n-th page of the file), "
           "not the numbers printed on the pages." % (pdf.name, n),
           "# page | sections | chars | first line"]
    for p in pages:
        sec = ",".join(s for s in SECTIONS if s in p["secs"]) or "-"
        if p["toc"] and sec == "-":
            sec = "- (contents/list page)"
        idx.append("%d | %s | %d | %s" % (p["n"], sec, p["chars"], p["first"]))
    idx.append("")
    idx.append("sections:")
    for s in SECTIONS:
        idx.append("  %s: %s" % (s, ", ".join(map(str, secmap[s])) if secmap[s] else "not detected"))
    idx.append("")
    idx.append("pages with little or no text (scan or drawing): " +
               (", ".join(map(str, lowtext)) if lowtext else "none"))

    ext = ["# %s - extract of selected pages. PAGE NUMBERS ARE 1-BASED PDF PAGE INDICES." % pdf.name]
    for pn in keep:
        p = pages[pn - 1]
        tags = ",".join(s for s in SECTIONS if s in p["secs"] and s in EXTRACT_SECTIONS)
        ext.append("=== %s page %d [%s] ===" % (pdf.name, pn, tags))
        ext.append(p["text"] if p["text"] else "(no extractable text on this page)")
        ext.append("")
    if left_out:
        ext.append("# pages classified but left out by the %d-page cap: %s" %
                   (MAX_EXTRACT_PAGES, ", ".join(map(str, left_out))))
    else:
        ext.append("# no classified pages left out by the cap")
    ext_chars = sum(len(pages[pn - 1]["text"]) for pn in keep)

    summary = {"pages": n,
               "keep": [[pn, [s for s in EXTRACT_SECTIONS if s in pages[pn - 1]["secs"]]] for pn in keep],
               "ext_chars": ext_chars, "doc_chars": doc_chars, "lowtext": len(lowtext),
               "found": {s: bool(secmap[s]) for s in SECTIONS}, "left_out": left_out}
    idx.append("")
    idx.append("# summary: " + json.dumps(summary))
    (outdir / (pdf.stem + ".index.txt")).write_text("\n".join(idx) + "\n", encoding="utf-8")
    (outdir / (pdf.stem + ".extract.txt")).write_text("\n".join(ext) + "\n", encoding="utf-8")
    return summary


def load_cached(pdf, outdir):
    ip, ep = outdir / (pdf.stem + ".index.txt"), outdir / (pdf.stem + ".extract.txt")
    if not (ip.exists() and ep.exists()):
        return None
    m = pdf.stat().st_mtime
    if ip.stat().st_mtime <= m or ep.stat().st_mtime <= m:
        return None
    try:
        last = [l for l in ip.read_text(encoding="utf-8").splitlines() if l.startswith("# summary: ")][-1]
        return json.loads(last[len("# summary: "):])
    except Exception:
        return None


def describe(pdf, s, cached):
    n = s["pages"]
    parts = " ".join("p%d[%s]" % (pn, "+".join(secs)) for pn, secs in s["keep"]) or "none"
    ratio = (100.0 * s["ext_chars"] / s["doc_chars"]) if s["doc_chars"] else 0.0
    line = "%s | %dp | extracted: %s | %d of %d chars (%.1f%%)" % (
        pdf.name, n, parts, s["ext_chars"], s["doc_chars"], ratio)
    warn = []
    if n and s["lowtext"] > 0.5 * n:
        warn.append("scanned or image-only: the reader must open the PDF pages directly")
    else:
        miss = [k for k in ("pins", "absmax", "package") if not s["found"].get(k)]
        if miss:
            warn.append("not detected: " + ", ".join(miss) + " (see index.txt, or read the PDF pages directly)")
    if s["left_out"]:
        warn.append("left out by cap: " + ",".join(map(str, s["left_out"])))
    if cached:
        line += " [cached]"
    if warn:
        line += " | WARN: " + "; ".join(warn)
    return line


def main(argv):
    pages_spec = None
    force = False
    use_all = False
    rest = []
    it = iter(argv)
    for a in it:
        if a == "--pages":
            pages_spec = next(it, "")
        elif a.startswith("--pages="):
            pages_spec = a.split("=", 1)[1]
        elif a == "--all":
            use_all = True
        elif a == "--force":
            force = True
        elif a.startswith("--"):
            sys.stderr.write("unknown option %s\n" % a)
            return 2
        else:
            rest.append(a)
    if pages_spec is not None and not pages_spec:
        sys.stderr.write("--pages needs a value such as 3-5 or 2,7\n")
        return 2
    if not rest:
        sys.stderr.write("usage: datasheet_index.py <project_dir> [PDF name or MPN substring ...] "
                         "[--all] [--pages N-M] [--force]\n")
        return 2
    project = Path(rest[0])
    names = rest[1:]
    ds = project / "datasheets"
    if not ds.is_dir():
        sys.stderr.write("no datasheets folder: %s\n" % ds)
        return 2
    pdfs = sorted((f for f in ds.iterdir() if f.is_file() and f.suffix.lower() == ".pdf"),
                  key=lambda f: f.name.lower())
    if use_all:
        sel = pdfs
    elif names:
        sel = [f for f in pdfs if any(nm.lower() in f.name.lower() for nm in names)]
        for nm in names:
            if not any(nm.lower() in f.name.lower() for f in pdfs):
                sys.stderr.write("no PDF in %s matches '%s'\n" % (ds, nm))
    else:
        sys.stderr.write("give at least one PDF name / MPN substring, or --all\n")
        return 2
    if not sel:
        sys.stderr.write("no matching PDF in %s (%d PDFs present)\n" % (ds, len(pdfs)))
        return 2

    if pages_spec is not None:
        for pdf in sel:
            texts = read_pages(pdf)
            try:
                wanted = parse_pages(pages_spec, len(texts))
            except ValueError as e:
                sys.stderr.write(str(e) + "\n")
                return 2
            print("# %s - %d pages; PAGE NUMBERS ARE 1-BASED PDF PAGE INDICES" % (pdf.name, len(texts)))
            for pn in wanted:
                t = clean_text(texts[pn - 1])
                print("=== %s page %d ===" % (pdf.name, pn))
                print(t if t else "(no extractable text on this page)")
                print()
            if not wanted:
                print("(no page of %s is in range 1-%d)" % (pdf.name, len(texts)))
        return 0

    outdir = ds / ".index"
    outdir.mkdir(exist_ok=True)
    tot_ext = tot_doc = 0
    for pdf in sel:
        s = None if force else load_cached(pdf, outdir)
        cached = s is not None
        if s is None:
            try:
                s = index_one(pdf, outdir)
            except Exception as e:
                hint = ""
                if "cryptography" in str(e):
                    hint = (" (AES-encrypted PDF: rerun with `uv run --with pypdf --with cryptography python "
                            "plugin/scripts/datasheet_index.py ...`)")
                print("%s | ERROR reading PDF: %s%s | WARN: open the PDF pages directly" % (pdf.name, e, hint))
                continue
        tot_ext += s["ext_chars"]
        tot_doc += s["doc_chars"]
        print(describe(pdf, s, cached))
    if len(sel) > 1:
        print("TOTAL %d PDFs | extracts %d of %d chars (%.1f%%) | page numbers are 1-based PDF indices | files in %s"
              % (len(sel), tot_ext, tot_doc, 100.0 * tot_ext / tot_doc if tot_doc else 0.0, outdir))
    else:
        print("page numbers are 1-based PDF indices | files in %s" % outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
