#!/usr/bin/env python3
"""Opt-in diagnostics: a local, redacted report built from Claude Code's own session transcripts.

    python scripts/diagnostics.py <project> status
    python scripts/diagnostics.py <project> record --session ID --transcript PATH   (called by the Stop/SessionEnd hooks)
    python scripts/diagnostics.py <project> report
    python scripts/diagnostics.py <project> export
    python scripts/diagnostics.py <project> delete

Nothing happens unless the user agreed (.boardwright/diagnostics/consent.json). Nothing is ever sent anywhere:
export writes a zip next to the report and the user sends it themselves. The transcripts are read
incrementally (a byte offset per file) and only a few fields are kept: prompts (if allowed), model, token
counts, tool names, error texts. Every stored string passes through redact().
Standard library only. Exit 0 always for `record`; 0 ok / 2 usage problem for the others.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from history import own_dir  # noqa: E402

try:
    from bw_project import md_table as _md_table  # noqa: E402
except Exception:  # pragma: no cover
    def _md_table(head, rows):
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        return out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]

ISSUE_URL = "https://github.com/Pratham7767/Boardwright/issues/new?template=diagnostics.yml"
SKIP_TYPES = {"api-request", "api-request-blob"}
ERR_MAX = 300
CAP_ERRORS = 500
COST_LABEL = "API-equivalent estimate; on a subscription plan you are not billed per token"


# ------------------------------------------------------------------ redaction
_COUNTS: Counter = Counter()


def _git_config(key: str) -> str:
    """One value of `git config <key>`; empty when git or the value is missing."""
    try:
        r = subprocess.run(["git", "config", key], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _build_patterns():
    pats = [
        ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), None),
        ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]+"), None),
        ("openai-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}"), None),
        ("firecrawl-key", re.compile(r"fc-[A-Za-z0-9]{20,}"), None),
        ("google-key", re.compile(r"AIza[0-9A-Za-z_-]{30,}"), None),
        ("slack-token", re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,}"), None),
        ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), None),
        ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), None),
        ("github-token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), None),
        ("aws-key", re.compile(r"AKIA[0-9A-Z]{16}"), None),
        ("bearer", re.compile(r"Bearer\s+\S+", re.I), None),
        # key=value secrets: the key name stays, the value goes
        ("secret", re.compile(r"\b(api[_-]?key|secret|token|passwd|password|pwd|auth)\b(\s*[:=]\s*)\S+", re.I),
         r"\1\2[redacted:secret]"),
        ("password", re.compile(r"\bpassword\s+\S+", re.I), None),
    ]
    # the git user's name and e-mail (read once); the e-mail goes before the generic e-mail pattern
    g_mail, g_name = _git_config("user.email"), _git_config("user.name")
    if len(g_mail) >= 3:
        pats.append(("git-email", re.compile(re.escape(g_mail), re.I), None))
    pats += [
        ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), None),
        # written out to dodge spam filters: "name at gmail dot com", "name [at] mail [dot] org"
        ("email", re.compile(r"(?i)\b[A-Za-z0-9._%+-]+\s*(?:\(at\)|\[at\]|\bat\b)\s*[A-Za-z0-9-]+"
                             r"(?:\s*(?:\(dot\)|\[dot\]|\bdot\b)\s*[A-Za-z]{2,})+"), None),
    ]
    home = str(Path.home())
    toks = [t for t in re.split(r"[\\/]+", home) if t]
    hn = re.escape(Path.home().name)
    if toks:
        sep = r"[\\/]+"
        lead = r"[\\/]*" if home.startswith(("/", "\\")) else ""
        pats.append(("home", re.compile(lead + sep.join(re.escape(t) for t in toks), re.I), "~"))
    pats += [
        ("home", re.compile(r"/[A-Za-z]/Users/" + hn, re.I), "~"),
        ("home", re.compile(r"/home/" + hn, re.I), "~"),
        ("home", re.compile(r"/Users/" + hn, re.I), "~"),
        ("home", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"'<>|:*?]+", re.I), "~"),
    ]
    if len(g_name) >= 3:
        pats.append(("git-name", re.compile(r"(?<![A-Za-z0-9])" + re.escape(g_name) + r"(?![A-Za-z0-9])", re.I), "<user>"))
    try:
        name = getpass.getuser()
    except Exception:
        name = ""
    if len(name) >= 3:
        pats.append(("user", re.compile(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", re.I), "<user>"))
    return pats


_PATTERNS = _build_patterns()


def redact(text) -> str:
    """Replace secrets, e-mail addresses and the user's name/home folder; counts per kind in _COUNTS."""
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    for kind, rx, repl in _PATTERNS:
        s, n = rx.subn(repl if repl is not None else f"[redacted:{kind}]", s)
        if n:
            _COUNTS[kind] += n
    return s


