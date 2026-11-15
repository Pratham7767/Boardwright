#!/usr/bin/env python3
"""A stand-in for the `claude` CLI, for testing the chat window without an
account.  It speaks just enough of the stream-json protocol.

  FAKE_LOGGED_IN=1   `auth status` reports signed in
  FAKE_PLUGIN=1      `plugin list` contains boardwright

Prompts:  anything  -> streamed text, one Bash tool call that asks permission
          "slow"    -> streams for 30 s until interrupted
          "ask"     -> an AskUserQuestion request
"""
import json
import os
import sys
import threading
import time

args = sys.argv[1:]


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


if args[:1] == ["--version"]:
    print("0.0.0 (fake Claude Code)")
    sys.exit(0)
if args[:2] == ["auth", "status"]:
    ok = os.environ.get("FAKE_LOGGED_IN") == "1"
    print(json.dumps({"loggedIn": ok, "authMethod": "claude.ai" if ok else "none",
                      "email": "must-not-be-kept@example.com"}, indent=2))
    sys.exit(0 if ok else 1)
if args[:2] == ["plugin", "list"]:
    print(json.dumps([{"id": "boardwright@boardwright", "version": "0.1.0", "enabled": True}]
                     if os.environ.get("FAKE_PLUGIN") == "1" else []))
    sys.exit(0)
if args[:2] == ["plugin", "marketplace"] or args[:2] == ["plugin", "install"]:
    print("ok (fake): " + " ".join(args))
    sys.exit(0)
if "-p" not in args:
    print("fake claude: unsupported arguments", args)
    sys.exit(2)

SID = "11111111-2222-3333-4444-555555555555"
responses, interrupted = {}, threading.Event()
got = threading.Condition()
users = []


def reader():
    for line in sys.stdin:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        with got:
            if d.get("type") == "control_request":
                sub = d["request"]["subtype"]
                if sub == "interrupt":
                    interrupted.set()
                emit({"type": "control_response", "response": {
                    "subtype": "success", "request_id": d["request_id"], "response": {}}})
            elif d.get("type") == "control_response":
                r = d["response"]
                responses[r["request_id"]] = r.get("response") or {}
            elif d.get("type") == "user":
                users.append(d["message"]["content"])
            got.notify_all()
    with got:
        users.append(None)
        got.notify_all()


threading.Thread(target=reader, daemon=True).start()


def delta(text):
    emit({"type": "stream_event", "session_id": SID, "parent_tool_use_id": None,
          "event": {"type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": text}}})


def say(text):
    emit({"type": "stream_event", "session_id": SID, "parent_tool_use_id": None,
          "event": {"type": "message_start"}})
    for word in text.split(" "):
        delta(word + " ")
        time.sleep(0.03)
    emit({"type": "assistant", "session_id": SID, "parent_tool_use_id": None,
          "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


def ask_permission(rid, tool, inp, suggestions=None):
    emit({"type": "control_request", "request_id": rid, "request": {
        "subtype": "can_use_tool", "tool_name": tool, "input": inp,
        "permission_suggestions": suggestions or []}})
    with got:
        got.wait_for(lambda: rid in responses, timeout=120)
    return responses.get(rid, {"behavior": "deny"})


def result(text, is_error=False):
    emit({"type": "result", "subtype": "error_during_execution" if is_error else "success",
          "is_error": is_error, "result": text, "session_id": SID, "total_cost_usd": 0.0123,
          "duration_ms": 100, "usage": {"input_tokens": 10, "output_tokens": 20}})


emit({"type": "system", "subtype": "init", "session_id": SID, "model": "fake-model", "cwd": os.getcwd(),
      "mcp_servers": [{"name": "plugin:boardwright:kicad-live", "status": "connected"}],
      "plugins": [{"name": "boardwright"}],
      "argv": args})
n = 0
while True:
    with got:
        got.wait_for(lambda: len(users) > n)
        prompt = users[n]
    n += 1
    if prompt is None:
        break
    interrupted.clear()
    if prompt == "slow":
        emit({"type": "stream_event", "session_id": SID, "parent_tool_use_id": None,
              "event": {"type": "message_start"}})
        for i in range(60):
            if interrupted.is_set():
                break
            delta(f"{i} ")
            time.sleep(0.5)
        result("interrupted" if interrupted.is_set() else "done", is_error=interrupted.is_set())
        continue
    if prompt == "ask":
        q = {"questions": [{"question": "Which regulator?", "header": "Power", "multiSelect": False,
                            "options": [{"label": "LDO", "description": "simple"},
                                        {"label": "Buck", "description": "efficient"}]}]}
        r = ask_permission("perm_q", "AskUserQuestion", q)
        say("You answered: " + json.dumps((r.get("updatedInput") or {}).get("answers")))
        result("ok")
        continue
    say(f"Hello from fake Claude. You said: {prompt}")
    emit({"type": "assistant", "session_id": SID, "parent_tool_use_id": None,
          "message": {"role": "assistant", "content": [
              {"type": "tool_use", "id": f"tool_{n}", "name": "Bash",
               "input": {"command": "python scripts/status.py ."}}]}})
    r = ask_permission(f"perm_{n}", "Bash", {"command": "python scripts/status.py ."},
                       [{"type": "addRules", "rules": [{"toolName": "Bash"}], "behavior": "allow",
                         "destination": "session"}])
    if r.get("behavior") == "allow":
        say("The command was allowed" + (" and remembered." if r.get("updatedPermissions") else "."))
    else:
        emit({"type": "user", "session_id": SID, "parent_tool_use_id": None, "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": f"tool_{n}",
                                         "is_error": True, "content": r.get("message", "denied")}]}})
        say("The command was denied.")
    result("ok")
