"""Dock the chat window to the side of KiCad's PCB Editor, so it looks and behaves like a side panel.

KiCad does not let add-ons put a panel inside its own window (add-ons are separate programs), so the chat
window attaches itself to the PCB Editor instead:
- it sits against the PCB Editor's right edge, at the same height, and follows it when it moves or resizes;
- if the PCB Editor fills the screen, the PCB Editor is made narrower so the chat does not cover the board
  (its own size comes back on undock or close);
- on Windows the chat is "owned" by the PCB Editor: it stays on top of KiCad only, hides when KiCad is
  minimised, and has no taskbar button of its own;
- when the PCB Editor closes, the chat becomes a normal window again.

Windows: Win32 through ctypes. Linux on X11: follows the PCB Editor with xdotool when it is installed (no
ownership). Elsewhere (Wayland, macOS): docking is not available and the chat stays a normal window.
Standard library only.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Optional

IS_WIN = os.name == "nt"
GWLP_HWNDPARENT = -8
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_RESTORE = 9
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
MONITOR_DEFAULTTONEAREST = 2

if IS_WIN:
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _title_matches(title: str, project_name: str) -> bool:
    """KiCad 10's PCB Editor title is "<board> — PCB Editor" (a leading '*' when unsaved)."""
    t = title.strip().lstrip("*").strip()
    if not t.endswith("PCB Editor"):
        return False
    if not project_name:
        return True
    # the whole board name must match: project "usb" must not dock to "usb-sensor-test — PCB Editor"
    board = t[: -len("PCB Editor")].rstrip(" —-").strip()
    return board.lower() == project_name.lower()


def find_pcb_editor(project_name: str) -> Optional[int]:
    """The PCB Editor window for this project: a Win32 HWND, an X11 window id, or None."""
    if IS_WIN:
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if u32.IsWindowVisible(hwnd):
                n = u32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    u32.GetWindowTextW(hwnd, buf, n + 1)
                    if _title_matches(buf.value, project_name):
                        found.append(hwnd)
            return True
        u32.EnumWindows(cb, 0)
        return found[0] if found else None
    if shutil.which("xdotool") and os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        try:
            out = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "PCB Editor"],
                                 capture_output=True, text=True, timeout=3).stdout.split()
            for wid in out:
                name = subprocess.run(["xdotool", "getwindowname", wid], capture_output=True, text=True,
                                      timeout=3).stdout
                if _title_matches(name, project_name):
                    return int(wid)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None
    return None