def short(text, n: int = ERR_MAX) -> str:
    return redact(text)[:n]


# ------------------------------------------------------------------ files, consent
def diag_dir(proj: Path, create: bool = False) -> Path:
    if create:
        d = own_dir(Path(proj)) / "diagnostics"
        d.mkdir(exist_ok=True)
        return d
    return Path(proj) / ".boardwright" / "diagnostics"


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", "utf-8")
    os.replace(tmp, p)


def _read_json(p: Path, default):
    try:
        d = json.loads(p.read_text("utf-8"))
        return d if isinstance(d, type(default)) else default
    except (OSError, ValueError):
        return default


def consent(proj) -> dict:
    d = _read_json(diag_dir(proj) / "consent.json", {})
    return {"on": bool(d.get("on")), "prompts": bool(d.get("prompts")), "since": d.get("since") or "",
            "typed": d.get("typed") or ""}


def set_consent(proj, on: bool, prompts: bool, typed: str = "", since: str | None = None) -> dict:
    old = consent(proj)
    if on and old["on"] and old["since"] and since is None:
        since = old["since"]
    rec = {"on": bool(on), "prompts": bool(prompts),
           "since": since or datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "typed": typed or ""}
    _write_json(diag_dir(proj, True) / "consent.json", rec)
    return rec


def parse_ts(v):
    if not isinstance(v, str) or not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


# ------------------------------------------------------------------ prices
def load_prices() -> dict:
    return _read_json(HERE / "model_prices.json", {}).get("models", {})


def price_for(model: str):
    base = re.sub(r"\[.*?\]\s*$", "", model or "")
    best = None
    for key, p in load_prices().items():
        if base.startswith(key) and (best is None or len(key) > len(best[0])):
            best = (key, p)
    return best[1] if best else None


def _cost_bucket(p: dict, v: list) -> float:
    inp, out, c5, c1, cr = v
    return (inp * p["input"] + out * p["output"] + c5 * p["cache_write_5m"] + c1 * p["input"] * 2
            + cr * p["cache_read"]) / 1e6


def nonstandard(r: dict) -> bool:
    """Fast mode or a restricted inference region: billed at a different price than the standard table."""
    geo = r.get("geo")
    return r.get("speed") == "fast" or (isinstance(geo, str) and geo.strip().lower() not in ("", "global", "not_available"))


def usage_cost(model: str, n: list, b: list):
    """USD for one request record, or None when the model is not in the price table."""
    p = price_for(model)
    if not p:
        return None
    pb = p.get("over_100k_prompt") or p
    return _cost_bucket(p, n) + _cost_bucket(pb, b)


