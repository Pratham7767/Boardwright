"""Loaded automatically by every Python the Boardwright engine starts (it is on PYTHONPATH for them).

Inside KiCad's Python, KiCad shows some messages (for example "Font 'Lato' not found") in a message box
and waits for a click, which would freeze an unattended run. This sends them to stderr instead.
Anywhere else (no wx, no display) it does nothing. It never raises.
"""
try:
    import os
    import sys
    if sys.platform in ("win32", "darwin") or os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        import wx
        if not wx.GetApp():
            _avail = getattr(wx.App, "IsDisplayAvailable", None)
            if _avail is None or _avail():
                wx.App(False)
        wx.Log.SetActiveTarget(wx.LogStderr())
except KeyboardInterrupt:
    raise
except BaseException:        # wx raises SystemExit when there is no display
    pass
