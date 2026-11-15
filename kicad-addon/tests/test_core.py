#!/usr/bin/env python3
"""Tests for plugins/bw_core.py against tests/fake_claude.py (no account needed).

    python tests/test_core.py            all tests with the fake CLI
    python tests/test_core.py --real     also start the real `claude` once and
                                         print what comes back (may use your plan)
"""
import os
import queue
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugins"))
import bw_core as core                                           # noqa: E402

for k in [k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC"))]:
    del os.environ[k]          # a desktop-app shell sets these; KiCad's does not


def make_fake() -> str:
    """A launcher for fake_claude.py that can be started like claude.exe."""
    d = Path(tempfile.mkdtemp(prefix="bw_fake_"))
    fake = ROOT / "tests" / "fake_claude.py"
    if os.name == "nt":
        p = d / "claude.cmd"
        p.write_text(f'@"{sys.executable}" "{fake}" %*\r\n', "utf-8")
    else:
        p = d / "claude"
        p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n', "utf-8")
        p.chmod(0o755)
    return str(p)


class Collect:
    def __init__(self):
        self.q = queue.Queue()
        self.all = []

    def __call__(self, kind, payload):
        self.q.put((kind, payload))

    def until(self, kind, timeout=20):
        while True:
            k, p = self.q.get(timeout=timeout)
            self.all.append((k, p))
            if k == kind:
                return p

    def text(self):
        return "".join(p for k, p in self.all if k == "text")


def test_parser():
    a = core.build_argv("claude", "plan", model="sonnet")
    assert a[a.index("--model") + 1] == "sonnet" and "--model" not in core.build_argv("claude")
    assert core.looks_like_limit("You've reached your Fable limit. Switch to another model, or ...")
    assert not core.looks_like_limit("All good")
    ps = core.StreamParser()
    ev = ps.feed('{"type":"system","subtype":"init","session_id":"abc","model":"m","mcp_servers":[{"name":"x","status":"failed"}]}')
    assert ev[0][0] == "init" and ev[0][1]["mcp"] == [("x", "failed")] and ps.session_id == "abc"
    assert ps.feed("not json") == [("raw", "not json")]
    assert ps.feed('{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}}') == [("text", "hi")]
    # the full message repeats streamed text: only a newline may come out
    assert ps.feed('{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}') == [("text", "\n")]
    # helper-agent text is hidden, its tool calls are shown as sub-steps
    ev = ps.feed('{"type":"assistant","parent_tool_use_id":"t1","message":{"content":[{"type":"text","text":"x"},{"type":"tool_use","id":"a","name":"Read","input":{"file_path":"a.txt"}}]}}')
    assert ev == [("tool", {"id": "a", "name": "Read", "sub": True, "summary": "Read: a.txt"})], ev
    ev = ps.feed('{"type":"result","is_error":true,"result":"Not logged in · Please run /login","usage":{}}')
    assert ev[0][1]["auth"] is True
    assert core.tool_summary("mcp__plugin_boardwright_kicad-live__pcb_summary", {}) == "kicad-live · pcb_summary"
    print("ok  parser")


def test_checks(fake):
    os.environ.pop("FAKE_LOGGED_IN", None)
    os.environ.pop("FAKE_PLUGIN", None)
    r = core.run_all_checks(fake)
    assert r["claude"]["ok"] and "fake" in r["claude"]["version"], r
    assert r["auth"] == {"ok": False, "known": True, "method": "none", "detail": ""}, r["auth"]
    assert r["plugin"]["known"] and not r["plugin"]["installed"] and not r["ready"], r
    os.environ["FAKE_LOGGED_IN"] = "1"
    os.environ["FAKE_PLUGIN"] = "1"
    r = core.run_all_checks(fake)
    assert r["ready"] and r["plugin"]["ok"], r
    assert "example.com" not in repr(r), "auth check kept more than loggedIn/authMethod"
    r = core.run_all_checks(str(Path(fake).parent / "nothing-here"))
    os.environ["PATH"], keep = "", os.environ["PATH"]
    try:
        home, os.environ["USERPROFILE"] = os.environ.get("USERPROFILE"), tempfile.gettempdir()
        appdata = os.environ.pop("APPDATA", None)
        assert core.find_claude() is None
        r = core.run_all_checks()
        assert not r["claude"]["ok"] and r["auth"] is None and not r["ready"]
    finally:
        os.environ["PATH"] = keep
        if home:
            os.environ["USERPROFILE"] = home
        if appdata:
            os.environ["APPDATA"] = appdata
    print("ok  first-run checks (not installed / not signed in / signed in)")


def test_session(fake):
    c = Collect()
    s = core.ClaudeSession(core.build_argv(fake, "ask"), str(ROOT), c)
    s.start()
    assert s.send("hello")
    init = c.until("init")
    assert init["model"] == "fake-model"
    tool = c.until("tool")
    assert tool["summary"] == "Bash: python scripts/status.py .", tool
    perm = c.until("permission")
    assert perm["tool_name"] == "Bash" and perm["suggestions"]
    s.allow(perm["request_id"], perm["input"], perm["suggestions"])
    res = c.until("result")
    assert not res["is_error"] and not s.busy and res["cost"] == 0.0123
    assert "Hello from fake Claude. You said: hello" in c.text(), c.text()
    assert "allowed and remembered" in c.text(), c.text()
    assert s.session_id == "11111111-2222-3333-4444-555555555555"

    c.all.clear()
    s.send("again")
    perm = c.until("permission")
    s.deny(perm["request_id"])
    assert c.until("tool_error") == "The user said no."
    c.until("result")
    assert "The command was denied." in c.text()

    c.all.clear()
    s.send("slow")                       # stop button
    c.until("text")
    s.interrupt()
    res = c.until("result", timeout=10)
    assert res["is_error"] and res["text"] == "interrupted"

    c.all.clear()
    s.send("ask")                        # AskUserQuestion round trip
    perm = c.until("permission")
    assert perm["tool_name"] == "AskUserQuestion"
    s.allow(perm["request_id"], dict(perm["input"], answers={"Which regulator?": "LDO"}))
    c.until("result")
    assert '"Which regulator?": "LDO"' in c.text(), c.text()

    s.send("slow")                       # hard stop
    c.until("text")
    s.kill()
    ex = c.until("exit", timeout=15)
    assert ex["killed"] and not s.alive
    print("ok  chat session (stream, tool line, allow, deny, stop, question, kill)")


def real_smoke():
    claude = core.find_claude()
    print("real claude:", claude)
    r = core.run_all_checks()
    print("checks:", {k: r[k] for k in ("claude", "auth", "plugin", "helpers", "ready")})
    c = Collect()
    s = core.ClaudeSession(core.build_argv(claude, "ask"), str(ROOT), c)
    s.start()
    s.send("Reply with the single word: pong")
    try:
        while True:
            k, p = c.q.get(timeout=120)
            if k == "text":
                print("  text:", repr(p))
            elif k == "init":
                print("  init:", p)
            else:
                print(f"  {k}:", p)
            if k in ("result", "exit"):
                break
    finally:
        s.close()


if __name__ == "__main__":
    test_parser()
    fake = make_fake()
    test_checks(fake)
    test_session(fake)
    if "--real" in sys.argv:
        real_smoke()
    print("all passed")
