#!/usr/bin/env python3
"""Boardwright for KiCad - everything that is not GUI.  Standard library only.

  * finding the user's own Claude Code CLI
  * first-run checks (installed? signed in? boardwright plugin installed?)
  * starting Claude Code's own sign-in
  * one long-lived Claude Code process per chat, spoken to over its
    stream-json protocol (the same one the Claude Agent SDK and the VS Code
    extension use): streamed text, tool-use lines, permission requests, stop.

Rule for this file: it never asks for, reads, stores or forwards a password,
API key or token.  Sign-in is always `claude auth login`, Claude Code's own
browser flow, in Claude Code's own window.  From `claude auth status` only the
two fields `loggedIn` and `authMethod` are kept; the rest is thrown away.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

APP_NAME = "Boardwright"
HERE = Path(__file__).resolve().parent

INSTALL_DOCS_URL = "https://code.claude.com/docs/en/setup"
REPO_URL = "https://github.com/Pratham7767/Boardwright"
# Official install commands, from the page above (read 2026-11-15).
INSTALL_COMMANDS = {
    "win32": "irm https://claude.ai/install.ps1 | iex",
    "darwin": "curl -fsSL https://claude.ai/install.sh | bash",
    "linux": "curl -fsSL https://claude.ai/install.sh | bash",
}
PLUGIN_NAME = "boardwright"
PLUGIN_ID = "boardwright@boardwright"
# A copy of the boardwright Claude Code plugin ships inside this add-on as a
# zip laid out as a local marketplace (.claude-plugin/marketplace.json +
# plugin/).  It must stay zipped: KiCad searches the add-on folder for every
# file named plugin.json and refuses the whole add-on when it meets Claude
# Code's .claude-plugin/plugin.json.  It is unpacked on first use.
BUNDLE_ZIP = HERE / "claude-plugin.zip"


def bundle_dir() -> Optional[Path]:
    """Unpacked copy of the bundled Claude Code plugin, or None if not shipped."""
    if not BUNDLE_ZIP.is_file():
        return None
    import zipfile
    tag = hashlib.sha256(BUNDLE_ZIP.read_bytes()).hexdigest()[:12]
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "Boardwright" / f"claude-plugin-{tag}"
    if not (root / ".claude-plugin" / "marketplace.json").is_file():
        tmp = root.with_name(root.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(BUNDLE_ZIP) as z:
            for name in z.namelist():                   # refuse odd paths
                if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                    raise ValueError(f"bad path in {BUNDLE_ZIP.name}: {name}")
            z.extractall(tmp)
        shutil.rmtree(root, ignore_errors=True)
        tmp.rename(root)
    return root

SYSTEM_NOTE = (
    "You are running in the Boardwright chat window opened from KiCad's PCB Editor; "
    "the working directory is the folder of the KiCad project that is open. "
    "The user sees your text, one line per tool call, and Allow/Deny buttons for "
    "permission requests. Keep answers short and plain; the user may be new to PCB "
    "design. Never order, upload or publish anything."
)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# --------------------------------------------------------------------------
# Finding things
# --------------------------------------------------------------------------

def find_claude(override: Optional[str] = None) -> Optional[str]:
    """Path of the `claude` executable, or None.

    Order: explicit override, BOARDWRIGHT_CLAUDE, PATH, then the places the
    official installers use (~/.local/bin, %APPDATA%\\npm)."""
    for cand in (override, os.environ.get("BOARDWRIGHT_CLAUDE")):
        if cand:
            if Path(cand).is_file():
                return str(cand)
            hit = shutil.which(cand)
            if hit:
                return hit
    hit = shutil.which("claude")
    if hit:
        return hit
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    places = [home / ".local" / "bin"]
    if os.environ.get("APPDATA"):
        places.append(Path(os.environ["APPDATA"]) / "npm")
    for d in places:
        for name in ("claude.exe", "claude.cmd", "claude"):
            if (d / name).is_file():
                return str(d / name)
    return None


def find_kicad_cli() -> Optional[str]:
    """kicad-cli of the KiCad that started us (it sits beside KiCad's python)."""
    env = os.environ.get("KICAD_CLI")
    if env and Path(env).is_file():
        return env
    names = ("kicad-cli.exe", "kicad-cli")
    dirs = [Path(getattr(sys, "base_prefix", sys.prefix)),
            Path(getattr(sys, "base_executable", sys.executable)).parent,
            Path(sys.executable).parent]
    for d in dirs:
        for n in names:
            if (d / n).is_file():
                return str(d / n)
    return shutil.which("kicad-cli")


def child_env() -> dict:
    """Environment for Claude Code: ours, plus KICAD_CLI so the kicad-live MCP
    server finds kicad-cli (it does not look beside KiCad on its own)."""
    env = os.environ.copy()
    cli = find_kicad_cli()
    if cli and not env.get("KICAD_CLI"):
        env["KICAD_CLI"] = cli
    return env


def run_quiet(argv: list, timeout: float = 60, cwd: Optional[str] = None):
    """Run a short command with no console window. -> (exit code, stdout, stderr)."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env=child_env(),
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout:.0f} s"
    except OSError as exc:
        return -2, "", str(exc)


def _json_from(text: str):
    """First JSON value in `text` (the CLI may print a notice before it)."""
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return json.JSONDecoder().raw_decode(text[i:])[0]
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------
# First-run checks
# --------------------------------------------------------------------------

def check_claude(override: Optional[str] = None) -> dict:
    path = find_claude(override)
    if not path:
        return {"ok": False, "path": None, "version": None}
    code, out, err = run_quiet([path, "--version"], timeout=30)
    return {"ok": code == 0, "path": path, "version": (out or err).strip().splitlines()[0] if (out or err).strip() else None}


def check_auth(claude: str) -> dict:
    """Signed in?  Uses `claude auth status --json` and keeps two fields only."""
    code, out, err = run_quiet([claude, "auth", "status", "--json"], timeout=30)
    data = _json_from(out) or _json_from(err)
    if not isinstance(data, dict):
        return {"ok": False, "known": False, "method": None,
                "detail": (err or out).strip()[:200] or f"exit code {code}"}
    return {"ok": bool(data.get("loggedIn")), "known": True,
            "method": str(data.get("authMethod") or "none"), "detail": ""}


def check_plugin(claude: str) -> dict:
    """Is the boardwright Claude Code plugin installed and enabled for this user?"""
    code, out, err = run_quiet([claude, "plugin", "list", "--json"], timeout=60)
    data = _json_from(out)
    if not isinstance(data, list):
        return {"ok": False, "known": False, "installed": False, "enabled": False,
                "version": None, "detail": (err or out).strip()[:200] or f"exit code {code}"}
    for item in data:
        if isinstance(item, dict) and str(item.get("id", "")).split("@")[0] == PLUGIN_NAME:
            en = bool(item.get("enabled", True))
            return {"ok": en, "known": True, "installed": True, "enabled": en,
                    "version": item.get("version"), "id": item.get("id"), "detail": ""}
    return {"ok": False, "known": True, "installed": False, "enabled": False,
            "version": None, "detail": ""}


def bundle_available() -> bool:
    try:
        d = bundle_dir()
    except Exception:
        return False
    return d is not None and (d / "plugin" / ".claude-plugin" / "plugin.json").is_file()


def _version_tuple(v) -> Optional[tuple]:
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("v").split("-")[0].split("+")[0].split("."))
    except ValueError:
        return None


def bundle_version() -> Optional[str]:
    """Version of the plugin that came with this add-on (from its plugin.json), or None."""
    try:
        d = bundle_dir()
        if d is None:
            return None
        data = json.loads((d / "plugin" / ".claude-plugin" / "plugin.json").read_text("utf-8"))
        return str(data.get("version")) if data.get("version") else None
    except (OSError, ValueError):
        return None


def is_older(installed, bundled) -> bool:
    """True when the installed plugin version is strictly older than the bundled one (unknown -> False)."""
    a, b = _version_tuple(installed), _version_tuple(bundled)
    return bool(a and b and a < b)


PLUGIN_UPDATE_COMMAND = "claude plugin update " + PLUGIN_ID


def plugin_install_commands(claude: str = "claude") -> list:
    """The two commands that install the bundled boardwright plugin for this user."""
    return [[claude, "plugin", "marketplace", "add", str(bundle_dir())],
            [claude, "plugin", "install", PLUGIN_ID]]


def install_plugin(claude: str) -> tuple:
    """Run the two commands above. -> (ok, text to show)."""
    lines = []
    for argv in plugin_install_commands(claude):
        code, out, err = run_quiet(argv, timeout=180)
        lines.append("> " + " ".join(argv[1:]))
        lines.append((out + err).strip() or f"(exit code {code})")
        if code != 0 and "already" not in (out + err).lower():
            return False, "\n".join(lines)
    return True, "\n".join(lines)


def check_helpers() -> list:
    """Programs the boardwright MCP servers start. Informational: the chat works
    without them, but Claude then has no KiCad tools."""
    rows = []
    for exe, why in (("kicad-buddy", "live link to the open board (kicad-live tools)"),
                     ("uvx", "starts the kicad-schematic tools")):
        ok = shutil.which(exe) is not None or             (Path.home() / ".local" / "bin" / (exe + (".exe" if os.name == "nt" else ""))).is_file()
        rows.append({"name": exe, "ok": ok, "why": why})
    cli = find_kicad_cli()
    rows.append({"name": "kicad-cli", "ok": cli is not None, "why": cli or "ERC/DRC and exports"})
    return rows


def run_all_checks(override: Optional[str] = None) -> dict:
    """Everything the Setup panel shows. Slow part is two CLI calls (about 2 s)."""
    c = check_claude(override)
    res = {"claude": c, "auth": None, "plugin": None, "helpers": check_helpers(),
           "bundle": bundle_available(), "engine": check_engine()}
    if c["ok"]:
        res["auth"] = check_auth(c["path"])
        res["plugin"] = check_plugin(c["path"])
        bv = bundle_version() if res["bundle"] else None
        res["plugin"]["bundle_version"] = bv
        res["plugin"]["older"] = bool(res["plugin"].get("installed") and is_older(res["plugin"].get("version"), bv))
    res["ready"] = bool(c["ok"] and res["auth"] and res["auth"]["ok"])
    return res


def engine_dir() -> Path:
    """Where the routing engine (Java, Freerouting, KiCadRoutingTools) is installed; the same rule as the
    plugin's scripts/engine.py."""
    if os.environ.get("BOARDWRIGHT_ENGINE_DIR"):
        return Path(os.environ["BOARDWRIGHT_ENGINE_DIR"])
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Boardwright" / "engine"
    return Path.home() / ".local" / "share" / "boardwright" / "engine"


def check_engine() -> dict:
    """{'ok': bool, 'detail': str}: ok when engine.json is there and every path it names exists."""
    f = engine_dir() / "engine.json"
    try:
        data = json.loads(f.read_text("utf-8-sig"))     # PowerShell writes a byte-order mark
    except (OSError, ValueError):
        return {"ok": False, "detail": "not installed"}
    if not isinstance(data, dict):
        return {"ok": False, "detail": "engine.json is not readable"}
    missing = [k for k in ("java", "freerouting_jar", "krt", "krt_python")
               if not data.get(k) or not Path(str(data[k])).exists()]
    return {"ok": not missing, "detail": ("missing: " + ", ".join(missing)) if missing else str(engine_dir())}


def engine_downloads_text() -> str:
    return ("This downloads a Java runtime (Eclipse Temurin 25, about 50 MB), Freerouting 2.5.0 (about 20 MB) "
            "and KiCadRoutingTools 0.24.1 with its Python packages (about 150 MB). Each download is checked "
            "against a fixed checksum. Everything goes into " + str(engine_dir()) + " and nothing else on "
            "your computer is changed.")


def start_engine_setup() -> Optional[str]:
    """Run the plugin's setup_engine script in its own console window. -> error text, or None."""
    if not bundle_available():
        return "this copy of the add-on has no bundled plugin; run the plugin's scripts/setup_engine script by hand"
    scripts = bundle_dir() / "plugin" / "scripts"
    if os.name == "nt":
        return open_in_terminal(["powershell", "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-File",
                                 str(scripts / "setup_engine.ps1")])
    return open_in_terminal(["bash", str(scripts / "setup_engine.sh")])


# --------------------------------------------------------------------------
# The chat's own settings (one small file per user): colours, mode, model, the last chat per project, and
# the user's answer about the usage log. Never a password, key or token.
# --------------------------------------------------------------------------
def _settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Boardwright" / "chat-settings.json"


def settings_get(key: str, default=None):
    try:
        d = json.loads(_settings_path().read_text("utf-8"))
        return d.get(key, default) if isinstance(d, dict) else default
    except (OSError, ValueError):
        return default


def settings_set(key: str, value) -> None:
    f = _settings_path()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            d = json.loads(f.read_text("utf-8"))
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        d[key] = value
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2), "utf-8")
        os.replace(tmp, f)
    except OSError:
        pass


