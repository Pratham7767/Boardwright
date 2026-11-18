"""Measure what the Boardwright MCP tools save: the same questions to real Claude Code, once with the MCP
server and once without it (the skills then fall back to running the scripts and reading files).

    python tools/bench/mcp_savings.py <project folder> [--model sonnet] [--out results.json]

Works on a temporary copy of the project, in plan mode (nothing is changed). Uses your Claude plan:
each question is one real Claude Code turn. Prints tokens and cost per question and the totals.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kicad-addon" / "plugins"))
for k in [k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC"))]:
    del os.environ[k]
import bw_core as core  # noqa: E402

QUESTIONS = [
    "Where does this board stand? One plain line per stage, then the single next step.",
    "Which nets on this board are still unrouted, and does DRC show any error? Short answer.",
    "Which parts on this board have stock or lifecycle problems? One line each.",
]


def ask(argv: list, proj: Path, question: str) -> dict:
    q: queue.Queue = queue.Queue()
    sess = core.ClaudeSession(argv, str(proj), lambda k, p, s=None: q.put((k, p)))
    sess.start()
    t0 = time.time()
    sess.send(question)
    tools = 0
    try:
        while True:
            k, p = q.get(timeout=900)
            if k == "tool":
                tools += 1
            elif k == "permission":
                sess.allow(p["request_id"], p["input"], None)      # plan mode: reads only
            elif k == "result":
                return {"cost": p.get("cost") or 0.0, "tokens_in": p["tokens_in"], "tokens_out": p["tokens_out"],
                        "tool_calls": tools, "seconds": round(time.time() - t0, 1), "error": p["is_error"]}
            elif k == "exit":
                return {"error": True, "exit": p}
    finally:
        sess.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default="", help="comma list of variants: all MCP, only bw MCP, without MCP")
    a = ap.parse_args()
    claude = core.check_claude(None)["path"]
    work = Path(tempfile.mkdtemp(prefix="bwsave"))
    src = Path(a.project).resolve()
    proj = work / src.name
    shutil.copytree(src, proj, ignore=shutil.ignore_patterns(".git", ".history", "*-backups", "fab", "*.lck",
                                                             "datasheets", "dev-to-article"))
    base = core.build_argv(claude, "plan", plugin_dir=str(ROOT / "plugin"), model=a.model)
    own = {"boardwright": {"command": "uv", "args": ["run", "--no-project", "--quiet", "python",
                                                     str(ROOT / "plugin" / "scripts" / "bw_mcp.py")]}}
    variants = {
        "all MCP": base,
        "all MCP + tool search": base,
        "only bw MCP": base + ["--strict-mcp-config", "--mcp-config",
                               json.dumps({"mcpServers": {"plugin_boardwright_boardwright": own["boardwright"]}})],
        "bw MCP up front": base + ["--strict-mcp-config", "--mcp-config",
                                          json.dumps({"mcpServers": {"plugin_boardwright_boardwright": own["boardwright"]}})],
        "without MCP": base + ["--strict-mcp-config", "--mcp-config", json.dumps({"mcpServers": {}})],
    }
    if a.only:
        variants = {k: v for k, v in variants.items() if k in a.only.split(",")}
    res = {name: [] for name in variants}
    for question in QUESTIONS:
        for name, argv in variants.items():
            if "tool search" in name:
                os.environ["ENABLE_TOOL_SEARCH"] = "true"        # tool definitions load only when needed
            if "up front" in name:
                os.environ["ENABLE_TOOL_SEARCH"] = "false"       # the few tool definitions sent with the prompt
            try:
                r = ask(argv, proj, question)
            finally:
                os.environ.pop("ENABLE_TOOL_SEARCH", None)
            r["question"] = question
            res[name].append(r)
            print(f"{name:22} {r.get('tokens_in', 0):>8,} in {r.get('tokens_out', 0):>6,} out "
                  f"${r.get('cost', 0):.3f} {r.get('tool_calls', 0):>3} tool calls  {question[:50]}", flush=True)
    tot = {n: {"tokens_in": sum(r.get("tokens_in", 0) for r in rs), "tokens_out": sum(r.get("tokens_out", 0) for r in rs),
               "cost": round(sum(r.get("cost", 0) for r in rs), 4), "tool_calls": sum(r.get("tool_calls", 0) for r in rs)}
           for n, rs in res.items()}
    for n, t in tot.items():
        print(f"TOTAL {n:12} {t['tokens_in']:,} in, {t['tokens_out']:,} out, ${t['cost']:.3f}, {t['tool_calls']} tool calls")
    if a.out:
        Path(a.out).write_text(json.dumps({"model": a.model, "runs": res, "totals": tot}, indent=2), "utf-8")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
