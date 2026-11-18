"""Docking test with a stand-in PCB Editor window (Windows; needs a Python with wxPython, e.g. KiCad's).

    <kicad python> kicad-addon/tests/test_dock.py

Opens two small windows for a few seconds: a fake "dock-test — PCB Editor" and a chat stand-in, then checks
that the chat attaches to the editor's right edge, follows a move, makes room when the editor is maximised,
and gives the editor its size back when undocked. Exit 0 when all pass (or skipped off Windows).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))
if os.name != "nt":
    print("skip: docking is tested on Windows")
    sys.exit(0)
try:
    import wx
except ImportError:
    print("skip: wxPython is not available in this Python (run it with KiCad's Python)")
    sys.exit(0)
import bw_dock  # noqa: E402

RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append(ok)
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  -> {extra}"))


app = wx.App(False)
editor = wx.Frame(None, title="dock-test — PCB Editor", pos=(100, 100), size=(700, 500))
chat = wx.Frame(None, title="chat", pos=(900, 100), size=(300, 300))
editor.Show()
chat.Show()
steps = []


def rect_of(hwnd):
    r = bw_dock.wintypes.RECT()
    bw_dock.u32.GetWindowRect(hwnd, bw_dock.ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def run():
    d = bw_dock.Dock(chat, "dock-test", width=360)
    eh, ch = editor.GetHandle(), chat.GetHandle()
    before = rect_of(eh)
    check("finds the PCB Editor window by its title", bw_dock.find_pcb_editor("dock-test") == eh)
    check("does not match another project's editor", bw_dock.find_pcb_editor("other-board") is None)
    check("attaches", d.attach())
    e, c = rect_of(eh), rect_of(ch)
    check("chat sits against the editor's right edge, same top and height",
          abs(c[0] - e[2]) <= 2 and abs(c[1] - e[1]) <= 2 and abs((c[3] - c[1]) - (e[3] - e[1])) <= 2, f"{e} {c}")
    check("chat is owned by the editor (on top of KiCad only, minimised with it)",
          bw_dock.u32.GetWindowLongPtrW(ch, bw_dock.GWLP_HWNDPARENT) == eh)
    editor.SetPosition((150, 140))
    d.poll()
    e, c = rect_of(eh), rect_of(ch)
    check("follows when the editor moves", abs(c[0] - e[2]) <= 2 and abs(c[1] - e[1]) <= 2, f"{e} {c}")
    d.detach()
    check("detach gives the editor its size back", rect_of(eh) == before or abs(rect_of(eh)[2] - before[2]) <= 2,
          f"{before} {rect_of(eh)}")
    check("detach releases ownership", bw_dock.u32.GetWindowLongPtrW(ch, bw_dock.GWLP_HWNDPARENT) == 0)
    # an editor (not maximised) that reaches the screen's right edge is made narrower, then gets its size back
    work0 = d._work_area(eh)
    editor.SetPosition((work0[2] - 750, 120))
    wx.Yield()
    near_edge = rect_of(eh)
    check("attaches to an editor at the screen edge", d.attach())
    e, c = rect_of(eh), rect_of(ch)
    check("makes room: the editor is narrower and the chat fits on screen",
          e[2] < near_edge[2] and c[2] <= work0[2] + 2, f"before {near_edge} editor {e} chat {c}")
    d.detach()
    check("detach gives a narrowed editor its size back", rect_of(eh) == near_edge, f"{near_edge} {rect_of(eh)}")
    editor.Maximize(True)
    wx.Yield()
    work = d._work_area(eh)
    check("attaches to a maximised editor", d.attach())
    e, c = rect_of(eh), rect_of(ch)
    check("makes room: the editor ends where the chat begins, the chat ends at the screen edge",
          abs(e[2] - c[0]) <= 2 and abs(c[2] - work[2]) <= 2, f"editor {e} chat {c} work {work}")
    d.detach()
    check("the editor is maximised again after undock", bool(bw_dock.u32.IsZoomed(eh)))
    editor.Destroy()
    wx.Yield()
    d2 = bw_dock.Dock(chat, "dock-test", width=360)
    check("nothing to dock to once the editor is closed", not d2.attach())
    chat.Destroy()
    app.ExitMainLoop()


wx.CallLater(500, run)
app.MainLoop()
bad = RESULTS.count(False)
print("all passed" if not bad and RESULTS else f"{bad} failed")
sys.exit(1 if bad or not RESULTS else 0)
