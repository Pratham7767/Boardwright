#!/usr/bin/env python3
"""Tests for scripts/diagnostics.py. Run: python plugin/tests/test_diagnostics.py  (exit 0 only if all pass)."""
from __future__ import annotations

import getpass
import json
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import diagnostics as D  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond:
        FAILS.append(name)


def jl(path: Path, recs, append=False):
    with open(path, "a" if append else "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def ts(minute):
    return f"2026-11-17T10:{minute:02d}:00.000Z"


def asst(mid, model, usage, minute, content=None):
    return {"type": "assistant", "timestamp": ts(minute), "requestId": "req_" + mid,
            "message": {"id": mid, "model": model, "usage": usage, "content": content or [{"type": "text", "text": "ok"}]}}


def all_text(root: Path) -> str:
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.name != "consent.json":
            if p.suffix == ".zip":
                with zipfile.ZipFile(p) as z:
                    out += [z.read(n).decode("utf-8", "replace") for n in z.namelist()]
            else:
                out.append(p.read_text("utf-8", "replace"))
    return "\n".join(out)


def main():
    # Claude Code puts its own notes in the same message as what the person typed: keep only the words.
    pt = D._prompt_text
    check("prompt after a system reminder is kept",
          pt("<system-reminder>\nnote\n</system-reminder>\n\nroute the LEDs please") == "route the LEDs please")
    check("a message that is only a task notification is no prompt",
          pt("<task-notification>\n<task-id>x</task-id>\n</task-notification>") is None)
    check("local command output is no prompt", pt("<local-command-stdout>Set model</local-command-stdout>") is None)
    home, user = str(Path.home()), getpass.getuser()
    tmp = Path(tempfile.mkdtemp(prefix="bwdiag_"))
    proj = tmp / "proj"
    proj.mkdir()
    tdir = tmp / "claude"
    tdir.mkdir()
    tr = tdir / "sess-1.jsonl"
    sub = tdir / "sess-1" / "subagents"
    sub.mkdir(parents=True)
    d = proj / ".boardwright" / "diagnostics"

    iters = [{"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 5000,
              "cache_creation_input_tokens": 400, "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 300}},
             {"input_tokens": 500, "output_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}]
    opus_usage = {"input_tokens": 9999, "output_tokens": 9999, "iterations": iters, "inference_geo": "global", "speed": "standard"}
    lines = [
        {"type": "user", "timestamp": "2026-11-17T09:00:00.000Z", "message": {"role": "user", "content": "OLD prompt before consent"}},
        dict(asst("msg_old", "claude-opus-5-5", {"input_tokens": 777777, "output_tokens": 1}, 0), timestamp="2026-11-17T09:30:00.000Z"),
        {"type": "user", "timestamp": ts(1), "message": {"role": "user", "content":
            f"Check key sk-ant-abc123DEF456ghi789 and mail jane.doe@example.com, file {home}\\proj\\a.kicad_pcb by {user}"}},
        asst("msg_1", "claude-opus-5-5", opus_usage, 2, [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "SECRETBLOB"}}]),
        asst("msg_1", "claude-opus-5-5", opus_usage, 2, [{"type": "text", "text": "x"}, {"type": "tool_use", "id": "t2", "name": "Read", "input": {}}]),
        {"type": "user", "timestamp": ts(3), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "Exit code 1 password=hunter2 failed"}]}},
        {"type": "api-request", "timestamp": ts(3), "body": "SECRETBLOB", "message": {"content": "SECRETBLOB"}},
        {"type": "user", "timestamp": ts(5), "message": {"role": "user", "content": [{"type": "text", "text": "second prompt text"}]}},
        asst("msg_2", "claude-sonnet-5-5", {"input_tokens": 2000, "output_tokens": 1000, "cache_read_input_tokens": 10000,
                                            "cache_creation_input_tokens": 1000}, 6),
        asst("msg_3", "claude-haiku-5-5-20261101", {"input_tokens": 120000, "output_tokens": 1000}, 7),
        asst("msg_4", "claude-haiku-5-5", {"input_tokens": 1000, "output_tokens": 500}, 8),
        asst("msg_5", "claude-mystery-1", {"input_tokens": 10, "output_tokens": 10}, 9),
        {"type": "cost-state", "timestamp": ts(10), "totalCostUSD": 1.23, "modelUsage": {"claude-opus-5-5": {"costUSD": 0.9}}},
        "this line is not json",
    ]
    jl(tr, lines)
    jl(sub / "agent-x.jsonl", [
        {"type": "user", "timestamp": ts(4), "message": {"role": "user", "content": "delegated task, not a user prompt"}},
        asst("msg_s1", "claude-sonnet-5-5", {"input_tokens": 1000, "output_tokens": 500}, 4)])
    (sub / "agent-x.meta.json").write_text(json.dumps({"agentType": "general-purpose"}), "utf-8")
    since = "2026-11-17T10:00:00Z"

    # consent off
    D.record(proj, "sess-1", tr)
    check("nothing recorded with consent off", not d.exists() or not (d / "sessions").exists())
    r = subprocess.run([sys.executable, str(SCRIPTS / "diagnostics.py"), str(proj), "record", "--session", "sess-1",
                        "--transcript", str(tr)], capture_output=True, text=True)
    check("record CLI silent with consent off", r.returncode == 0 and r.stdout == "" and not (d / "sessions").exists())

    # consent on
    D.set_consent(proj, True, True, "yes, record my prompts", since=since)
    check("consent read back", D.consent(proj)["on"] and D.consent(proj)["prompts"])
    check(".boardwright has .gitignore", (proj / ".boardwright" / ".gitignore").read_text() == "*\n")
    D.record(proj, "sess-1", tr)
    S = json.loads((d / "sessions" / "sess-1.json").read_text("utf-8"))
    check("prompts counted (old one ignored, subagent prompt not counted)", len(S["prompts"]) == 2, str(len(S["prompts"])))
    check("usage deduped per message id", len(S["usage"]) == 6, str(sorted(S["usage"])))
    check("tool calls counted once", S["tools"] == {"Bash": 1, "Read": 1}, str(S["tools"]))
    check("error found with tool name", any(e["kind"] == "tool_error" and e["tool"] == "Bash" for e in S["errors"]))
    check("subagent type from meta", "general-purpose" in S["agents"])
    D.cmd_report(proj)
    R = json.loads((d / "report.json").read_text("utf-8"))
    m = R["models"]
    close = lambda a, b: a is not None and abs(a - b) < 1e-9  # noqa: E731
    check("opus cost (iterations, 1h cache)", close(m["claude-opus-5-5"]["cost_usd"], 0.0159), str(m.get("claude-opus-5-5")))
    check("opus tokens from iterations", m["claude-opus-5-5"]["input"] == 1500 and m["claude-opus-5-5"]["requests"] == 1)
    check("sonnet cost incl. subagent", close(m["claude-sonnet-5-5"]["cost_usd"], 0.0245), str(m.get("claude-sonnet-5-5")))
    check("haiku cost with over-100k prices", close(m["claude-haiku-5-5-20261101"]["cost_usd"], 0.0625) and close(m["claude-haiku-5-5"]["cost_usd"], 0.00035),
          str({k: v["cost_usd"] for k, v in m.items()}))
    check("unknown model cost unknown", m["claude-mystery-1"]["cost_usd"] is None and m["claude-mystery-1"]["input"] == 10)
    check("total cost unknown when a model is unpriced", R["totals"]["cost_estimate_usd"] is None and "claude-mystery-1" in R["totals"]["unknown_models"])
    check("Claude Code's own figure kept", R["totals"]["cost_claude_code_usd"] == 1.23 and m["claude-opus-5-5"]["claude_code_usd"] == 0.9)
    check("agents split", {"main", "general-purpose"} <= set(R["agents"]))
    check("errors by kind", R["errors"]["tool_error"]["count"] == 1 and R["errors"]["tool_error"]["tool"] == "Bash")
    md = (d / "report.md").read_text("utf-8")
    check("report.md has summary placeholder and model table", "## Summary in plain words" in md and "| Model | Requests |" in md)
    check("report says API-equivalent estimate", "API-equivalent estimate" in md)
    check("prompts text in report when allowed", "second prompt text" in md)

    # redaction
    text = all_text(d)
    check("no api key in outputs", "sk-ant-abc123" not in text and "hunter2" not in text)
    check("no e-mail in outputs", "jane.doe@example.com" not in text)
    check("no home path in outputs", home not in text and home.replace("\\", "\\\\") not in text and home.replace("\\", "/") not in text)
    if len(user) >= 3:
        check("no user name in outputs", user.lower() not in text.lower())
    check("no SECRETBLOB in outputs", "SECRETBLOB" not in text)
    check("redaction counts reported", R["redactions"].get("anthropic-key", 0) >= 1 and R["redactions"].get("email", 0) >= 1, str(R["redactions"]))
    check("redact() kinds", D.redact("ghp_" + "a" * 25) == "[redacted:github-token]" and D.redact("AKIA" + "A" * 16) == "[redacted:aws-key]"
          and "[redacted:bearer]" in D.redact("Authorization: Bearer abc.def")
          and "[redacted:private-key]" in D.redact("-----BEGIN RSA PRIVATE KEY-----\nxx\n-----END RSA PRIVATE KEY-----"))

    # more secret kinds
    rd = D.redact
    check("openai-style keys (incl. sk-proj-)", rd("sk-proj-" + "aB3_-" * 8) == "[redacted:openai-key]"
          and rd("key sk-" + "A" * 24 + " end") == "key [redacted:openai-key] end")
    check("anthropic key still its own kind", rd("sk-ant-api03-" + "x" * 30) == "[redacted:anthropic-key]")
    check("firecrawl key", rd("fc-" + "a1" * 12) == "[redacted:firecrawl-key]")
    check("google key", rd("AIza" + "Sy" * 17) == "[redacted:google-key]")
    check("slack token", rd("xoxb-123456789012-abcdefABCDEF") == "[redacted:slack-token]")
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefgh12345678"
    check("jwt", rd("t=" + jwt) == "t=[redacted:jwt]" or "[redacted:jwt]" in rd("see " + jwt), rd(jwt))
    check("key=value keeps the key, hides the value",
          rd("api_key=abc123") == "api_key=[redacted:secret]" and rd("secret: s3cr3t!") == "secret: [redacted:secret]"
          and rd("TOKEN = xyz") == "TOKEN = [redacted:secret]" and rd("pwd=1") == "pwd=[redacted:secret]"
          and "hunter2" not in rd("auth=hunter2") and "hunter2" not in rd("passwd: hunter2"), rd("api_key=abc123"))
    check("'password <value>'", rd("the password hunter2 was") == "the [redacted:password] was", rd("the password hunter2 was"))
    check("harmless words stay", rd("the tokens were fine, authority") == "the tokens were fine, authority")
    saved = D._PATTERNS
    old_git = D._git_config
    D._git_config = lambda k: {"user.name": "Zebediah Quux", "user.email": "zq@corp.test"}.get(k, "")
    try:
        D._PATTERNS = D._build_patterns()
        out = rd("by Zebediah Quux <zq@corp.test> and zq@corp.test")
        check("git user name and e-mail redacted", "Zebediah" not in out and "zq@corp" not in out, out)
        D._git_config = lambda k: ""
        D._PATTERNS = D._build_patterns()
        check("no git config: no crash", rd("Zebediah Quux") == "Zebediah Quux")
    finally:
        D._git_config, D._PATTERNS = old_git, saved

    # fast mode / region pricing: tokens counted, cost unknown
    fp = tmp / "fastproj"
    fp.mkdir()
    ftr = tdir / "fast-1.jsonl"
    jl(ftr, [asst("f1", "claude-sonnet-5-5", {"input_tokens": 1000, "output_tokens": 500}, 21),
             asst("f2", "claude-sonnet-5-5", {"input_tokens": 2000, "output_tokens": 100, "speed": "fast"}, 22),
             asst("f3", "claude-opus-5-5", {"input_tokens": 3000, "output_tokens": 100, "inference_geo": "us"}, 23),
             asst("f4", "claude-opus-5-5", {"input_tokens": 4000, "output_tokens": 100, "inference_geo": "global", "speed": "standard"}, 24)])
    D.set_consent(fp, True, False, "x", since=since)
    D.record(fp, "fast-1", ftr)
    D.cmd_report(fp)
    RF = json.loads((fp / ".boardwright" / "diagnostics" / "report.json").read_text("utf-8"))
    mdf = (fp / ".boardwright" / "diagnostics" / "report.md").read_text("utf-8")
    check("fast / US requests counted, tokens kept", RF["totals"]["nonstandard_requests"] == 2 and RF["totals"]["input"] == 10000,
          str(RF["totals"]))
    check("fast / US cost unknown, not guessed", RF["models"]["claude-sonnet-5-5"]["cost_usd"] is None
          and RF["models"]["claude-opus-5-5"]["cost_usd"] is None and RF["totals"]["cost_estimate_usd"] is None)
    check("report lists the not-estimated requests",
          "2 requests in fast mode / US-only inference: cost not estimated (different price)" in mdf)
    check("standard / global requests still priced", RF["models"]["claude-sonnet-5-5"]["nonstandard_requests"] == 1
          and not D.nonstandard({"geo": "global", "speed": "standard"}) and not D.nonstandard({}))

    # report rewrite keeps the summary Claude wrote
    rp0 = d / "report.md"
    mdtxt = rp0.read_text("utf-8")
    check("fresh report has the placeholder", "_Not written yet._" in mdtxt)
    mine = "We routed the board. It was slow at the DRC step.\nThe cost was small."
    head, tail = mdtxt.split("## Summary in plain words", 1)
    tail = tail[tail.index("Generated "):]
    rp0.write_text(head + "## Summary in plain words\n\n" + mine + "\n\n" + tail, "utf-8")
    D.cmd_report(proj)
    after = rp0.read_text("utf-8")
    check("report keeps Claude's summary", mine in after and "_Not written yet._" not in after and "<!-- CLAUDE" not in after)
    check("kept summary appears once, rest regenerated", after.count("We routed the board") == 1 and "## Totals" in after)

    # incremental
    size1 = tr.stat().st_size
    state1 = json.loads((d / "state.json").read_text())
    D.record(proj, "sess-1", tr)
    S2 = json.loads((d / "sessions" / "sess-1.json").read_text("utf-8"))
    check("second record with no new lines changes nothing", S2["prompts"] == S["prompts"] and S2["usage"] == S["usage"])
    jl(tr, [{"type": "user", "timestamp": ts(11), "message": {"content": "third prompt"}},
            asst("msg_6", "claude-sonnet-5-5", {"input_tokens": 100, "output_tokens": 100}, 12),
            asst("msg_2", "claude-sonnet-5-5", {"input_tokens": 2000, "output_tokens": 1000, "cache_read_input_tokens": 10000,
                                                "cache_creation_input_tokens": 1000}, 13)], append=True)
    with open(tr, "a", encoding="utf-8") as f:
        f.write('{"type":"user","timestamp":"' + ts(14) + '","message":{"content":"half line')  # incomplete: must wait
    D.record(proj, "sess-1", tr)
    S3 = json.loads((d / "sessions" / "sess-1.json").read_text("utf-8"))
    check("incremental adds only new lines", len(S3["prompts"]) == 3 and len(S3["usage"]) == 7, f"{len(S3['prompts'])} {len(S3['usage'])}")
    state3 = json.loads((d / "state.json").read_text())
    check("offset advanced to last complete line, not past partial one",
          list(state3["files"].values())[0] > list(state1["files"].values())[0] and size1 < tr.stat().st_size
          and max(state3["files"].values()) < tr.stat().st_size)

    # export
    r = subprocess.run([sys.executable, str(SCRIPTS / "diagnostics.py"), str(proj), "export"], capture_output=True, text=True)
    zips = list(d.glob("boardwright-diagnostics-*.zip"))
    check("export makes one zip and prints instructions", r.returncode == 0 and len(zips) == 1 and "Nothing has been sent" in r.stdout
          and "issues/new?template=diagnostics.yml" in r.stdout, r.stdout + r.stderr)
    with zipfile.ZipFile(zips[0]) as z:
        names = z.namelist()
        mf = json.loads(z.read("manifest.json"))
    check("zip content: report.md, report.json, sessions, manifest",
          {"report.md", "report.json", "manifest.json", "sessions/sess-1.json"} <= set(names), str(names))
    check("manifest fields", {"boardwright_version", "os", "python", "kicad", "included", "consent"} <= set(mf))
    text = all_text(d)
    check("no SECRETBLOB / key / home in zip", "SECRETBLOB" not in text and "sk-ant-abc123" not in text and home not in text)

    # prompts: false
    D.cmd_delete(proj)
    check("delete removes recordings", not (d / "sessions").exists() and not list(d.glob("*.zip")) and not (d / "report.md").exists()
          and not (d / "state.json").exists() and (d / "consent.json").exists())
    D.set_consent(proj, True, False, "yes but not my prompts", since=since)
    D.record(proj, "sess-1", tr)
    D.cmd_report(proj)
    sm = d / "report.md"
    h, t_ = sm.read_text("utf-8").split("## Summary in plain words", 1)
    sm.write_text(h + "## Summary in plain words\n\nSummary written by Claude.\n\n" + t_[t_.index("Generated "):], "utf-8")
    D.cmd_export(proj)
    check("export keeps the summary", "Summary written by Claude." in sm.read_text("utf-8"))
    text = all_text(d)
    S4 = json.loads((d / "sessions" / "sess-1.json").read_text("utf-8"))
    check("prompts false: count and lengths only", len(S4["prompts"]) == 3 and all(p["text"] is None and p["chars"] > 0 for p in S4["prompts"]))
    check("prompts false: no prompt text anywhere", "second prompt text" not in text and "third prompt" not in text and "Check key" not in text)

    # status, delete
    st = subprocess.run([sys.executable, str(SCRIPTS / "diagnostics.py"), str(proj), "status"], capture_output=True, text=True).stdout
    check("status shows consent and sessions", "ON since" in st and "Sessions recorded: 1" in st, st)
    D.cmd_delete(proj)
    check("delete again", not (d / "sessions").exists())

    # fast-ish on big input
    big = tdir / "big.jsonl"
    with open(big, "w", encoding="utf-8") as f:
        row = json.dumps(asst("m", "claude-sonnet-5-5", {"input_tokens": 1, "output_tokens": 1}, 20)) + "\n"
        pad = json.dumps({"type": "attachment", "timestamp": ts(20), "x": "y" * 2000}) + "\n"
        for i in range(8000):
            f.write(row.replace('"m"', f'"m{i}"', 1) + pad)
    t0 = time.time()
    D.record(proj, "big", big)
    check("larger transcript records quickly", time.time() - t0 < 5, f"{time.time() - t0:.1f}s")

    # real transcripts smoke test
    root = Path.home() / ".claude" / "projects"
    if root.is_dir():
        cands = [p for p in root.rglob("*.jsonl") if "subagents" not in p.parts]
        if cands:
            newest = max(cands, key=lambda p: p.stat().st_mtime)
            p2 = tmp / "smoke"
            p2.mkdir()
            D.set_consent(p2, True, True, "smoke", since="2000-01-01T00:00:00Z")
            t0 = time.time()
            D.record(p2, newest.stem, newest)
            dt = time.time() - t0
            rp = D.cmd_report(p2)
            R2 = json.loads((p2 / ".boardwright" / "diagnostics" / "report.json").read_text("utf-8"))
            header = [ln for ln in rp.read_text("utf-8").splitlines() if ln.startswith("| Model |")]
            print(f"smoke: transcript {newest.stat().st_size:,} bytes, record {dt:.1f}s, report.md {rp.stat().st_size:,} bytes, "
                  f"report.json {rp.with_suffix('.json').stat().st_size:,} bytes, sessions {R2['totals']['sessions']}, "
                  f"prompts {R2['totals']['prompts']}, models {len(R2['models'])}")
            print("smoke: table header: " + (header[0] if header else "(none)"))
            check("smoke: report.md produced", rp.stat().st_size > 0 and bool(header))
        else:
            print("smoke: no transcripts found, skipped")
    else:
        print("smoke: ~/.claude/projects not found, skipped")

    print(("\nall passed" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
