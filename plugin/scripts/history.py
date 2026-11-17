#!/usr/bin/env python3
"""Design history: a snapshot after every edit, undo to any step, a commit after each stage, and a lock.

    python scripts/history.py . snap [--note TEXT] [--quiet]   save a step if a design file changed
    python scripts/history.py . list [N]                         the last N steps (default 20), newest first
    python scripts/history.py . diff A [B]                       files changed between step A and B (default: now)
    python scripts/history.py . restore N [--force]             put the design files back as they were at step N
    python scripts/history.py . stage-commit N NAME              commit the design files: "stage N: NAME passed"
    python scripts/history.py . lock status|take WHO|release WHO one editor at a time

Steps are git commits on a hidden ref, refs/boardwright/steps/<id> (one per project), built from a private index: no branch
moves, nothing is staged in your index and your own commits are untouched. A project inside a git
repository keeps them in that repository; any other project gets its own private store in
.boardwright/history.git. Design files: the board, schematics, project, rules, symbol and footprint
libraries and boardwright.json. A restore first saves the current state as a step, so it can itself
be undone, and refuses while KiCad has the file open (its ~*.lck file) unless --force.

stage-commit makes a normal commit on your current branch with only the design files and reports/, and
only in a git repository; elsewhere it saves a step instead and says so. The lock lives in
.boardwright/edit.lock; a lock untouched for 30 minutes is free again.
Standard library only. Exit 0 ok, 1 refused (lock held, KiCad has the file open), 2 setup problem.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

OLD_REF = "refs/boardwright/steps"      # the one shared ref of older versions (a plain ref, not a folder)
REF_BASE = "refs/boardwright/steps/"    # now one ref per project: REF_BASE + <id>
LEGACY_BASE = "refs/boardwright/legacy/"
LOCK_WAIT_S = 10
LOCK_STALE_INDEX_S = 60
DESIGN_EXT = (".kicad_pcb", ".kicad_sch", ".kicad_pro", ".kicad_dru", ".kicad_sym", ".kicad_mod", ".kicad_wks")
DESIGN_NAMES = ("sym-lib-table", "fp-lib-table", "boardwright.json")
SKIP_DIRS = {".git", ".boardwright", ".history", "fab", "__pycache__", "node_modules", "scripts"}
LOCK_STALE_S = 30 * 60
IDENT = {"GIT_AUTHOR_NAME": "Boardwright", "GIT_AUTHOR_EMAIL": "boardwright@localhost",
         "GIT_COMMITTER_NAME": "Boardwright", "GIT_COMMITTER_EMAIL": "boardwright@localhost"}


def own_dir(proj: Path) -> Path:
    """.boardwright/ with a .gitignore of '*', so its contents never end up in the user's own commits."""
    d = proj / ".boardwright"
    d.mkdir(exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", "utf-8")
    return d


def die(msg: str, code: int = 2):
    print(msg)
    sys.exit(code)


def design_files(proj: Path) -> list:
    out = []
    for root, dirs, files in os.walk(proj):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith("-backups")]
        for f in files:
            if f.startswith("~") or f.startswith("_autosave") or f.endswith(".lck"):
                continue
            if f.endswith(DESIGN_EXT) or f in DESIGN_NAMES:
                out.append(Path(root) / f)
    return sorted(out)


