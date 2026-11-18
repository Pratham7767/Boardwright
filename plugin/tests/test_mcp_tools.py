#!/usr/bin/env python3
"""Tests for the Boardwright MCP server's tools and guards (plugin/scripts/bw_mcp.py).

    python plugin/tests/test_mcp_tools.py

Works on a temp copy of examples/usb-sensor-test (without `fab`), set up with
`init_project.py <copy> --update-scripts`. Talks to the real server over stdio. Calls that need KiCad
(find, check gates, edit) are skipped cleanly when KiCad is not found. Prints `ok` / `FAIL` / `skip` lines.
Exit 0 only when every check passed. Standard library only.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _k, _v in (("GIT_AUTHOR_NAME", "test"), ("GIT_AUTHOR_EMAIL", "test@example.invalid"),
               ("GIT_COMMITTER_NAME", "test"), ("GIT_COMMITTER_EMAIL", "test@example.invalid")):
    os.environ.setdefault(_k, _v)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPTS = REPO / "plugin" / "scripts"
EXAMPLE = REPO / "examples" / "usb-sensor-test"
sys.path.insert(0, str(SCRIPTS))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FAILS = []


def check(name, cond, detail=""):
    print(f"{'ok  ' if cond else 'FAIL'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"skip {name}: {why}")


class Server:
    def __init__(self, cwd, env=None):
        self.p = subprocess.Popen([sys.executable, str(SCRIPTS / "bw_mcp.py")], cwd=str(cwd), stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        self.n = 0

    def rpc(self, method, params=None):
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        reply = json.loads(self.p.stdout.readline())
        assert reply["id"] == self.n, reply
        return reply

    def tool(self, name, **args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return r, r["content"][0]["text"]

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()


def sh(*args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)


def main():
    import history
    from run_gates import find_kicad_cli
    have_kicad = bool(find_kicad_cli())
    tmp = Path(tempfile.mkdtemp(prefix="bwtools_"))
    proj = tmp / "usb-sensor-test"
    shutil.copytree(EXAMPLE, proj, ignore=shutil.ignore_patterns("fab"))
    r = sh(SCRIPTS / "init_project.py", proj, "--update-scripts")
    check("init_project --update-scripts", r.returncode == 0, r.stdout[-300:] + r.stderr[-300:])
    pcb = proj / "usb-sensor-test.kicad_pcb"
    srv = Server(proj)
    try:
        srv.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        init = srv.rpc("initialize")["result"]
        check("instructions under 600 characters", len(init.get("instructions", "")) < 600, str(len(init.get("instructions", ""))))
        lst = srv.rpc("tools/list")["result"]
        names = [t["name"] for t in lst["tools"]]
        size = len(json.dumps(lst, separators=(",", ":")))
        print(f"     tools/list: {len(names)} tools, {size} characters")
        want = {"status", "check", "find", "edit", "place", "route", "history", "plan", "fab", "lifecycle",
                "diagnostics", "engine", "setup", "digest", "export"}
        check("tools/list has the expected names", set(names) == want, ",".join(names))
        check("tools/list under 6,000 characters", size < 6000, str(size))
        banned = ("approve", "consent", "restore", "reject", "undo", "choice", "waive", "upload", "send", "order", "publish")
        check("no new action offers a user decision or a send",
              not [w for t in lst["tools"] for w in banned
                   if w in json.dumps(t["inputSchema"]).lower() and t["name"] not in ("history", "plan", "diagnostics")], "")
        by = {t["name"]: t for t in lst["tools"]}
        check("digest is read-only, setup and export are not", by["digest"].get("annotations", {}).get("readOnlyHint")
              and "annotations" not in by["setup"] and "annotations" not in by["export"])
        check("no approve, consent or restore tool",
              not [n for n in names if any(w in n for w in ("approve", "consent", "restore", "reject"))]
              and "restore" not in json.dumps(lst["tools"][names.index("history")]))
        check("every tool takes an optional project", all("project" in t["inputSchema"]["properties"] for t in lst["tools"]))

        # refusals and answers that need no KiCad
        r, t = srv.tool("status", project=str(tmp))
        check("non-project folder refused", r["isError"] and "not a Boardwright project" in t, t)
        r, t = srv.tool("status")
        check("status", not r["isError"] and "READY NOW" in t and r["structuredContent"]["exit_code"] == 0, t[:200])
        r, t = srv.tool("history", action="list")
        check("history list (no history yet or a list)", not r["isError"], t)
        r, t = srv.tool("history", action="restore")
        check("history restore is not offered", r["isError"] and "pcb-undo" in t, t)
        r, t = srv.tool("plan", action="show")
        check("plan show", not r["isError"] and "routing plan" in t, t)
        r, t = srv.tool("plan", action="approve")
        check("plan approve is refused", r["isError"] and "designer" in t, t)
        r, t = srv.tool("diagnostics", action="status")
        check("diagnostics status", not r["isError"] and "Diagnostics:" in t, t)
        r, t = srv.tool("diagnostics", action="on")
        check("diagnostics on is refused", r["isError"] and "user" in t, t)
        r, t = srv.tool("fab", action="check")
        check("fab check", not r["isError"] and "factory:" in t, t)
        r, t = srv.tool("check", kind="sch") if have_kicad else (None, "")
        if r:
            check("check sch answers one line", not r["isError"] and t.startswith("sch:"), t)
        else:
            skip("check sch", "KiCad not found")
        r, t = srv.tool("engine", action="status")
        if "not installed" in t:
            skip("engine answers", "engine tools not installed (status says so)")
        else:
            check("engine answers", not r["isError"], t)
        r, t = srv.tool("setup", action="doctor")
        check("setup doctor answers one summary line", not r["isError"] and t.startswith("doctor:"), t)
        r, t = srv.tool("setup", action="bogus")
        check("setup refuses an unknown action", r["isError"] and "new, update or doctor" in t, t)
        r, t = srv.tool("setup", action="new")
        check("setup new needs a folder", r["isError"] and "needs project" in t, t)
        newdir = tmp / "fresh-board"
        r = srv.rpc("tools/call", {"name": "setup", "arguments": {"action": "new", "project": str(newdir), "name": "fresh"}})["result"]
        t = r["content"][0]["text"]
        check("setup new creates a project", not r["isError"] and "new project" in t and (newdir / "PROJECT.md").is_file()
              and (newdir / "scripts").is_dir(), t)
        marker = newdir / "PROJECT.md"
        marker.write_text("my own words\n", encoding="utf-8")
        r, t = srv.tool("setup", action="new", project=str(newdir))
        check("setup new again never overwrites", not r["isError"] and marker.read_text("utf-8") == "my own words\n"
              and "0 files created" in t, t)
        r, t = srv.tool("status", project=str(newdir))
        check("the new folder is a project the other tools accept", not r["isError"], t[:150])
        r, t = srv.tool("setup", action="update")
        check("setup update answers and saves nothing it should not", not r["isError"] and "scripts updated in" in t, t)
        check("setup update left no lock", history.lock_read(proj) is None)
        r, t = srv.tool("digest", section="near")
        check("digest near needs args", r["isError"] and "near needs" in t, t)
        r, t = srv.tool("digest", section="bogus")
        check("digest refuses an unknown section", r["isError"], t)
        r, t = srv.tool("export", action="datasheets")
        check("export datasheets needs names or all", r["isError"] and "names" in t, t)
        r, t = srv.tool("export", action="datasheets", names=["--force"])
        check("export datasheets refuses option-like names", r["isError"], t)
        r, t = srv.tool("export", action="datasheets", names=["x"], pages="1;2")
        check("export datasheets refuses odd pages", r["isError"] and "pages must" in t, t)
        r, t = srv.tool("export", action="datasheets", all=True, pages="1-2")
        check("export datasheets pages read answers without crashing", "failed" not in t.splitlines()[0], t[:200])
        r, t = srv.tool("export", action="bogus")
        check("export refuses an unknown action", r["isError"], t)
        r, t = srv.tool("export", action="precompliance")
        check("export precompliance writes the pack", not r["isError"] and (proj / "reports" / "precompliance.md").is_file(), t)
        check("export left no lock", history.lock_read(proj) is None)

        if not have_kicad:
            for n in ("find", "check gates", "digest", "export parts and sim", "export release", "dry-run edit", "edit",
                      "lock refusal"):
                skip(n, "KiCad not found")
        else:
            r, t = srv.tool("find", selector={"kind": "pad", "ref": "C3"})
            check("find pads of C3", not r["isError"] and "C3.1" in t and "C3.2" in t, t)
            r, t = srv.tool("check", kind="gates")
            check("check gates", t.startswith("gates:") and "structuredContent" in r, t)
            print("     " + t.splitlines()[0])

            r, t = srv.tool("digest")
            check("digest summary", not r["isError"] and len(t) > 40, t[:200])
            r, t = srv.tool("digest", section="near", args=["C3", 8])
            check("digest near C3", not r["isError"] and "C3" in t, t[:200])
            r, t = srv.tool("digest", section="net", args=["NO_SUCH_NET"])
            check("digest unknown net is an answer, not a crash", r["isError"] and "[exit 2]" in t, t[:200])
            r, t = srv.tool("export", action="parts")
            check("export parts writes the register", not r["isError"] and (proj / "reports" / "parts-register.json").is_file(), t)
            r, t = srv.tool("export", action="sim")
            check("export sim writes sim/", not r["isError"] and (proj / "sim").is_dir() and "written to" in t, t[:200])
            r, t = srv.tool("export", action="release")
            check("export release answers with the gate summary", t.startswith("gates:"), t[:200])
            print("     " + t.splitlines()[0])

            before = pcb.read_bytes()
            r, t = srv.tool("edit", ops=[{"move": "H1", "rot": 45}], dry_run=True)
            check("dry-run edit answers", not r["isError"] and "H1" in t, t)
            check("dry-run edit leaves the board byte-identical", pcb.read_bytes() == before)
            check("dry-run edit leaves no lock", history.lock_read(proj) is None)

            n0 = len(history.Store(proj).steps())
            r, t = srv.tool("edit", ops=[{"move": "H1", "rot": 45}])
            check("edit move H1 rot 45", not r["isError"] and r["structuredContent"]["exit_code"] == 0, t)
            check("edit changed the board", pcb.read_bytes() != before)
            n1 = len(history.Store(proj).steps())
            check("edit added exactly one history step", n1 == n0 + 1, f"{n0} -> {n1}")
            check("edit left no lock behind", history.lock_read(proj) is None)

            # a second editor (another server process, another client) holds the lock
            r2 = sh(SCRIPTS / "history.py", proj, "lock", "take", "mcp-other", "second server")
            check("second editor took the lock", "taken" in r2.stdout, r2.stdout)
            mid = pcb.read_bytes()
            r, t = srv.tool("edit", ops=[{"move": "H1", "rot": 90}])
            check("edit refused while another editor holds the lock",
                  r["isError"] and "another editor" in t and "second server" in t, t)
            check("refused edit changed nothing", pcb.read_bytes() == mid)
            r, t = srv.tool("route", nets=["/SDA"])
            check("route refused while another editor holds the lock", r["isError"] and "another editor" in t, t)
            r, t = srv.tool("export", action="precompliance")
            check("export refused while another editor holds the lock", r["isError"] and "another editor" in t, t)
            r, t = srv.tool("setup", action="update")
            check("setup update refused while another editor holds the lock", r["isError"] and "another editor" in t, t)
            r, t = srv.tool("edit", ops=[{"move": "H1", "rot": 90}], dry_run=True)
            check("a dry run still answers while the lock is held", not r["isError"], t)
            sh(SCRIPTS / "history.py", proj, "lock", "release", "mcp-other")
            check("lock free again", history.lock_read(proj) is None)

        # engine run under the MCP's own lock: must not find the lock "taken by someone else"
        r, t = srv.tool("engine", action="run", args=["--nets", "NO_SUCH_NET_X", "--minutes", "1"])
        check("engine run does not trip over the MCP's own lock",
              "someone else is editing" not in t and "another editor" not in t, t[:300])
        if "not installed" in t:
            skip("engine run past the lock", "engine tools not installed (exit 2 'not installed' accepted)")
        check("engine run left no lock", history.lock_read(proj) is None)
        r, t = srv.tool("engine", action="leftovers")
        check("engine leftovers is an accepted read-only action", "action must be" not in t, t[:200])

        # hook: the new tools are MCP writes the hook hands the lock over for; reads stay reads
        import edit_hooks as eh
        P = "mcp__plugin_boardwright_boardwright__"
        check("hook: setup update and export are writes",
              eh.is_bw_mcp_write(P + "setup", {"action": "update"}) and eh.is_bw_mcp_write(P + "export", {"action": "parts"}))
        check("hook: setup doctor/new, engine status/leftovers, export datasheets pages are reads",
              not any(eh.is_bw_mcp_write(P + n, a) for n, a in (
                  ("setup", {"action": "doctor"}), ("setup", {"action": "new"}), ("engine", {"action": "status"}),
                  ("engine", {"action": "leftovers"}), ("export", {"action": "datasheets", "pages": "1-2"}))))
        check("hook: engine run and export datasheets (no pages) are writes",
              eh.is_bw_mcp_write(P + "engine", {"action": "run"}) and eh.is_bw_mcp_write(P + "export", {"action": "datasheets"}))
        check("hook: Bash engine.py run is a write, status and --dry-run are not",
              eh.is_bw_mcp_write("Bash", {"command": "python scripts/engine.py . run --minutes 2"})
              and not eh.is_bw_mcp_write("Bash", {"command": "python scripts/engine.py . status"})
              and not eh.is_bw_mcp_write("Bash", {"command": "python scripts/engine.py . run --dry-run"}))
        # the hook as Claude Code runs it: a session that holds the lock gives it up before setup update / export
        hook_env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
        sid = "sess-hook-1234"
        history.lock_take(proj, sid, "session " + sid[:8])
        hp = subprocess.run([sys.executable, str(SCRIPTS / "edit_hooks.py"), "pre"], input=json.dumps(
            {"session_id": sid, "cwd": str(proj), "tool_name": P + "setup", "tool_input": {"action": "update"}}),
            capture_output=True, text=True, encoding="utf-8", env=hook_env, timeout=60)
        check("hook pre hands the session's lock over for setup update", "deny" not in hp.stdout, hp.stdout + hp.stderr)
        check("hook pre released the session's lock", history.lock_read(proj) is None, str(history.lock_read(proj)))
    finally:
        srv.close()
    # a clean server in the working directory with no project: CLAUDE_PROJECT_DIR is used
    srv2 = Server(tmp, env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"})
    try:
        srv2.rpc("initialize", {"protocolVersion": "2025-06-18"})
        r, t = srv2.tool("status")
        check("no project in the working directory is refused", r["isError"] and "not a Boardwright project" in t, t)
    finally:
        srv2.close()
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    p = subprocess.Popen([sys.executable, str(SCRIPTS / "bw_mcp.py")], cwd=str(tmp), env=env, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": "status", "arguments": {}}}) + "\n")
        p.stdin.flush()
        res = json.loads(p.stdout.readline())["result"]
        check("CLAUDE_PROJECT_DIR is the fallback project", not res["isError"], res["content"][0]["text"][:150])
    finally:
        p.stdin.close()
        p.wait(timeout=10)
    shutil.rmtree(tmp, ignore_errors=True)
    print("PASS" if not FAILS else "FAILED: " + ", ".join(FAILS))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