# ------------------------------------------------------------------ transcript parsing
def _num(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _src_numbers(src: dict) -> list:
    inp, out = _num(src.get("input_tokens")), _num(src.get("output_tokens"))
    cr, cc = _num(src.get("cache_read_input_tokens")), _num(src.get("cache_creation_input_tokens"))
    c5 = c1 = 0
    sub = src.get("cache_creation")
    if isinstance(sub, dict):
        c5, c1 = _num(sub.get("ephemeral_5m_input_tokens")), _num(sub.get("ephemeral_1h_input_tokens"))
    if c5 + c1 < cc:
        c5 = cc - c1
    return [inp, out, c5, c1, cr]


def usage_buckets(u: dict):
    """([normal], [over-100k-prompt]) token lists [input, output, cache5m, cache1h, cache_read]."""
    its = u.get("iterations")
    srcs = [i for i in its if isinstance(i, dict)] if isinstance(its, list) else []
    if not srcs:
        srcs = [u]
    n, b = [0] * 5, [0] * 5
    for s in srcs:
        v = _src_numbers(s)
        big = v[0] + v[2] + v[3] + v[4] > 100_000
        tgt = b if big else n
        for i in range(5):
            tgt[i] += v[i]
    return n, b


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                if b.get("type") == "text" or "text" in b:
                    parts.append(str(b.get("text") or ""))
                elif b.get("type") == "tool_result":
                    parts.append(_text_of(b.get("content")))
        return "\n".join(p for p in parts if p)
    return ""


_DENIAL = re.compile(r"permission.{0,40}denied|doesn't want to proceed|was denied|denied by|blocked by .{0,20}hook|"
                     r"hook .{0,30}(blocked|denied)", re.I | re.S)


INJECTED = re.compile(r"<(system-reminder|task-notification|local-command-stdout|local-command-stderr|"
                      r"local-command-caveat|agent-message|side-sessions-event|ci-monitor-event)"
                      r"\b[^>]*>.*?</\1>", re.S)


def _prompt_text(text: str):
    """What the person typed: Claude Code puts its own notes (system reminders, task notifications) in the
    same message, before or after the words; those are removed, and a message with nothing left is no prompt."""
    t = INJECTED.sub("", text or "").strip()
    if not t:
        return None
    m = re.search(r"<command-name>\s*(.*?)\s*</command-name>", t, re.S)
    if m:
        a = re.search(r"<command-args>\s*(.*?)\s*</command-args>", t, re.S)
        return (m.group(1) + " " + (a.group(1) if a else "")).strip()
    if t.startswith(("<command-", "<local-command", "<system-reminder", "<task-notification",
                     "[Request interrupted")):
        return None
    return t


def new_session(sid: str) -> dict:
    return {"version": 1, "session": sid, "first_ts": "", "last_ts": "", "prompts": [], "turns": 0,
            "tools": {}, "tool_errors": {}, "tool_ids": {}, "errors": [], "error_counts": {}, "usage": {},
            "msg_ids": [], "cost_state": None, "agents": [], "redactions": {}, "recorder_errors": [],
            "prompts_included": False}


def add_error(S: dict, kind: str, tool: str, text, tss: str, label: str) -> None:
    S["error_counts"][kind] = S["error_counts"].get(kind, 0) + 1
    if len(S["errors"]) < CAP_ERRORS:
        S["errors"].append({"kind": kind, "tool": redact(tool), "text": short(text), "ts": tss, "agent": label})


def _flag_errors(S: dict, rec: dict, label: str, tss: str) -> None:
    if rec.get("toolDenialKind"):
        add_error(S, "denial", "", f"{rec.get('toolDenialKind')} {rec.get('permissionDecisionReason') or ''}", tss, label)
    pd = rec.get("permissionDecision")
    if isinstance(pd, dict):
        pd = pd.get("behavior") or pd.get("decision")
    if isinstance(pd, str) and pd.lower() == "deny":
        add_error(S, "denial", "", rec.get("permissionDecisionReason") or "permission denied", tss, label)
    he = rec.get("hookErrors")
    if he:
        add_error(S, "hook", "", json.dumps(he, ensure_ascii=False) if not isinstance(he, str) else he, tss, label)
    if rec.get("isApiErrorMessage") or rec.get("apiError"):
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
        txt = _text_of(msg.get("content")) or json.dumps(rec.get("apiError"), ensure_ascii=False, default=str)
        add_error(S, "api", "", txt, tss, label)


def handle(S: dict, rec: dict, label: str, since, keep_prompts: bool) -> None:
    t = rec.get("type")
    if not isinstance(t, str) or t in SKIP_TYPES or t.startswith("file-history"):
        return
    ts = parse_ts(rec.get("timestamp"))
    if ts is None or ts < since:
        return
    tss = ts.astimezone(timezone.utc).isoformat(timespec="seconds")
    if not S["first_ts"] or tss < S["first_ts"]:
        S["first_ts"] = tss
    if tss > S["last_ts"]:
        S["last_ts"] = tss
    _flag_errors(S, rec, label, tss)
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
    content = msg.get("content")
    if t == "user":
        text = ""
        if isinstance(content, list):
            results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            for b in results:
                if b.get("is_error"):
                    tool = S["tool_ids"].get(str(b.get("tool_use_id")), "unknown")
                    body = _text_of(b.get("content"))
                    kind = "denial" if _DENIAL.search(body) else "tool_error"
                    S["tool_errors"][tool] = S["tool_errors"].get(tool, 0) + 1
                    add_error(S, kind, tool, body, tss, label)
            if results:
                return
            text = _text_of(content)
        elif isinstance(content, str):
            text = content
        if label != "main" or rec.get("isMeta"):
            return
        p = _prompt_text(text)
        if p is not None:
            S["prompts"].append({"ts": tss, "chars": len(p), "text": short(p, 100000) if keep_prompts else None})
    elif t == "assistant":
        if rec.get("isApiErrorMessage"):
            return
        mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
        if mid and mid not in S["msg_ids"]:
            S["msg_ids"].append(mid)
            S["turns"] += 1
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    tid, name = str(b.get("id")), redact(b.get("name") or "unknown")
                    if tid not in S["tool_ids"]:
                        S["tool_ids"][tid] = name
                        S["tools"][name] = S["tools"].get(name, 0) + 1
        model, u = msg.get("model"), msg.get("usage")
        if mid and isinstance(model, str) and model != "<synthetic>" and isinstance(u, dict):
            n, b = usage_buckets(u)
            old = S["usage"].get(mid)
            if old:
                n = [max(x, y) for x, y in zip(n, old["n"])]
                b = [max(x, y) for x, y in zip(b, old["b"])]
            S["usage"][mid] = {"m": redact(model), "a": label, "n": n, "b": b,
                               "geo": u.get("inference_geo") if isinstance(u.get("inference_geo"), str) else None,
                               "speed": u.get("speed") if isinstance(u.get("speed"), str) else None}
    elif t == "cost-state":
        models = rec.get("modelUsage")
        S["cost_state"] = {"ts": tss, "total": rec.get("totalCostUSD") if isinstance(rec.get("totalCostUSD"), (int, float)) else None,
                           "models": {redact(k): v.get("costUSD") for k, v in models.items()
                                      if isinstance(v, dict) and isinstance(v.get("costUSD"), (int, float))}
                           if isinstance(models, dict) else {}}


def _key(path: Path) -> str:
    return hashlib.sha1(str(path).encode("utf-8", "replace")).hexdigest()[:16]


def ingest(S: dict, path: Path, label: str, since, state: dict, keep_prompts: bool) -> None:
    files = state.setdefault("files", {})
    k = _key(path)
    off = _num(files.get(k))
    size = path.stat().st_size
    if size < off:
        off = 0
    if size == off:
        return
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read()
    end = data.rfind(b"\n")
    if end < 0:
        return
    for line in data[:end + 1].split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        try:
            handle(S, rec, label, since, keep_prompts)
        except Exception as e:  # defensive: never stop on one odd record
            if len(S["recorder_errors"]) < 20:
                S["recorder_errors"].append(short(f"{type(e).__name__}: {e}"))
    files[k] = off + end + 1


def _safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)[:100] or "session"