class Store:
    """Where the steps live: the project's git repository, or a private one in .boardwright/."""

    def __init__(self, proj: Path):
        # One spelling of every path: Windows may hand us a short name (RUNNER~1) for a folder whose
        # files resolve to the long name, and relative_to() would then say the file is not inside it.
        proj = Path(proj).resolve()
        self.proj = proj
        top = self._plain(["git", "-C", str(proj), "rev-parse", "--show-toplevel"])
        if top:
            self.top = Path(top).resolve()
            self.gitdir = Path(self._plain(["git", "-C", str(proj), "rev-parse", "--absolute-git-dir"]))
            self.private = False
        else:
            self.top = proj
            self.gitdir = proj / ".boardwright" / "history.git"
            self.private = True
            if not (self.gitdir / "HEAD").is_file():
                own_dir(proj)
                subprocess.run(["git", "init", "-q", "--bare", str(self.gitdir)], check=True)
        try:
            rel = self.proj.relative_to(self.top).as_posix()
        except ValueError:
            rel = "."
        self.is_top = rel in (".", "")
        self.id = "root" if self.is_top else hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
        self.ref = REF_BASE + self.id
        self.prefix = "" if self.is_top else rel + "/"

    @staticmethod
    def _plain(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        except OSError:
            die("git is not installed; the design history needs it (https://git-scm.com).")
        return r.stdout.strip() if r.returncode == 0 else ""

    def git(self, *args, index=None, check=True, binary=False, stdin=None):
        env = dict(os.environ, GIT_DIR=str(self.gitdir), GIT_WORK_TREE=str(self.top), **IDENT)
        if index:
            env["GIT_INDEX_FILE"] = str(index)
        r = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
                            "-c", "core.quotepath=false", *args],
                           cwd=str(self.top), env=env, capture_output=True, input=stdin,
                           **({} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}))
        if check and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or b'')[-300:]}")
        return r.stdout if binary else r.stdout.strip()

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.top).as_posix()

    def head(self) -> str:
        return self.git("rev-parse", "-q", "--verify", self.ref, check=False)

    @contextlib.contextmanager
    def lock(self):
        """A lock file in the git dir, so that parallel snaps take turns. Waits up to 10 s; stale after 60 s."""
        p = self.gitdir / "boardwright-steps.lock"
        deadline = time.time() + LOCK_WAIT_S
        while True:
            try:
                os.close(os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                break
            except (FileExistsError, PermissionError):
                try:
                    if time.time() - p.stat().st_mtime > LOCK_STALE_INDEX_S:
                        p.unlink()
                        continue
                except OSError:
                    pass
                if time.time() > deadline:
                    raise RuntimeError("the history lock is busy: " + str(p))
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                p.unlink()
            except OSError:
                pass

    def migrate(self):
        """Older versions kept every project's steps on the one ref refs/boardwright/steps. A plain ref blocks
        the folder refs/boardwright/steps/, so it is moved aside (nothing is lost); the project that is the
        repository top takes it over as its own history."""
        if not self.git("rev-parse", "-q", "--verify", OLD_REF, check=False):
            if not (self.is_top and not self.head()):
                return
        with self.lock():
            old = self.git("rev-parse", "-q", "--verify", OLD_REF, check=False)
            if old:
                self.git("update-ref", "-d", OLD_REF, old)
                self.git("update-ref", LEGACY_BASE + old[:12], old, "0" * 40, check=False)
            if self.is_top and not self.head():
                src = old or self.git("for-each-ref", "--sort=-committerdate", "--count=1",
                                      "--format=%(objectname)", LEGACY_BASE, check=False)
                if src:
                    self.git("update-ref", self.ref, src, "0" * 40)

    def steps(self) -> list:
        """Oldest first: [(commit, unix time, note)]."""
        self.migrate()
        h = self.head()
        if not h:
            return []
        out = self.git("log", "--reverse", "--format=%H%x09%ct%x09%s", h)
        return [tuple(l.split("\t", 2)) for l in out.splitlines() if l]

    def snap(self, note: str) -> str | None:
        files = design_files(self.proj)
        if not files:
            return None
        self.migrate()
        # A private index file per call (parallel hooks must not share one), removed afterwards.
        idx = self.gitdir / f"boardwright-steps.{os.getpid()}.{uuid.uuid4().hex[:8]}.index"
        try:
            self.git("read-tree", "--empty", index=idx)
            rels = [self.rel(f) for f in files]
            # Stored byte for byte (--no-filters): git's line-ending and attribute conversions would make a
            # restore differ from the file that was saved.
            shas = self.git("hash-object", "-w", "--no-filters", "--", *[str(f) for f in files]).split()
            if not shas or len(shas) != len(rels):
                return None
            info = "".join(f"100644 {sha}\t{rel}\n" for sha, rel in zip(shas, rels))
            # bytes, not text: in text mode Windows writes CR LF, and every path would end in a CR
            self.git("update-index", "--add", "--index-info", index=idx, stdin=info.encode("utf-8"), binary=True)
            tree = self.git("write-tree", index=idx)
            with self.lock():
                parent = self.head()
                if parent and self.git("rev-parse", parent + "^{tree}") == tree:
                    return None
                args = ["commit-tree", tree, "-m", note or "edit"] + (["-p", parent] if parent else [])
                new = self.git(*args)
                self.git("update-ref", self.ref, new, parent or "0" * 40)
            return new
        finally:
            try:
                idx.unlink()
            except OSError:
                pass


def step_commit(store: Store, n: str) -> str:
    steps = store.steps()
    try:
        k = int(n)
    except ValueError:
        die(f"step must be a number 1..{len(steps)}")
    if not 1 <= k <= len(steps):
        die(f"no step {k}; there are {len(steps)}")
    return steps[k - 1][0]


def kicad_has_open(store: Store, rels: list) -> list:
    out = []
    for r in rels:
        p = store.top / r
        if (p.parent / f"~{p.name}.lck").exists():
            out.append(r)
    return out


def cmd_list(store: Store, args):
    steps = store.steps()
    n = int(args[0]) if args else 20
    if not steps:
        print("no steps yet (one is saved after each edit to a design file)")
        return 0
    where = ".boardwright/history.git" if store.private else f"{store.ref} in the project's git repository"
    print(f"# {len(steps)} steps, kept in {where}. step | time | what")
    for i in range(len(steps), max(0, len(steps) - n), -1):
        c, t, note = steps[i - 1]
        print(f"{i} | {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(t)))} | {note}")
    return 0


def cmd_diff(store: Store, args):
    if not args:
        die("usage: diff A [B]")
    a = step_commit(store, args[0])
    if len(args) > 1:
        out = store.git("diff", "--stat=120", a, step_commit(store, args[1]))
    else:
        store.snap("diff check")  # compare with the files as they are now
        out = store.git("diff", "--stat=120", a, store.head())
    print(out or "no difference")
    return 0


def cmd_restore(store: Store, args):
    if not args:
        die("usage: restore N [--force]")
    c = step_commit(store, args[0])
    listing = store.git("-c", "core.quotepath=false", "ls-tree", "-r", "-z", "--name-only", c, binary=True)
    # only files that belong to this project (older shared history may hold other projects' files)
    rels = [r for r in (b.decode("utf-8", "replace") for b in listing.split(b"\0") if b)
            if r.startswith(store.prefix) and ".." not in r.split("/")]
    open_ = kicad_has_open(store, rels)
    if open_ and "--force" not in args:
        print("KiCad has these open: " + ", ".join(open_) + ". Close them in KiCad first (or add --force and "
              "reload them in KiCad after).")
        return 1
    before = store.snap(f"before restore to step {args[0]}")
    for r in rels:
        data = store.git("show", f"{c}:{r}", binary=True)
        p = store.top / r
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    now = {store.rel(f) for f in design_files(store.proj)}
    extra = sorted(now - set(rels))
    store.snap(f"restored step {args[0]}")
    print(f"restored {len(rels)} design files to step {args[0]}"
          + (" (the state before it is saved as a step)" if before else ""))
    if extra:
        print("left as they are (not in that step): " + ", ".join(extra))
    return 0


def cmd_stage_commit(store: Store, args):
    if len(args) < 2:
        die("usage: stage-commit N NAME")
    msg = f"stage {args[0]}: {' '.join(args[1:])} passed"
    if store.private:
        store.snap(msg)
        print("not a git repository: saved a step instead (" + msg + "). Run `git init` here to get stage commits.")
        return 0
    paths = [store.rel(f) for f in design_files(store.proj)]
    reports = store.proj / "reports"
    if reports.is_dir():
        paths.append(store.rel(reports))
    env = dict(os.environ)
    r = subprocess.run(["git", "-C", str(store.top), "add", "--", *paths], capture_output=True, text=True, env=env)
    if r.returncode:
        die("git add failed: " + r.stderr.strip())
    r = subprocess.run(["git", "-C", str(store.top), "commit", "-q", "-m", msg, "--only", "--", *paths],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out = (r.stdout + r.stderr).strip()
    if r.returncode and "nothing to commit" in out + r.stdout:
        print("nothing changed since the last commit")
        return 0
    if r.returncode:
        die("git commit failed: " + out[-400:])
    store.snap(msg)
    print("committed: " + msg)
    return 0


# ------------------------------------------------------------------ lock
def lock_path(proj: Path) -> Path:
    return proj / ".boardwright" / "edit.lock"


def lock_read(proj: Path) -> dict | None:
    p = lock_path(proj)
    try:
        d = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - d.get("at", 0) > LOCK_STALE_S:
        return None
    return d


def lock_take(proj: Path, who: str, label: str = "") -> dict | None:
    """Take or refresh the lock for WHO. Returns the other holder's record when someone else holds it."""
    d = lock_read(proj)
    if d and d.get("who") != who:
        return d
    p = lock_path(proj)
    own_dir(proj)
    rec = {"who": who, "label": label or (d or {}).get("label", ""), "since": (d or {}).get("since", time.time()),
           "at": time.time()}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec), "utf-8")
    os.replace(tmp, p)
    return None


