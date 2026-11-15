#!/usr/bin/env python3
"""KiCad IPC-API action entrypoint for the Boardwright toolbar button.

KiCad runs this file in the plugin's own Python environment each time the
button is clicked.  It finds the folder of the open project, starts the chat
window as a separate process and returns at once, so nothing here can freeze
KiCad.  Standard library only; kicad-python (kipy) is used if it is there.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
LOG = Path(tempfile.gettempdir()) / "boardwright_launcher.log"


def log(msg: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def project_from_kicad() -> str | None:
    """Folder of the board that is open in the PCB Editor, or None.

    Uses kicad-python if someone installed it; otherwise reads the board name
    from the PCB Editor's window title and finds that board in KiCad's own
    recent-files list.  (requirements.txt lists no packages on purpose:
    KiCad 10.0.8's pip step hangs when the KiCad documents folder has a
    non-ASCII name, because pip floods an unread stderr pipe with encoding
    errors while downloading.)"""
    try:
        from kipy import KiCad
    except ImportError:
        return project_from_window_title()
    try:
        kicad = KiCad(timeout_ms=5000)     # reads KICAD_API_SOCKET / KICAD_API_TOKEN itself
        path = str(kicad.get_board().document.project.path or "")
        if path and Path(path).is_dir():
            return path
        log(f"board has no project folder yet (path={path!r})")
    except Exception as exc:
        log(f"asking KiCad for the project failed: {exc}")
    return project_from_window_title()


def pcb_editor_titles() -> list:
    """Titles of visible PCB Editor windows. Windows: the window list.
    Linux on X11: wmctrl or xdotool if installed. Otherwise none (Wayland
    does not let other programs read window titles)."""
    if os.name != "nt":
        for cmd in (["wmctrl", "-l"], ["xdotool", "search", "--name", "PCB Editor", "getwindowname", "%@"]):
            if shutil.which(cmd[0]):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
                except (OSError, subprocess.TimeoutExpired):
                    continue
                # wmctrl lines: "<id> <desktop> <host> <title>"
                lines = [l.split(None, 3)[-1] if cmd[0] == "wmctrl" else l for l in out.splitlines()]
                return [l for l in lines if l.rstrip().endswith("PCB Editor")]
        return []
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    titles = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.rstrip().endswith("PCB Editor"):
                    titles.append(buf.value)
        return True
    u32.EnumWindows(cb, 0)
    return titles


def kicad_config_dirs() -> list:
    env = os.environ.get("KICAD_CONFIG_HOME")
    if env:
        return [Path(env)]
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "kicad"
    return sorted((d for d in base.glob("*.*") if d.is_dir()), reverse=True)


def recent_boards() -> list:
    import json
    out = []
    for d in kicad_config_dirs():
        for name, ext in (("pcbnew.json", ".kicad_pcb"), ("kicad.json", ".kicad_pro")):
            try:
                hist = json.loads((d / name).read_text("utf-8")).get("system", {}).get("file_history", [])
            except Exception:
                continue
            out += [Path(h) for h in hist if isinstance(h, str) and h.endswith(ext)]
    return out


def project_from_window_title() -> str | None:
    # title looks like "usb-sensor-test — PCB Editor" (a leading '*' means unsaved)
    names = set()
    for t in pcb_editor_titles():
        stem = re.split(r"\s+[—–-]\s+PCB Editor\s*$", t)[0].lstrip("*").strip()
        if stem and stem != t:
            names.add(stem)
    dirs = {}
    for b in recent_boards():
        if b.stem in names and b.parent.is_dir():
            dirs.setdefault(os.path.normcase(str(b.parent)), str(b.parent))
    if len(dirs) == 1:
        path = next(iter(dirs.values()))
        log(f"project from window title {sorted(names)} and KiCad's recent files: {path}")
        return path
    if not names and os.name != "nt":
        # No window titles to go by (Linux on Wayland, or no wmctrl): KiCad puts the
        # board it opened last at the top of its recent-files list.
        newest = next((b for b in recent_boards() if b.suffix == ".kicad_pcb" and b.parent.is_dir()), None)
        if newest:
            log(f"no window titles readable; using the most recently opened board: {newest}")
            return str(newest.parent)
    log(f"could not tell the project folder (PCB Editor titles {sorted(names)}, matches {sorted(dirs.values())}); "
        "will ask for it")
    return None


def imports_wx(py: str) -> bool:
    try:
        return subprocess.run([py, "-c", "import wx"], capture_output=True, timeout=30,
                              stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def gui_python() -> str | None:
    """A Python that has wxPython.  Windows/macOS: KiCad's bundled Python.
    Linux: the system python3, where KiCad's packages install python3-wxgtk."""
    env = os.environ.get("BOARDWRIGHT_PYTHON")
    if env and Path(env).is_file():
        return env
    if os.name != "nt" and sys.platform != "darwin":
        cands = [sys.executable, getattr(sys, "_base_executable", ""), "/usr/bin/python3", shutil.which("python3")]
        for c in dict.fromkeys(c for c in cands if c):
            if Path(c).is_file() and imports_wx(c):
                return c
        return None
    base = Path(getattr(sys, "base_executable", "") or sys.executable).parent
    for d in (base, Path(sys.base_prefix), Path(sys.base_prefix) / "bin"):
        has_wx = any((d / lib / "site-packages" / "wx").is_dir() for lib in ("Lib", "lib")) or \
                 any(d.parent.glob("lib/python3*/site-packages/wx"))
        if has_wx:
            for n in ("pythonw.exe", "python.exe", "python3", "python"):
                if (d / n).is_file():
                    return str(d / n)
    return None


def main() -> int:
    from bw_core import raise_window, read_lock_pid
    project = project_from_kicad()
    if project and read_lock_pid(project):
        raise_window(project)
        log(f"already open for {project}")
        return 0
    py = gui_python()
    if not py:
        msg = ("Boardwright: no Python with wxPython found. " +
               ("Install wxPython for the system Python (Debian/Ubuntu: sudo apt install python3-wxgtk4.0) "
                "or set BOARDWRIGHT_PYTHON." if sys.platform.startswith("linux")
                else "Set BOARDWRIGHT_PYTHON to KiCad's python."))
        log(msg)
        print(msg)                 # KiCad 10.0.1+ shows plugin output in its messages
        return 1
    cmd = [py, str(HERE / "bw_chat.py")]
    cmd += ["--project", project] if project else ["--ask-project"]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED | NEW_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    with open(LOG, "a", encoding="utf-8") as err:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=err, stderr=err,
                         close_fds=True, cwd=str(HERE), **kw)
    log(f"started {cmd}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log("unhandled:\n" + traceback.format_exc())
        print("Boardwright could not start; see " + str(LOG))
        sys.exit(1)
