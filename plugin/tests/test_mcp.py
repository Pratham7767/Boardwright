#!/usr/bin/env python3
"""Drive bw_mcp.py over stdio: initialize, tools/list, then status, plan, board_find and run_gates.

Usage:  python plugin/tests/test_mcp.py <project folder>

The project folder should be a COPY (run_gates writes reports/). Exit 0 = pass or skipped (KiCad not
installed), 1 = a check failed, 2 = bad usage.
"""
import json
import subprocess
import sys
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


def main():
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_dir():
        print(__doc__)
        return 2
    try:
        from run_gates import find_kicad_cli
        if not find_kicad_cli():
            raise ImportError
    except Exception:
        print("SKIP: KiCad (kicad-cli) not found; set KICAD_CLI to run this test")
        return 0
    proj = Path(sys.argv[1]).resolve()
    p = subprocess.Popen([sys.executable, str(SCRIPTS / "bw_mcp.py")], cwd=str(proj), stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    fails = []
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
        want = {"status", "plan", "run_gates", "sch_check", "history_list", "fab_check",
                "routing_plan_show", "board_find"}
        check("tools/list", set(names) == want)
        check("unknown method error", "error" in send("nope/none"))
        res, text = tool("status")
        check("status", not res["isError"] and "[exit code 0]" in text)
        res, text = tool("plan")
        check("plan", not res["isError"] and "[exit code 0]" in text)
        res, text = tool("board_find", {"selector": {"kind": "pad", "ref": "C3"}})
        check("board_find", not res["isError"] and "C3" in text)
        res, text = tool("run_gates", {"no_export": True})
        check("run_gates", not res["isError"] and "[exit code" in text)
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
