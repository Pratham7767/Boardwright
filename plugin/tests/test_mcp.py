#!/usr/bin/env python3
"""Drive bw_mcp.py over stdio: initialize, tools/list, then status, find and check gates.

Usage:  python plugin/tests/test_mcp.py [project folder]

Offline checks (no KiCad needed) always run: project refusal, the gates check never exports, history list never
creates a history. With a project folder (a COPY: the gates check writes reports/) the live server is driven too.
The write tools and their guards are in test_mcp_tools.py.
Exit 0 = pass or live part skipped (KiCad not installed), 1 = a check failed, 2 = bad usage.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def short(text, n=300):
    text = text.strip().replace("\n", " | ")
    return text if len(text) <= n else text[:n] + " ..."


def offline():
    import bw_mcp
    fails = []

    def check(name, cond, detail=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
        if not cond:
            fails.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="bwmcp_"))
    empty, proj = tmp / "empty", tmp / "proj"
    empty.mkdir()
    proj.mkdir()
    (proj / "PROJECT.md").write_text("# test\n", "utf-8")
    names = {t[0] for t in bw_mcp.TOOLS}
    for n in sorted(names):
        text, err, _rc = bw_mcp.call_tool(n, {"project": str(empty), "selector": {"kind": "net"}})
        check(f"{n} refuses a folder that is not a Boardwright project", err and "not a Boardwright project" in text, text)
    check("refusal created nothing", not list(empty.iterdir()))
    check("gates check always has --no-export", "--no-export" in bw_mcp.CHECKS["gates"][0][2], str(bw_mcp.CHECKS["gates"]))
    props = [t[2]["properties"] for t in bw_mcp.TOOLS if t[0] == "check"][0]
    check("check has no no_export option", "no_export" not in props and "export" not in props)
    text, err, _rc = bw_mcp.call_tool("history", {"project": str(proj), "action": "list"})
    check("history: no history yet", not err and "no history yet" in text, text)
    check("history created no history and no git repository",
          not (proj / ".boardwright").exists() and not (proj / ".git").exists(), str(list(proj.iterdir())))
    (tmp / "cfg").mkdir()
    (tmp / "cfg" / "boardwright.json").write_text("{}", "utf-8")
    check("boardwright.json alone makes a project", bw_mcp.is_project(tmp / "cfg"))
    check("has_history false without history", not bw_mcp.has_history(proj))
    (proj / ".boardwright" / "history.git").mkdir(parents=True)
    (proj / ".boardwright" / "history.git" / "HEAD").write_text("ref: refs/heads/master\n", "utf-8")
    check("has_history true with a private history", bw_mcp.has_history(proj))
    repo = tmp / "repo"
    repo.mkdir()
    (repo / "PROJECT.md").write_text("# t\n", "utf-8")
    try:
        g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)  # noqa: E731
        g("init", "-q")
        check("git repo without steps: no history", not bw_mcp.has_history(repo))
        head = subprocess.run(["git", "-C", str(repo), "mktree"], input="", capture_output=True, text=True,
                              check=True).stdout.strip()
        c = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.test", "commit-tree", head, "-m", "x"],
                           capture_output=True, text=True, check=True).stdout.strip()
        g("update-ref", "refs/boardwright/steps/abc123", c)
        check("git repo with a steps ref: has history", bw_mcp.has_history(repo))
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"SKIP git repository checks: {e}")
    return fails


def main():
    fails0 = offline()
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        if len(sys.argv) == 1:
            print("PASS (offline checks only)" if not fails0 else f"FAILED: {', '.join(fails0)}")
            return 1 if fails0 else 0
        print(__doc__)
        return 2
    try:
        from run_gates import find_kicad_cli
        if not find_kicad_cli():
            raise ImportError
    except Exception:
        print("SKIP: KiCad (kicad-cli) not found; set KICAD_CLI to run the live checks")
        return 1 if fails0 else 0
    proj = Path(sys.argv[1]).resolve()
    p = subprocess.Popen([sys.executable, str(SCRIPTS / "bw_mcp.py")], cwd=str(proj), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    fails = list(fails0)
    nid = [0]

    def send(method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            nid[0] += 1
            msg["id"] = nid[0]
        p.stdin.write(json.dumps(msg) + "\n")
        p.stdin.flush()
        if notify:
            return None
        reply = json.loads(p.stdout.readline())
        assert reply["id"] == nid[0], reply
        return reply

    def check(name, cond, detail=""):
        print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
        if not cond:
            fails.append(name)

    def tool(name, args=None):
        r = send("tools/call", {"name": name, "arguments": args or {}})
        res = r.get("result", {})
        text = res.get("content", [{}])[0].get("text", "")
        print(f"  -> {name}: isError={res.get('isError')} {short(text)}")
        return res, text

    try:
        r = send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "test", "version": "0"}})
        check("initialize", r["result"]["protocolVersion"] == "2025-06-18", r["result"]["serverInfo"])
        send("notifications/initialized", notify=True)
        check("ping", send("ping")["result"] == {})
        names = [t["name"] for t in send("tools/list")["result"]["tools"]]
        print("  tools:", ", ".join(names))
        want = {"status", "check", "find", "edit", "place", "route", "history", "plan", "fab", "lifecycle",
                "diagnostics", "engine", "setup", "digest", "export"}
        check("tools/list", set(names) == want)
        check("unknown method error", "error" in send("nope/none"))
        res, text = tool("status")
        check("status", not res["isError"] and "READY NOW" in text)
        check("replies are text only (Claude Code would show structuredContent instead of the text)",
              "structuredContent" not in res)
        res, text = tool("find", {"selector": {"kind": "pad", "ref": "C3"}})
        check("find", not res["isError"] and "C3" in text)
        res, text = tool("check", {"kind": "gates"})
        check("check gates", text.startswith("gates:"))
        res, text = tool("nope")
        check("unknown tool is an error", res["isError"])
    except Exception as e:  # noqa: BLE001
        check("driver", False, repr(e))
    finally:
        try:
            p.stdin.close()
            p.wait(timeout=10)
        except Exception:
            p.kill()
    print("PASS" if not fails else f"FAILED: {', '.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
