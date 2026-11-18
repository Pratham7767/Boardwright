#!/usr/bin/env python3
"""Tests for scripts/history.py: python plugin/tests/test_history.py  (standard library only)."""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

for k, v in (("GIT_AUTHOR_NAME", "Test"), ("GIT_AUTHOR_EMAIL", "test@localhost"),
             ("GIT_COMMITTER_NAME", "Test"), ("GIT_COMMITTER_EMAIL", "test@localhost")):
    os.environ.setdefault(k, v)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "history.py"
FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAILS.append(name)


def hist(proj, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), str(proj), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout + r.stderr).strip()


def git(cwd, *args, inp=None):
    r = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(cwd), *args], capture_output=True,
                       input=inp.encode("utf-8") if inp is not None else None)
    out = r.stdout.decode("utf-8", "replace")
    return out.strip()


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def new_repo(tmp):
    git(tmp, "init", "-q")
    git(tmp, "config", "user.name", "Test")
    git(tmp, "config", "user.email", "test@localhost")


def test_basics(tmp):
    p = tmp / "p"
    p.mkdir()
    new_repo(p)
    write(p / "a.kicad_pro", "v1\n")
    write(p / "a.kicad_sch", "sch1\r\nline\n")
    rc, out = hist(p, "snap")
    check("basics: first snap saves step 1", rc == 0 and out == "saved step 1", out)
    rc, out = hist(p, "snap")
    check("basics: no change", rc == 0 and out == "no change", out)
    write(p / "a.kicad_sch", "sch2\r\nline\n")
    rc, out = hist(p, "snap", "--note", "second")
    check("basics: second snap", out == "saved step 2", out)
    rc, out = hist(p, "list")
    check("basics: list shows both", "2 steps" in out and "second" in out, out)
    rc, out = hist(p, "restore", "1")
    check("basics: restore ok", rc == 0 and "restored 2 design files" in out, out)
    check("basics: restored byte for byte", (p / "a.kicad_sch").read_bytes() == b"sch1\r\nline\n")
    refs = git(p, "for-each-ref", "--format=%(refname)", "refs/boardwright/")
    check("basics: ref is per project", refs.splitlines()[0:1] == ["refs/boardwright/steps/root"], refs)
    check("basics: no index files left", not list((p / ".git").glob("boardwright-steps.*.index")))
    rc, out = hist(p, "snap")
    check("basics: nothing to snap on empty design", True)
    e = tmp / "empty"
    e.mkdir()
    rc, out = hist(e, "snap")
    check("basics: no design files -> no change", rc == 0 and out == "no change", out)


def test_two_projects(tmp):
    repo = tmp / "repo"
    repo.mkdir()
    new_repo(repo)
    a, b = repo / "projA", repo / "projB"
    write(a / "a.kicad_pro", "A\n")
    write(a / "a.kicad_sch", "A-sch\n")
    write(b / "b.kicad_pro", "B\n")
    write(b / "b.kicad_sch", "B1\n")
    hist(a, "snap")
    hist(b, "snap")
    write(b / "b.kicad_sch", "B2\n")
    hist(b, "snap")
    with open(a / "a.kicad_sch", "ab") as f:  # projA's unsaved work
        f.write(b"unsaved A work\n")
    rc, out = hist(b, "restore", "1")
    check("two projects: restore from B succeeds", rc == 0, out)
    check("two projects: B went back", (b / "b.kicad_sch").read_bytes() == b"B1\n")
    check("two projects: A's unsaved text survives", (a / "a.kicad_sch").read_bytes() == b"A-sch\nunsaved A work\n",
          (a / "a.kicad_sch").read_bytes())
    refs = git(repo, "for-each-ref", "--format=%(refname)", "refs/boardwright/").splitlines()
    check("two projects: two separate refs", len(refs) == 2 and all(r.startswith("refs/boardwright/steps/") for r in refs),
          str(refs))
    rc, out = hist(a, "list")
    check("two projects: A history is its own (1 step)", "# 1 steps" in out, out)