def record(proj, session_id: str, transcript) -> None:
    c = consent(proj)
    if not c["on"]:
        return
    since = parse_ts(c["since"]) or datetime.fromtimestamp(0, timezone.utc)
    tpath = Path(transcript)
    sid = _safe_id(session_id or tpath.stem)
    d = diag_dir(proj, True)
    sf = d / "sessions" / f"{sid}.json"
    S = _read_json(sf, {}) or new_session(sid)
    for k, v in new_session(sid).items():
        S.setdefault(k, v)
    state = _read_json(d / "state.json", {})
    before = Counter(_COUNTS)
    try:
        S["prompts_included"] = c["prompts"]
        todo = []
        if tpath.is_file():
            todo.append((tpath, "main"))
        sub = tpath.with_suffix("") / "subagents"
        if sub.is_dir():
            for a in sorted(sub.glob("agent-*.jsonl")):
                label = "subagent"
                meta = _read_json(a.with_name(a.name[:-len(".jsonl")] + ".meta.json"), {})
                for key in ("agentType", "agent_type", "subagent_type", "type"):
                    if isinstance(meta.get(key), str) and meta[key]:
                        label = redact(meta[key])
                        break
                if label not in S["agents"]:
                    S["agents"].append(label)
                todo.append((a, label))
        for p, label in todo:
            ingest(S, p, label, since, state, c["prompts"])
    except Exception as e:
        S["recorder_errors"].append(short(f"{type(e).__name__}: {e}"))
    for kind, n in (Counter(_COUNTS) - before).items():
        S["redactions"][kind] = S["redactions"].get(kind, 0) + n
    S["recorder_errors"] = S["recorder_errors"][-20:]
    _write_json(sf, S)
    _write_json(d / "state.json", state)


# ------------------------------------------------------------------ report
def load_sessions(proj) -> list:
    out = []
    for p in sorted((diag_dir(proj) / "sessions").glob("*.json")):
        S = _read_json(p, {})
        if S.get("session"):
            out.append(S)
    out.sort(key=lambda s: s.get("first_ts") or "")
    return out


def _sum5(a, b):
    return [x + y for x, y in zip(a, b)]


def _agg_usage(recs) -> dict:
    """Group request records into {requests, tokens[5], cost}; cost None if any record's model is unpriced."""
    tot = {"requests": 0, "tok": [0] * 5, "cost": 0.0, "unknown": False, "nonstandard": 0}
    for r in recs:
        tot["requests"] += 1
        tot["tok"] = _sum5(tot["tok"], _sum5(r["n"], r["b"]))
        if nonstandard(r):  # tokens counted, cost unknown: the price differs and is not guessed
            tot["nonstandard"] += 1
            tot["unknown"] = True
            continue
        c = usage_cost(r["m"], r["n"], r["b"])
        if c is None:
            tot["unknown"] = True
        else:
            tot["cost"] += c
    return tot


def _cost_val(t):
    return None if t["unknown"] else t["cost"]


def fmt_cost(x) -> str:
    return "unknown" if x is None else f"${x:.4f}"


def _cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def table(head, rows):
    return _md_table(head, [[_cell(c) for c in r] for r in rows])