def plugin_scripts() -> Optional[Path]:
    """The bundled plugin's scripts folder (diagnostics.py and the rest), or None."""
    try:
        d = bundle_dir()
    except Exception:
        return None
    return d / "plugin" / "scripts" if d and (d / "plugin" / "scripts").is_dir() else None


def diagnostics_module():
    """The plugin's diagnostics.py as a module, or None."""
    sc = plugin_scripts()
    if not sc or not (sc / "diagnostics.py").is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("bw_diagnostics", sc / "diagnostics.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return mod


def usage_log_decided(project: str) -> bool:
    return (Path(project) / ".boardwright" / "diagnostics" / "consent.json").is_file()


def set_usage_log(project: str, on: bool, prompts: bool, how: str) -> bool:
    """The user's own click in the chat window: the usage log on or off for this project."""
    mod = diagnostics_module()
    if mod is None:
        return False
    try:
        mod.set_consent(Path(project), on, prompts, typed=how)
        return True
    except Exception:
        return False


def usage_log_on(project: str) -> bool:
    mod = diagnostics_module()
    try:
        return bool(mod and mod.consent(Path(project))["on"])
    except Exception:
        return False


def build_report(project: str) -> tuple:
    """(report text or '', note). The plugin's own redacted report of this project's usage log."""
    sc = plugin_scripts()
    if not sc:
        return "", "the plugin copy that came with the add-on was not found"
    code, out, err = run_quiet([console_python(), str(sc / "diagnostics.py"), project, "report"], timeout=120)
    path = None
    for line in out.splitlines():
        if line.startswith("Report: "):
            path = line[len("Report: "):].rsplit(" (", 1)[0].strip()
    if code != 0 or not path or not Path(path).is_file():
        return "", (err or out).strip()[-200:] or "no report was made"
    return Path(path).read_text("utf-8", errors="replace"), path


def feedback_issue_url() -> str:
    """The new-issue page; only a fixed title goes in the address, the text goes on the clipboard."""
    from urllib.parse import quote
    return REPO_URL + "/issues/new?title=" + quote("Feedback from the Boardwright chat") + "&labels=feedback"


# --------------------------------------------------------------------------
# The eight stages, from the stage reports (the row of chips, and which tools to load)
# --------------------------------------------------------------------------
STAGES = (("1", "Spec", "01-spec.md"), ("2", "Parts", "02-parts.md"), ("3", "Power", "03-power.md"),
          ("4", "Schematic", "04-schematic.md"), ("5", "Layout", "05-layout.md"), ("6", "EMC", "06-emc.md"),
          ("7", "BOM", "07-bom.md"), ("8", "Release", "08-release.md"))
_FAIL = re.compile(r"NOT PASSED|Gate[^\n]{0,40}\bFAIL(?:ED)?\b", re.I)


def stage_states(project: str) -> list:
    """[(number, name, state, note)] where state is done, failed, current or pending.

    From the stage reports only: a report that says its gate is NOT PASSED is 'failed', a report that
    exists is 'done', the first stage without a report is 'current'. A rough picture for the strip;
    the pipeline's own status (pcb-run / status.py) is the real one."""
    rep = Path(project) / "reports"
    out = []
    current_set = False
    for num, name, fname in STAGES:
        f = rep / fname
        if f.is_file():
            try:
                text = f.read_text("utf-8", errors="replace")
            except OSError:
                text = ""
            m = _FAIL.search(text)
            if m:
                line = text[max(0, text.rfind("\n", 0, m.start()) + 1):text.find("\n", m.end())]
                out.append((num, name, "failed", re.sub(r"[*#`]", "", line).strip()[:160]))
            else:
                out.append((num, name, "done", "report written: reports/" + fname))
        elif not current_set:
            current_set = True
            out.append((num, name, "current", "next stage"))
        else:
            out.append((num, name, "pending", "not started"))
    return out


def has_started(project: str) -> bool:
    return (Path(project) / "reports" / STAGES[0][2]).is_file() or (Path(project) / "PROJECT.md").is_file()



# The KiCad tool servers (kicad-live for the open board, kicad-schematic for schematic files) add about a
# hundred tool descriptions that Claude Code sends again with every step: measured on the example board, the
# same three questions cost about twice as much with them loaded (tools/bench/mcp_savings.py). So the chat
# loads only Boardwright's own server unless they are needed: in the schematic and layout stages, or when the
# user switches them on.
EDIT_STAGES = ("4", "5")
KICAD_TOOLS = {"auto": "Automatic (schematic and layout stages)", "on": "Always on", "off": "Off"}

LEAN_NOTE = (
    " The KiCad editing tools (kicad-live for the open board, kicad-schematic) are not loaded in this chat, to "
    "save tokens; Boardwright's own tools are. If you need to change the board while it is open in KiCad, or "
    "edit the schematic, do not work around it: tell the user to switch on \u22ef \u2192 KiCad editing tools \u2192 "
    "Always on (or to close the board so Boardwright's edit tool can change the file), then stop."
)


def current_stage(project: str) -> Optional[str]:
    """The number of the first stage without a report, or None when every report exists."""
    for num, _name, state, _note in stage_states(project):
        if state == "current":
            return num
    return None


def kicad_tools_wanted(project: str, setting: str) -> bool:
    if setting == "on":
        return True
    if setting == "off":
        return False
    return current_stage(project) in EDIT_STAGES


def lean_mcp_config(plugin_root: Optional[Path]) -> Optional[str]:
    """--mcp-config text with only Boardwright's own server, from the plugin's .mcp.json; None if not found."""
    if not plugin_root:
        return None
    try:
        servers = json.loads((Path(plugin_root) / ".mcp.json").read_text("utf-8"))["mcpServers"]
        own = json.loads(json.dumps(servers["boardwright"]).replace("${CLAUDE_PLUGIN_ROOT}",
                                                                     str(plugin_root).replace("\\", "/")))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # named as Claude Code names the plugin's own server, so the tools keep their usual names
    # (mcp__plugin_boardwright_boardwright__status ...), which the hooks and the skills' permissions use
    return json.dumps({"mcpServers": {"plugin_boardwright_boardwright": own}})


def console_python() -> str:
    """A python that shows a console (KiCad starts us with pythonw.exe, which has none)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


# Terminal emulators tried on Linux, in order, with the flag that runs a command.
LINUX_TERMINALS = (("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
                   ("xfce4-terminal", ["-x"]), ("kitty", []), ("alacritty", ["-e"]),
                   ("tilix", ["-e"]), ("mate-terminal", ["-x"]), ("lxterminal", ["-e"]), ("xterm", ["-e"]))


def open_in_terminal(argv: list) -> Optional[str]:
    """Run argv in a new, visible terminal window the user can type into.
    Windows: a new console. Linux: the first terminal emulator found.
    macOS: Terminal.app. -> error text (with the command to run by hand), or None."""
    shown = " ".join(f'"{a}"' if " " in a else a for a in argv)
    try:
        if os.name == "nt":
            subprocess.Popen(argv, creationflags=subprocess.CREATE_NEW_CONSOLE, close_fds=True)
            return None
        # keep the window open after the command ends, so its last lines can be read
        import shlex
        script = " ".join(shlex.quote(a) for a in argv) +             "; echo; read -r -p 'Press Enter to close this window. ' _"
        if sys.platform == "darwin":
            osa = 'tell application "Terminal" to do script ' + json.dumps(script)
            subprocess.Popen(["osascript", "-e", osa, "-e", 'tell application "Terminal" to activate'])
            return None
        for term, flag in LINUX_TERMINALS:
            exe = shutil.which(term)
            if exe:
                subprocess.Popen([exe] + flag + ["bash", "-c", script], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return None
        return "No terminal window could be opened. Open a terminal and run:  " + shown
    except OSError as exc:
        return f"could not open a terminal ({exc}). Run by hand:  {shown}"


def start_helper_setup() -> Optional[str]:
    """Run the plugin's setup.py (uv, kicad-buddy, mcp-server-kicad, KiCad API
    setting) in its own console window, where the user answers each y/N question.
    -> error text, or None."""
    if not bundle_available():
        return "this copy of the add-on has no bundled plugin; run the plugin's scripts/setup.py by hand"
    script = bundle_dir() / "plugin" / "scripts" / "setup.py"
    return open_in_terminal([console_python(), str(script)])


def start_login(claude: str) -> Optional[str]:
    """Start Claude Code's own sign-in (`claude auth login`) in its own console
    window. We do not touch its input or output. -> error text, or None."""
    return open_in_terminal([claude, "auth", "login"])


# --------------------------------------------------------------------------
# Talking to Claude Code
# --------------------------------------------------------------------------

# key -> (label, value for --permission-mode or None for Claude Code's default)
MODES = {
    "ask": ("Ask before edits", None),
    "edits": ("Auto-accept file edits", "acceptEdits"),
    "plan": ("Plan only (changes nothing)", "plan"),
}
DEFAULT_MODE = "ask"

# key -> (label, value for --model or None for the user's own Claude Code default).
# The aliases are the ones `claude --model` accepts; they follow the newest model of each line.
MODELS = {
    "default": ("Model: your default", None),
    "opus": ("Opus", "opus"),
    "sonnet": ("Sonnet", "sonnet"),
    "haiku": ("Haiku", "haiku"),
}
DEFAULT_MODEL = "default"


def looks_like_limit(text: str) -> bool:
    """Claude Code's 'You've reached your ... limit' reply: another model may still work."""
    t = (text or "").lower()
    return "limit" in t and ("reached" in t or "switch to another model" in t)


def build_argv(claude: str, mode: str = DEFAULT_MODE, resume: Optional[str] = None,
               plugin_dir: Optional[str] = None, model: str = DEFAULT_MODEL,
               lean_mcp: Optional[str] = None) -> list:
    """Command line of the chat process (flags checked against `claude --help` 2.1.289). lean_mcp: an
    --mcp-config text; when given, only those tool servers are loaded (see lean_mcp_config)."""
    argv = [claude, "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--permission-prompt-tool", "stdio",     # permission requests come to us
            "--append-system-prompt", SYSTEM_NOTE + (LEAN_NOTE if lean_mcp else "")]
    if lean_mcp:
        argv += ["--strict-mcp-config", "--mcp-config", lean_mcp]
    pm = MODES[mode][1]
    if pm:
        argv += ["--permission-mode", pm]
    mv = MODELS.get(model, MODELS[DEFAULT_MODEL])[1]
    if mv:
        argv += ["--model", mv]
    if resume:
        argv += ["--resume", resume]
    if plugin_dir:
        argv += ["--plugin-dir", plugin_dir]
    return argv


def tool_summary(name: str, inp) -> str:
    """One short line for a tool call, e.g. 'Bash: python scripts/status.py .'"""
    shown = name
    if name.startswith("mcp__"):
        parts = name.split("__")
        server = parts[1].replace("plugin_boardwright_", "") if len(parts) > 1 else ""
        shown = f"{server} · {parts[-1]}"
    detail = ""
    if isinstance(inp, dict):
        for key in ("command", "file_path", "path", "pattern", "query", "url",
                    "skill", "description", "prompt", "pcb_path", "schematic_path"):
            val = inp.get(key)
            if isinstance(val, str) and val.strip():
                detail = " ".join(val.split())
                break
        else:
            if inp and name.startswith("mcp__"):
                detail = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in list(inp.items())[:3])
    if len(detail) > 140:
        detail = detail[:137] + "..."
    return f"{shown}: {detail}" if detail else shown


AUTH_WORDS = ("not logged in", "please run /login", "invalid api key", "authentication_error",
              "oauth token has expired", "failed to authenticate", "login again")


def looks_like_auth_error(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in AUTH_WORDS)


class StreamParser:
    """Turns stream-json lines from Claude Code into (kind, payload) events.

      init        dict(session_id, model, mcp=[(name,status)], plugins=[names])
      text        str   assistant text, incremental
      status      str   short activity note ("thinking")
      tool        dict(id, name, summary, sub)      sub = inside a helper agent
      tool_error  str   first line of a failed tool result
      permission  dict(request_id, tool_name, input, summary, suggestions, title)
      permission_cancel  str request_id
      control_response   dict(request_id, ok, error)
      result      dict(is_error, text, cost, tokens_in, tokens_out, duration_ms, auth)
      raw         str   a line that is not JSON
    """

    def __init__(self) -> None:
        self.session_id: Optional[str] = None
        self._streamed = False
        self._seen_tools: set = set()

    def feed(self, line: str) -> list:
        line = line.strip()
        if not line:
            return []
        try:
            d = json.loads(line)
        except ValueError:
            return [("raw", line)]
        if not isinstance(d, dict):
            return [("raw", line)]
        out: list = []
        t = d.get("type")
        sid = d.get("session_id")
        if isinstance(sid, str) and sid and t in ("system", "result", "assistant"):
            self.session_id = sid
        sub = d.get("parent_tool_use_id") is not None

        if t == "system":
            if d.get("subtype") == "init":
                out.append(("init", {
                    "session_id": sid, "model": d.get("model"),
                    "mcp": [(s.get("name"), s.get("status")) for s in d.get("mcp_servers") or []
                            if isinstance(s, dict)],
                    "plugins": [p.get("name") for p in d.get("plugins") or [] if isinstance(p, dict)],
                }))
        elif t == "stream_event":
            if sub:
                return out
            ev = d.get("event") or {}
            et = ev.get("type")
            if et == "message_start":
                self._streamed = False
            elif et == "content_block_start":
                if (ev.get("content_block") or {}).get("type") == "thinking":
                    out.append(("status", "thinking"))
            elif et == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    self._streamed = True
                    out.append(("text", delta["text"]))
        elif t == "assistant":
            msg = d.get("message") or {}
            for block in msg.get("content") or []:
                if not isinstance(block, dict):
                    continue
                bt = block.get("type")
                if bt == "text" and not sub and not self._streamed and block.get("text"):
                    out.append(("text", block["text"]))
                elif bt == "tool_use":
                    tid = block.get("id") or id(block)
                    if tid not in self._seen_tools:
                        self._seen_tools.add(tid)
                        name = str(block.get("name", "?"))
                        out.append(("tool", {"id": tid, "name": name, "sub": sub,
                                             "summary": tool_summary(name, block.get("input"))}))
            if not sub:
                if self._streamed:
                    out.append(("text", "\n"))
                self._streamed = False
        elif t == "user":
            msg = d.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                        c = block.get("content")
                        if isinstance(c, list):
                            c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
                        first = str(c or "").strip().splitlines()[0:1]
                        out.append(("tool_error", (first[0] if first else "tool failed")[:200]))
        elif t == "control_request":
            req = d.get("request") or {}
            if req.get("subtype") == "can_use_tool":
                name = str(req.get("tool_name", "?"))
                out.append(("permission", {
                    "request_id": d.get("request_id"), "tool_name": name,
                    "input": req.get("input") if isinstance(req.get("input"), dict) else {},
                    "summary": tool_summary(name, req.get("input")),
                    "suggestions": req.get("permission_suggestions") or [],
                    "title": req.get("title") or req.get("description") or "",
                }))
            else:
                # hooks / in-process MCP: we registered none, so say so and move on
                out.append(("unsupported_request", {"request_id": d.get("request_id"),
                                                    "subtype": req.get("subtype")}))
        elif t == "control_cancel_request":
            out.append(("permission_cancel", d.get("request_id")))
        elif t == "control_response":
            r = d.get("response") or {}
            out.append(("control_response", {"request_id": r.get("request_id"),
                                             "ok": r.get("subtype") == "success",
                                             "error": r.get("error")}))
        elif t == "result":
            usage = d.get("usage") or {}
            text = d.get("result") if isinstance(d.get("result"), str) else ""
            is_err = bool(d.get("is_error"))
            out.append(("result", {
                "is_error": is_err, "text": text, "subtype": d.get("subtype"),
                "cost": d.get("total_cost_usd"),
                "tokens_in": (usage.get("input_tokens") or 0)
                             + (usage.get("cache_read_input_tokens") or 0)
                             + (usage.get("cache_creation_input_tokens") or 0),
                "tokens_out": usage.get("output_tokens") or 0,
                "duration_ms": d.get("duration_ms"),
                "auth": is_err and looks_like_auth_error(text),
            }))
        return out


class ClaudeSession:
    """One Claude Code process for one chat.

    `emit(kind, payload)` is called from a reader thread (the GUI wraps it in
    wx.CallAfter). Besides StreamParser's kinds it sends ("exit", code) once.
    """

    def __init__(self, argv: list, cwd: str, emit: Callable[[str, object], None]) -> None:
        self.argv, self.cwd, self.emit = argv, cwd, emit
        self.parser = StreamParser()
        self.proc: Optional[subprocess.Popen] = None
        self._wlock = threading.Lock()
        self._n = 0
        self.busy = False
        self.killed = False

    @property
    def session_id(self) -> Optional[str]:
        return self.parser.session_id

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.argv, cwd=self.cwd, env=child_env(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW, start_new_session=(os.name != "nt"))   # own group: Stop kills its tools too
        threading.Thread(target=self._read, name="claude-reader", daemon=True).start()
        self._control({"subtype": "initialize", "hooks": None})

    def _read(self) -> None:
        proc = self.proc
        try:
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace")
                for kind, payload in self.parser.feed(line):
                    if kind == "unsupported_request":
                        self._write({"type": "control_response", "response": {
                            "subtype": "error", "request_id": payload["request_id"],
                            "error": f"not supported by {APP_NAME}: {payload['subtype']}"}})
                        continue
                    if kind == "result":
                        self.busy = False
                    self.emit(kind, payload)
        except Exception as exc:                      # never die silently
            self.emit("raw", f"reader stopped: {type(exc).__name__}: {exc}")
        code = proc.wait()
        self.busy = False
        self.emit("exit", {"code": code, "killed": self.killed})

    def _write(self, obj: dict) -> bool:
        if not self.alive:
            return False
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._wlock:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            return True
        except OSError:
            return False

    def _control(self, request: dict) -> str:
        self._n += 1
        rid = f"req_{self._n}_{os.urandom(4).hex()}"
        self._write({"type": "control_request", "request_id": rid, "request": request})
        return rid

    def send(self, text: str) -> bool:
        self.busy = True
        ok = self._write({"type": "user", "message": {"role": "user", "content": text},
                          "parent_tool_use_id": None,
                          "session_id": self.session_id or "default"})
        if not ok:
            self.busy = False
        return ok

    def interrupt(self) -> None:
        """Ask Claude Code to stop the current turn (same as Esc in the terminal)."""
        self._control({"subtype": "interrupt"})

    def allow(self, request_id: str, tool_input: dict, remember: Optional[list] = None) -> None:
        resp = {"behavior": "allow", "updatedInput": tool_input}
        if remember:
            resp["updatedPermissions"] = remember
        self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": request_id, "response": resp}})

    def deny(self, request_id: str, message: str = "The user said no.") -> None:
        self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": request_id,
            "response": {"behavior": "deny", "message": message}}})

    def kill(self) -> None:
        """Stop the process and everything it started (MCP servers, shells)."""
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        self.killed = True
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10, creationflags=NO_WINDOW)
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def close(self) -> None:
        """End of chat: close stdin so Claude Code exits by itself, then make sure."""
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            with self._wlock:
                proc.stdin.close()
            proc.wait(timeout=3)
        except Exception:
            self.kill()


# --------------------------------------------------------------------------
# One window per project
# --------------------------------------------------------------------------

def window_title(project: str) -> str:
    return f"{APP_NAME} - {Path(project).name or project}"


def lock_path(project: str) -> Path:
    key = hashlib.sha1(os.path.normcase(os.path.abspath(project)).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"boardwright_chat_{key}.lock"


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def process_start_time(pid: int) -> Optional[float]:
    """Start time of a process in seconds since the epoch, or None when it cannot be read. Used so a lock
    left by a dead process is not mistaken for a live one that reuses the same PID."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            k32.OpenProcess.restype = wintypes.HANDLE
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                return None
            try:
                c, e, k, u = (wintypes.FILETIME() for _ in range(4))
                if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
                    return None
                return ((c.dwHighDateTime << 32) + c.dwLowDateTime) / 1e7 - 11644473600
            finally:
                k32.CloseHandle(h)
        if Path("/proc/self/stat").is_file():
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            ticks = int(fields[19])                      # field 22: start time in clock ticks since boot
            boot = float(next(l for l in Path("/proc/stat").read_text().splitlines() if l.startswith("btime")).split()[1])
            return boot + ticks / os.sysconf("SC_CLK_TCK")
        code, out, _err = run_quiet(["ps", "-o", "lstart=", "-p", str(pid)], timeout=5)
        if code == 0 and out.strip():
            import time as _t
            return _t.mktime(_t.strptime(out.strip(), "%a %b %d %H:%M:%S %Y"))
    except Exception:
        return None
    return None