def lock_release(proj: Path, who: str) -> bool:
    d = lock_read(proj)
    if d and d.get("who") == who:
        lock_path(proj).unlink(missing_ok=True)
        return True
    return False


def describe(d: dict) -> str:
    mins = int((time.time() - d.get("since", time.time())) / 60)
    return f"{d.get('label') or 'another session'} ({d.get('who', '?')[:8]}), editing for {mins} min"


def cmd_lock(proj: Path, args):
    if not args or args[0] not in ("status", "take", "release"):
        die("usage: lock status|take WHO|release WHO")
    if args[0] == "status":
        d = lock_read(proj)
        print("free" if not d else "held by " + describe(d))
        return 0
    if len(args) < 2:
        die(f"usage: lock {args[0]} WHO")
    if args[0] == "take":
        other = lock_take(proj, args[1], " ".join(args[2:]))
        if other:
            print("refused: held by " + describe(other))
            return 1
        print("taken")
        return 0
    print("released" if lock_release(proj, args[1]) else "not held by " + args[1])
    return 0


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    proj = Path(argv[0]).resolve()
    if not proj.is_dir():
        die("not a folder: " + str(proj))
    cmd, args = argv[1], argv[2:]
    if cmd == "lock":
        return cmd_lock(proj, args)
    store = Store(proj)
    if cmd == "snap":
        note = args[args.index("--note") + 1] if "--note" in args else "edit"
        c = store.snap(note)
        if "--quiet" not in args:
            print(f"saved step {len(store.steps())}" if c else "no change")
        return 0
    return {"list": cmd_list, "diff": cmd_diff, "restore": cmd_restore,
            "stage-commit": cmd_stage_commit}.get(cmd, lambda s, a: die("unknown command " + cmd))(store, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