def _gate_rows(node, out):
    if isinstance(node, dict):
        st = node.get("status")
        if isinstance(st, str):
            if st.strip().lower().replace("_", " ") not in ("pass", "note", "not run"):
                name = node.get("name") or node.get("check") or node.get("id") or node.get("stage") or "?"
                out.append({"name": short(name, 120), "status": short(st, 40),
                            "detail": short(node.get("detail") or node.get("message") or "", 200)})
        for v in node.values():
            if isinstance(v, (dict, list)):
                _gate_rows(v, out)
    elif isinstance(node, list):
        for v in node:
            _gate_rows(v, out)


def failed_gates(proj) -> list:
    p = Path(proj) / "reports" / "gates.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    out: list = []
    _gate_rows(data, out)
    return out[:50]


def project_stage(proj) -> str:
    plan = HERE / "plan.py"
    if not plan.is_file():
        return ""
    try:
        r = subprocess.run([sys.executable, str(plan), str(Path(proj).resolve())], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20, cwd=str(proj))
        for line in r.stdout.splitlines():
            if line.strip():
                return short(line.strip(), 300)
    except Exception:
        pass
    return ""


def build_report(proj) -> dict:
    proj = Path(proj)
    c = consent(proj)
    sessions = load_sessions(proj)
    _COUNTS.clear()
    all_recs, per_session = [], []
    tools: dict = {}
    err_kinds: dict = {}
    redactions: Counter = Counter()
    prompts = []
    cc_total, cc_models, cc_any = 0.0, Counter(), False
    for S in sessions:
        recs = list(S["usage"].values())
        all_recs += recs
        est = _agg_usage(recs)
        main = _agg_usage([r for r in recs if r["a"] == "main"])
        subs = _agg_usage([r for r in recs if r["a"] != "main"])
        cs = S.get("cost_state") or {}
        if cs.get("total") is not None:
            cc_any = True
            cc_total += cs["total"]
            for m, v in (cs.get("models") or {}).items():
                cc_models[m] += v
        for name, n in S["tools"].items():
            tools.setdefault(name, [0, 0])[0] += n
        for name, n in S["tool_errors"].items():
            tools.setdefault(name, [0, 0])[1] += n
        for e in S["errors"]:
            k = err_kinds.setdefault(e["kind"], {"count": 0, "example": None})
            if k["example"] is None:
                k["example"] = e
        for kind, n in S["error_counts"].items():
            err_kinds.setdefault(kind, {"count": 0, "example": None})["count"] += n
        for kind, n in (S.get("redactions") or {}).items():
            redactions[kind] += n
        for p in S["prompts"]:
            prompts.append({"session": S["session"][:8], "ts": p["ts"], "chars": p["chars"],
                            "text": p["text"] if c["prompts"] else None})
        per_session.append({
            "id": S["session"], "from": S["first_ts"], "to": S["last_ts"], "prompts": len(S["prompts"]),
            "turns": S["turns"], "tool_calls": sum(S["tools"].values()), "errors": sum(S["error_counts"].values()),
            "requests": est["requests"], "cost_estimate_usd": _cost_val(est), "cost_main_usd": _cost_val(main),
            "cost_subagents_usd": _cost_val(subs), "cost_claude_code_usd": cs.get("total"),
            "recorder_errors": len(S["recorder_errors"])})
    models: dict = {}
    for m in sorted({r["m"] for r in all_recs}):
        rs = [r for r in all_recs if r["m"] == m]
        t = _agg_usage(rs)
        models[m] = {"requests": t["requests"], "input": t["tok"][0], "output": t["tok"][1],
                     "cache_write": t["tok"][2] + t["tok"][3], "cache_write_1h": t["tok"][3], "cache_read": t["tok"][4],
                     "cost_usd": _cost_val(t), "claude_code_usd": cc_models.get(m),
                     "nonstandard_requests": t["nonstandard"],
                     "speed": dict(Counter(r["speed"] for r in rs if r.get("speed"))),
                     "inference_geo": dict(Counter(r["geo"] for r in rs if r.get("geo")))}
    agents: dict = {}
    for a in sorted({r["a"] for r in all_recs}):
        t = _agg_usage([r for r in all_recs if r["a"] == a])
        agents[a] = {"requests": t["requests"], "input": t["tok"][0], "output": t["tok"][1],
                     "cache_write": t["tok"][2] + t["tok"][3], "cache_read": t["tok"][4], "cost_usd": _cost_val(t)}
    total = _agg_usage(all_recs)
    unknown_models = sorted({r["m"] for r in all_recs if price_for(r["m"]) is None})
    # findings
    findings = []
    texts: Counter = Counter()
    sample = {}
    for S in sessions:
        for e in S["errors"]:
            k = (e["kind"], re.sub(r"\d+", "N", e["text"])[:200])
            texts[k] += 1
            sample.setdefault(k, e["text"])
    for k, n in texts.most_common():
        if n >= 3 and k[1].strip():
            findings.append(f"The same {k[0].replace('_', ' ')} appeared {n} times: {sample[k][:120]}")
    for name, (calls, errs) in sorted(tools.items()):
        if calls >= 3 and errs / calls > 0.30:
            findings.append(f"Tool {name} failed {errs} of {calls} calls ({100 * errs // calls}%)")
    per_prompt = [(s["id"], (s["cost_estimate_usd"] or 0) / s["prompts"]) for s in per_session
                  if s["prompts"] and s["cost_estimate_usd"]]
    if len(per_prompt) >= 2:
        med = statistics.median(v for _, v in per_prompt)
        for sid, v in per_prompt:
            if med > 0 and v > 3 * med:
                findings.append(f"Session {sid[:8]} cost {fmt_cost(v)} per prompt, more than 3x the median {fmt_cost(med)}")
    for s in per_session:
        if s["cost_subagents_usd"] and s["cost_subagents_usd"] > (s["cost_main_usd"] or 0):
            findings.append(f"In session {s['id'][:8]} the subagents cost {fmt_cost(s['cost_subagents_usd'])}, "
                            f"more than the main session ({fmt_cost(s['cost_main_usd'])})")
    gates = failed_gates(proj)
    stage = project_stage(proj)
    for kind, n in _COUNTS.items():
        redactions[kind] += n
    first = min((s["from"] for s in per_session if s["from"]), default="")
    last = max((s["to"] for s in per_session if s["to"]), default="")
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "consent": {k: c[k] for k in ("on", "prompts", "since")},
        "period": {"from": first, "to": last},
        "cost_label": COST_LABEL,
        "totals": {"sessions": len(sessions), "prompts": sum(s["prompts"] for s in per_session),
                   "turns": sum(s["turns"] for s in per_session), "requests": total["requests"],
                   "nonstandard_requests": total["nonstandard"], "tool_calls": sum(s["tool_calls"] for s in per_session), "errors": sum(s["errors"] for s in per_session),
                   "input": total["tok"][0], "output": total["tok"][1], "cache_write": total["tok"][2] + total["tok"][3],
                   "cache_read": total["tok"][4], "cost_estimate_usd": _cost_val(total),
                   "cost_claude_code_usd": cc_total if cc_any else None, "unknown_models": unknown_models},
        "sessions": per_session,
        "models": models,
        "agents": agents,
        "tools": {n: {"calls": v[0], "errors": v[1]} for n, v in sorted(tools.items())},
        "errors": {k: {"count": v["count"], "tool": (v["example"] or {}).get("tool", ""),
                       "example": (v["example"] or {}).get("text", "")} for k, v in sorted(err_kinds.items())},
        "failed_gates": gates,
        "stage": stage,
        "prompts": prompts,
        "findings": findings,
        "redactions": dict(redactions),
    }