def _read_lock(project: str) -> Optional[dict]:
    try:
        d = json.loads(lock_path(project).read_text("utf-8"))
        return d if isinstance(d, dict) and int(d["pid"]) > 0 else None
    except Exception:
        return None


def _lock_live(d: Optional[dict]) -> bool:
    """Does this lock record belong to a process that is still running (and is the same process)?"""
    if not d:
        return False
    pid = int(d["pid"])
    if not pid_alive(pid):
        return False
    started = d.get("started")
    now = process_start_time(pid)
    if isinstance(started, (int, float)) and now is not None and abs(now - started) > 2:
        return False                         # the PID now belongs to another process
    return True


def read_lock_pid(project: str) -> Optional[int]:
    d = _read_lock(project)
    return int(d["pid"]) if _lock_live(d) else None


def _lock_text() -> str:
    return json.dumps({"pid": os.getpid(), "started": process_start_time(os.getpid()), "token": _LOCK_TOKEN})


_LOCK_TOKEN = os.urandom(8).hex()


def acquire_lock(project: str) -> bool:
    """Take the one-window-per-project lock. The create is atomic (O_EXCL), so two quick clicks cannot
    both win. Calling it again from the owner refreshes the file."""
    path = lock_path(project)
    for _ in range(3):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            d = _read_lock(project)
            if d and int(d["pid"]) == os.getpid() and d.get("token") == _LOCK_TOKEN:
                return True                  # ours already (heartbeat)
            if _lock_live(d):
                return False
            if d is None:
                # unreadable: the other window may have created it a moment ago and not written it yet
                try:
                    if time.time() - path.stat().st_mtime < 5:
                        return False
                except OSError:
                    pass
            try:                             # stale or unreadable: remove it and try the atomic create again
                path.unlink()
            except OSError:
                pass
            continue
        except OSError:
            return True                      # cannot write the lock (read-only temp dir): do not block the user
        try:
            os.write(fd, _lock_text().encode("utf-8"))
        finally:
            os.close(fd)
        return True
    return False


def release_lock(project: str) -> None:
    try:
        p = lock_path(project)
        d = json.loads(p.read_text("utf-8"))
        if int(d.get("pid", -1)) == os.getpid() and d.get("token", _LOCK_TOKEN) == _LOCK_TOKEN:
            p.unlink()
    except Exception:
        pass


def raise_window(project: str) -> bool:
    """Bring the chat window that is already open for this project to the front."""
    if os.name != "nt":
        wm = shutil.which("wmctrl")             # X11 only; Wayland has no way for us to do this
        if not wm:
            return False
        try:
            return subprocess.run([wm, "-a", window_title(project)], timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    import ctypes
    u32 = ctypes.windll.user32
    hwnd = u32.FindWindowW(None, window_title(project))
    if not hwnd:
        return False
    u32.ShowWindow(hwnd, 9)          # SW_RESTORE
    u32.SetForegroundWindow(hwnd)
    return True