class Dock:
    """Keeps a wx.Frame docked to the PCB Editor. Call attach(), then poll() on a timer (the chat does)."""

    def __init__(self, frame, project_name: str, width: int = 420,
                 on_change: Optional[Callable[[bool], None]] = None):
        self.frame = frame
        self.name = project_name
        self.width = width
        self.on_change = on_change
        self.target: Optional[int] = None
        self.saved_target_rect = None          # the PCB Editor's rect before we made room
        self.saved_maximized = False
        self.last_rect = None
        self.docked = False

    @staticmethod
    def available() -> bool:
        return IS_WIN or (bool(shutil.which("xdotool")) and bool(os.environ.get("DISPLAY"))
                          and not os.environ.get("WAYLAND_DISPLAY"))

    # ------------------------------------------------------------------ geometry helpers
    def _rect(self, hwnd):
        if IS_WIN:
            r = wintypes.RECT()
            if not u32.GetWindowRect(hwnd, ctypes.byref(r)):
                return None
            return (r.left, r.top, r.right, r.bottom)
        try:
            out = subprocess.run(["xdotool", "getwindowgeometry", "--shell", str(hwnd)], capture_output=True,
                                 text=True, timeout=3).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        v = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        try:
            x, y, w, h = int(v["X"]), int(v["Y"]), int(v["WIDTH"]), int(v["HEIGHT"])
        except (KeyError, ValueError):
            return None
        return (x, y, x + w, y + h)

    def _work_area(self, hwnd):
        if IS_WIN:
            mon = u32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if u32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                w = mi.rcWork
                return (w.left, w.top, w.right, w.bottom)
            return None
        import wx
        a = wx.Display(max(0, wx.Display.GetFromWindow(self.frame))).GetClientArea()
        return (a.x, a.y, a.x + a.width, a.y + a.height)

    def _alive(self, hwnd) -> bool:
        if IS_WIN:
            return bool(u32.IsWindow(hwnd))
        return self._rect(hwnd) is not None

    def _move(self, hwnd, x, y, w, h) -> None:
        if IS_WIN:
            u32.SetWindowPos(hwnd, 0, int(x), int(y), int(w), int(h), SWP_NOZORDER | SWP_NOACTIVATE)
        else:
            subprocess.run(["xdotool", "windowsize", str(hwnd), str(w), str(h), "windowmove", str(hwnd),
                            str(x), str(y)], capture_output=True, timeout=3)

    def _own(self, on: bool) -> None:
        """Windows: make the PCB Editor the chat's owner (on top of KiCad only, minimised with it, no taskbar
        button), or give the chat back its own taskbar button."""
        if not IS_WIN:
            return
        me = self.frame.GetHandle()
        ex = u32.GetWindowLongPtrW(me, GWL_EXSTYLE)
        if on:
            u32.SetWindowLongPtrW(me, GWLP_HWNDPARENT, self.target or 0)
            u32.SetWindowLongPtrW(me, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        else:
            u32.SetWindowLongPtrW(me, GWLP_HWNDPARENT, 0)
            u32.SetWindowLongPtrW(me, GWL_EXSTYLE, (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)

    # ------------------------------------------------------------------ docking
    def attach(self) -> bool:
        """Dock to the PCB Editor. False (and nothing changed) when it cannot be found."""
        if not self.available():
            return False
        hwnd = find_pcb_editor(self.name)
        if not hwnd:
            return False
        self.target = hwnd
        rect = self._rect(hwnd)
        work = self._work_area(hwnd)
        if not rect or not work:
            return False
        self.saved_target_rect = rect
        self.saved_maximized = bool(IS_WIN and u32.IsZoomed(hwnd))
        # make room when the PCB Editor reaches the screen's right edge
        if rect[2] + self.width > work[2]:
            if self.saved_maximized:
                u32.ShowWindow(hwnd, SW_RESTORE)
            left = max(work[0], min(rect[0], work[2] - self.width - 400))
            top = work[1] if self.saved_maximized else rect[1]
            bottom = work[3] if self.saved_maximized else rect[3]
            self._move(hwnd, left, top, work[2] - self.width - left, bottom - top)
        self._own(True)
        self.docked = True
        self.last_rect = None
        self.poll()
        if self.on_change:
            self.on_change(True)
        return True

    def detach(self, restore: bool = True) -> None:
        """Back to a normal window; the PCB Editor gets its own size back."""
        if not self.docked:
            return
        self.docked = False
        try:
            self._own(False)
            if restore and self.target and self._alive(self.target) and self.saved_target_rect:
                l, t, r, b = self.saved_target_rect
                self._move(self.target, l, t, r - l, b - t)
                if self.saved_maximized and IS_WIN:
                    u32.ShowWindow(self.target, 3)            # SW_MAXIMIZE
        finally:
            self.target = None
            if self.on_change:
                self.on_change(False)

    def poll(self) -> None:
        """Follow the PCB Editor. Called on a short timer while docked."""
        if not self.docked or not self.target:
            return
        if not self._alive(self.target):
            self.detach(restore=False)          # KiCad closed: stay open as a normal window
            return
        if IS_WIN and u32.IsIconic(self.target):
            return                              # minimised: the owner takes the chat with it
        rect = self._rect(self.target)
        if not rect or rect == self.last_rect:
            return
        self.last_rect = rect
        work = self._work_area(self.target) or rect
        x = min(rect[2], work[2] - self.width)
        if IS_WIN:
            self._move(self.frame.GetHandle(), x, rect[1], self.width, rect[3] - rect[1])
        else:
            self.frame.SetSize(x, rect[1], self.width, rect[3] - rect[1])