KIND_NAMES = {"tool_error": "Tool error", "denial": "Hook / permission denial", "hook": "Hook error", "api": "API error"}


SUMMARY_HEAD = "## Summary in plain words"
PLACEHOLDER = "_Not written yet._"


def kept_summary(md_path: Path):
    """The text Claude wrote under 'Summary in plain words' in an existing report.md, or None when the
    section is missing, empty or still the placeholder."""
    try:
        old = md_path.read_text("utf-8")
    except OSError:
        return None
    i = old.find(SUMMARY_HEAD)
    if i < 0:
        return None
    body = old[i + len(SUMMARY_HEAD):]
    m = re.search(r"^Generated \S+\. Period covered:", body, re.M) or re.search(r"^## ", body, re.M)
    if m:
        body = body[:m.start()]
    body = body.strip()
    if not body or PLACEHOLDER in body or "<!-- CLAUDE:" in body:
        return None
    return body


def render_md(R: dict, summary=None) -> list:
    t = R["totals"]
    if summary:
        summ = ["", redact(summary), ""]
    else:
        summ = ["",
                "<!-- CLAUDE: write 5 to 8 plain sentences here for the person who reads this report: what the work",
                "     was, what went wrong or was slow, what it cost, and what you would change. Then delete this comment. -->",
                "", PLACEHOLDER, ""]
    L = ["# Boardwright diagnostics", "", SUMMARY_HEAD] + summ + [
         f"Generated {R['generated']}. Period covered: {R['period']['from'] or 'nothing recorded'} to {R['period']['to'] or '-'}. "
         f"Project stage: {R['stage'] or 'unknown'}.", "",
         f"Prompts are {'included' if R['consent']['prompts'] else 'NOT included (only their count and length)'}. "
         f"Cost: {R['cost_label']}.", "", "## Totals", ""]
    L += table(["Sessions", "Prompts", "Turns", "API requests", "Tool calls", "Errors", "Cost est. (USD)", "Claude Code's own figure"],
               [[t["sessions"], t["prompts"], t["turns"], t["requests"], t["tool_calls"], t["errors"],
                 fmt_cost(t["cost_estimate_usd"]), fmt_cost(t["cost_claude_code_usd"]) if t["cost_claude_code_usd"] is not None else "-"]])
    if t.get("nonstandard_requests"):
        L += ["", f"{t['nonstandard_requests']} requests in fast mode / US-only inference: cost not estimated (different price)"]
    if t["unknown_models"]:
        L += ["", "Models not in the price table (tokens counted, cost unknown): " + ", ".join(t["unknown_models"])]
    L += ["", "## Per session", ""]
    L += table(["Session", "From", "Prompts", "Turns", "Tool calls", "Errors", "Cost est. (USD)", "Claude Code's figure"],
               [[s["id"][:8], s["from"], s["prompts"], s["turns"], s["tool_calls"], s["errors"],
                 fmt_cost(s["cost_estimate_usd"]), fmt_cost(s["cost_claude_code_usd"]) if s["cost_claude_code_usd"] is not None else "-"]
                for s in R["sessions"]])
    L += ["", "## Models", ""]
    L += table(["Model", "Requests", "Input", "Output", "Cache write", "Cache read", "Cost est. (USD)", "Claude Code's figure"],
               [[m, f"{v['requests']:,}", f"{v['input']:,}", f"{v['output']:,}", f"{v['cache_write']:,}", f"{v['cache_read']:,}",
                 fmt_cost(v["cost_usd"]), fmt_cost(v["claude_code_usd"]) if v["claude_code_usd"] is not None else "-"]
                for m, v in R["models"].items()])
    L += ["", "## Agents (main session and each subagent type)", ""]
    L += table(["Agent", "Requests", "Input", "Output", "Cache write", "Cache read", "Cost est. (USD)"],
               [[a, f"{v['requests']:,}", f"{v['input']:,}", f"{v['output']:,}", f"{v['cache_write']:,}",
                 f"{v['cache_read']:,}", fmt_cost(v["cost_usd"])] for a, v in R["agents"].items()])
    L += ["", "## Tools", ""]
    L += table(["Tool", "Calls", "Errors", "Error rate"],
               [[n, v["calls"], v["errors"], f"{100 * v['errors'] // v['calls']}%" if v["calls"] else "-"]
                for n, v in sorted(R["tools"].items(), key=lambda kv: -kv[1]["calls"])])
    L += ["", "## Errors", ""]
    if R["errors"]:
        L += table(["Kind", "Count", "Tool", "First example"],
                   [[KIND_NAMES.get(k, k), v["count"], v["tool"], v["example"]] for k, v in R["errors"].items()])
    else:
        L += ["No errors recorded."]
    L += ["", "## Failed gates", ""]
    if R["failed_gates"]:
        L += table(["Gate", "Status", "Detail"], [[g["name"], g["status"], g["detail"]] for g in R["failed_gates"]])
    else:
        L += ["None found (or reports/gates.json does not exist)."]
    L += ["", "## Findings", ""]
    L += [f"- {f}" for f in R["findings"]] or ["Nothing stood out by the simple rules (repeated errors, tools failing "
                                              "over 30%, expensive sessions, subagents costing more than the main session)."]
    L += ["", "## Prompts", ""]
    if R["consent"]["prompts"]:
        L += [f"{len(R['prompts'])} prompts.", ""]
        L += [f"{i}. `{p['ts']}` (session {p['session']}): {(p['text'] or '').strip()}" for i, p in enumerate(R["prompts"], 1)]
    else:
        L += [f"{len(R['prompts'])} prompts; their text was not recorded.", "",
              "Lengths in characters: " + ", ".join(str(p["chars"]) for p in R["prompts"])]
    L += ["", "## Redactions", ""]
    L += [", ".join(f"{k}: {n}" for k, n in sorted(R["redactions"].items())) or "Nothing needed redacting."]
    return L


