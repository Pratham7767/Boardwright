"""Save a picture of one window (by a piece of its title) to a PNG, even when other windows cover it.
Windows only; run with a Python that has wxPython (KiCad's):

    <kicad python> tools/guide/capture_window.py "PCB Editor" out.png [x0 y0 x1 y1]

The optional box crops the picture (window pixels). Used to make the user guide's screenshots.
"""
import ctypes
import sys
from ctypes import wintypes

import wx

u32 = ctypes.windll.user32


def find(part: str):
    hits = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u32.IsWindowVisible(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, b, n + 1)
                if part.lower() in b.value.lower():
                    hits.append(h)
        return True
    u32.EnumWindows(cb, 0)
    return hits[0] if hits else None


def main() -> int:
    main.app = wx.App(False)               # keep wx alive while drawing
    h = find(sys.argv[1])
    if not h:
        print("window not found: " + sys.argv[1])
        return 1
    r = wintypes.RECT()
    u32.GetWindowRect(h, ctypes.byref(r))
    w, ht = r.right - r.left, r.bottom - r.top
    bmp = wx.Bitmap(w, ht)
    mdc = wx.MemoryDC(bmp)
    pw = u32.PrintWindow
    pw.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    pw(h, mdc.GetHandle(), 2)
    mdc.SelectObject(wx.NullBitmap)
    if len(sys.argv) >= 7:
        x0, y0, x1, y1 = (int(v) for v in sys.argv[3:7])
        bmp = bmp.GetSubBitmap(wx.Rect(x0, y0, x1 - x0, y1 - y0))
    bmp.SaveFile(sys.argv[2], wx.BITMAP_TYPE_PNG)
    print(f"saved {sys.argv[2]} ({bmp.GetWidth()}x{bmp.GetHeight()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
