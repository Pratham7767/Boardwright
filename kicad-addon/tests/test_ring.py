"""The living ring on the chat's welcome screen (needs a Python with wxPython, e.g. KiCad's).

    <kicad python> kicad-addon/tests/test_ring.py [picture.png]

Opens a small window with the ring, moves a fake mouse over it, clicks and double-clicks, and checks that
it animates, reacts, cleans up its flying traces and draws a frame quickly enough. Saves a picture
mid-animation when a path is given. Exit 0 when all pass.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))
import os  # noqa: E402

if os.name != "nt" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    print("skip: no display to open a window on (a headless Linux runner)")
    sys.exit(0)
try:
    import wx
except ImportError:
    print("skip: wxPython is not available in this Python (run it with KiCad's Python)")
    sys.exit(0)
import bw_theme as theme  # noqa: E402

RESULTS = []


def check(name, ok, extra=""):
    RESULTS.append(ok)
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  -> {extra}"))


app = wx.App(False)
theme.set_theme(sys.argv[2] if len(sys.argv) > 2 else "night")
frame = wx.Frame(None, title="ring test", size=(320, 320))
frame.SetBackgroundColour(theme.T["bg"])
ring = theme.Ring(frame, 260)
s = wx.BoxSizer(wx.VERTICAL)
s.Add(ring, 1, wx.EXPAND)
frame.SetSizer(s)
frame.Show()


def run():
    ring.active(True)
    p0 = ring.phase
    for _ in range(10):
        ring._tick(None)
    check("turns by itself", ring.phase != p0)
    ring.mouse = (40, 40)
    ring._move(type("E", (), {"GetPosition": lambda self: wx.Point(200, 150), "LeftIsDown": lambda self: False})())
    for _ in range(20):
        ring._tick(None)
    check("notices the mouse (leans and shivers)", ring.hover > 0.5 and ring.energy > 0.05, (ring.hover, ring.energy))
    ring._burst(200, 120)
    check("a click makes a ripple and a burst of traces", len(ring.ripples) == 1 and len(ring.bits) == 22)
    ring._double(None)
    check("a double-click routes eight traces out", sum(b["kind"] == "route" for b in ring.bits) == 8)
    for _ in range(12):
        ring._tick(None)
    ring.Update()
    wx.Yield()
    if len(sys.argv) > 1 and os.name == "nt":       # the picture uses a Windows call
        w, h = frame.GetSize()
        bmp = wx.Bitmap(w, h)
        mdc = wx.MemoryDC(bmp)
        import ctypes
        pw = ctypes.windll.user32.PrintWindow
        pw.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        pw(frame.GetHandle(), mdc.GetHandle(), 2)
        mdc.SelectObject(wx.NullBitmap)
        bmp.SaveFile(sys.argv[1], wx.BITMAP_TYPE_PNG)
    t = time.perf_counter()
    for _ in range(20):
        ring.Refresh(False)
        ring.Update()
    ms = (time.perf_counter() - t) / 20 * 1000
    check(f"draws a frame in {ms:.1f} ms (needs under 25 ms for smooth motion)", ms < 25, ms)
    time.sleep(1.3)                 # ripples fade by time
    for _ in range(120):
        ring._tick(None)
    check("the flying traces and ripples clear away", not ring.bits and not ring.ripples, len(ring.bits))
    ring.active(False)
    check("stops animating when hidden", not ring.timer.IsRunning())
    frame.Destroy()
    app.ExitMainLoop()


wx.CallLater(300, run)
app.MainLoop()
bad = RESULTS.count(False)
print("all passed" if not bad and RESULTS else f"{bad} failed")
sys.exit(1 if bad or not RESULTS else 0)