def cmd_report(proj) -> Path:
    R = build_report(proj)
    d = diag_dir(proj, True)
    _write_json(d / "report.json", R)
    summary = kept_summary(d / "report.md")
    (d / "report.md").write_text("\n".join(render_md(R, summary)).rstrip() + "\n", "utf-8")
    return d / "report.md"


# ------------------------------------------------------------------ export, delete, status
def send_instructions(zip_path=None) -> str:
    lines = [f"File: {zip_path}" if zip_path else "File: (not exported yet)",
             "Nothing has been sent. Read report.md first: it may contain your prompts and part names.", "",
             "Two ways to send it:",
             f"  1. GitHub issue form: {ISSUE_URL}",
             "     Warning: issues and attachments on a public repository are readable by anyone.",
             ]
    email = ""
    cfg = _read_json(HERE / "diagnostics.json", {}) or _read_json(HERE.parent / "diagnostics.json", {})
    if isinstance(cfg.get("email"), str):
        email = cfg["email"].strip()
    lines.append(f"  2. E-mail to {email} (attach the zip yourself)." if email else "  2. E-mail is not set up for this plugin.")
    text = "\n".join(lines)
    print(text)
    return text


def _kicad_version() -> str:
    try:
        from run_gates import find_kicad_cli
        r = subprocess.run([find_kicad_cli() or "kicad-cli", "version"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else "unavailable"
    except Exception:
        return "unavailable"


def _bw_version() -> str:
    d = _read_json(HERE.parent / ".claude-plugin" / "plugin.json", {})
    if not d and os.environ.get("CLAUDE_PLUGIN_ROOT"):
        d = _read_json(Path(os.environ["CLAUDE_PLUGIN_ROOT"]) / ".claude-plugin" / "plugin.json", {})
    return str(d.get("version") or "unknown")


def cmd_export(proj) -> Path:
    cmd_report(proj)
    d = diag_dir(proj, True)
    c = consent(proj)
    sessions = sorted((d / "sessions").glob("*.json"))
    zp = d / f"boardwright-diagnostics-{time.strftime('%Y%m%d-%H%M')}.zip"
    manifest = {
        "boardwright_version": _bw_version(), "os": redact(platform.platform()), "python": platform.python_version(),
        "kicad": redact(_kicad_version()), "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "included": {"report.md": True, "report.json": True, "sessions": len(sessions), "prompt_text": c["prompts"],
                     "tool_errors_and_denials": True, "model_usage_and_cost": True},
        "consent": {"on": c["on"], "prompts": c["prompts"], "since": c["since"], "typed": redact(c["typed"])},
    }
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(d / "report.md", "report.md")
        z.write(d / "report.json", "report.json")
        for p in sessions:
            S = _read_json(p, {})
            if not c["prompts"]:
                for pr in S.get("prompts", []):
                    pr["text"] = None
            z.writestr(f"sessions/{p.name}", json.dumps(S, indent=1, ensure_ascii=False))
        z.writestr("manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"Exported: {zp}")
    print(f"Size: {zp.stat().st_size:,} bytes")
    send_instructions(zp)
    return zp


def cmd_delete(proj) -> None:
    d = diag_dir(proj)
    removed = []
    for p in sorted((d / "sessions").glob("*")) if (d / "sessions").is_dir() else []:
        p.unlink()
        removed.append(f"sessions/{p.name}")
    if (d / "sessions").is_dir():
        (d / "sessions").rmdir()
    for pat in ("report.md", "report.json", "state.json", "boardwright-diagnostics-*.zip"):
        for p in sorted(d.glob(pat)):
            p.unlink()
            removed.append(p.name)
    print("Removed: " + (", ".join(removed) if removed else "nothing (no recordings found)")
          + ". The consent setting was kept.")


def _dir_size(d: Path) -> int:
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) if d.is_dir() else 0


def cmd_status(proj) -> None:
    c = consent(proj)
    d = diag_dir(proj)
    n = len(list((d / "sessions").glob("*.json"))) if (d / "sessions").is_dir() else 0
    print(f"Diagnostics: {'ON since ' + c['since'] if c['on'] else 'OFF (nothing is recorded)'}")
    print("Included: model names, token counts and cost estimates, tool names, tool errors and permission denials, "
          "failed gates, " + ("your prompts (redacted)." if c["prompts"] else "the number and length of your prompts (not their text)."))
    print("Never included: file contents, tool outputs, API request bodies. Secrets, e-mail addresses and your user name are redacted.")
    print(f"Sessions recorded: {n}")
    print(f"Total size: {_dir_size(d):,} bytes")


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    proj, cmd, args = Path(argv[0]).resolve(), argv[1], argv[2:]
    if cmd == "record":
        try:
            def opt(name):
                return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""
            tr = opt("--transcript")
            if tr:
                record(proj, opt("--session"), tr)
        except Exception:
            pass
        return 0
    if not proj.is_dir():
        print("not a folder: " + str(proj))
        return 2
    if cmd == "status":
        cmd_status(proj)
    elif cmd == "report":
        p = cmd_report(proj)
        print(f"Report: {p} ({p.stat().st_size:,} bytes)")
    elif cmd == "export":
        cmd_export(proj)
    elif cmd == "delete":
        cmd_delete(proj)
    else:
        print("unknown command " + cmd)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