def test_concurrent(tmp):
    p = tmp / "conc"
    p.mkdir()
    new_repo(p)
    write(p / "x.kicad_pro", "x\n")
    for i in range(8):
        write(p / f"f{i}.kicad_sch", "initial\n")
    hist(p, "snap")
    results = [None] * 8
    gate = threading.Barrier(8)

    def work(i):
        write(p / f"f{i}.kicad_sch", f"edit {i}\n")
        gate.wait()
        results[i] = hist(p, "snap", "--quiet")

    ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    bad = [r for r in results if r is None or r[0] != 0 or r[1]]
    check("concurrent: no error output", not bad, str(bad)[:3000])
    ref = git(p, "for-each-ref", "--format=%(refname)", "refs/boardwright/").splitlines()[0]
    commits = git(p, "rev-list", ref).split()
    empty = [c for c in commits if not git(p, "ls-tree", "-r", "--name-only", c)]
    check("concurrent: no empty-tree step", commits and not empty, f"{len(commits)} steps, empty: {empty}")
    last = git(p, "ls-tree", "-r", "--name-only", commits[0]).splitlines()
    check("concurrent: newest step has all files", len(last) == 9, str(last))
    check("concurrent: no leftover index or lock", not list((p / ".git").glob("boardwright-steps.*")),
          str(list((p / ".git").glob("boardwright-steps.*"))))


def test_non_ascii(tmp):
    p = tmp / "na"
    p.mkdir()
    new_repo(p)
    data = "传感器 v1\r\n".encode("utf-8")
    write(p / "传感器.kicad_pro", "pro\n")
    (p / "传感器.kicad_sch").write_bytes(data)
    hist(p, "snap")
    (p / "传感器.kicad_sch").write_bytes(b"changed\n")
    hist(p, "snap")
    rc, out = hist(p, "restore", "1")
    check("non-ASCII: restore succeeds", rc == 0 and "restored 2 design files" in out, out)
    check("non-ASCII: byte-identical", (p / "传感器.kicad_sch").read_bytes() == data)


def test_migration(tmp):
    p = tmp / "mig"
    p.mkdir()
    new_repo(p)
    write(p / "m.kicad_pro", "old\n")
    blob = git(p, "hash-object", "-w", "--no-filters", "--", str(p / "m.kicad_pro"))
    tree = git(p, "mktree", inp=f"100644 blob {blob}\tm.kicad_pro\n")
    commit = git(p, "commit-tree", tree, "-m", "old step")
    git(p, "update-ref", "refs/boardwright/steps", commit)
    write(p / "m.kicad_pro", "new\n")
    rc, out = hist(p, "list")
    check("migration: old history is still listed", rc == 0 and "# 1 steps" in out and "old step" in out, out)
    refs = git(p, "for-each-ref", "--format=%(refname) %(objectname)", "refs/boardwright/").splitlines()
    names = [r.split()[0] for r in refs]
    check("migration: old plain ref is gone, new ref holds it",
          "refs/boardwright/steps" not in names and f"refs/boardwright/steps/root {commit}" in refs, str(refs))
    rc, out = hist(p, "restore", "1")
    check("migration: restore from migrated step", rc == 0 and (p / "m.kicad_pro").read_bytes() == b"old\n", out)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="bw-history-"))
    try:
        for t in (test_basics, test_two_projects, test_concurrent, test_non_ascii, test_migration):
            sub = tmp / t.__name__
            sub.mkdir()
            try:
                t(sub)
            except Exception as e:  # a crash is a failure, not an abort
                check(t.__name__ + " ran", False, repr(e))
    finally:
        def onerr(fn, path, exc):
            try:
                os.chmod(path, 0o700)
                fn(path)
            except OSError:
                pass
        shutil.rmtree(tmp, onerror=onerr)
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
