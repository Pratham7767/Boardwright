"""Look of the Boardwright chat window: colours (day and night), fonts, soft shadows, rounded buttons,
the ring on the home screen, the rounded message box and the stage chips.

wxPython only (KiCad's own Python). The colours live in one dict, T, that every control reads when it
paints, so switching day/night is: set_theme(...), then repaint.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path
from typing import Callable, Optional

import wx

DAY = {
    "bg": "#F3F3F1", "surface": "#FFFFFF", "surface2": "#E9E9E6", "border": "#E2E2DE",
    "text": "#141414", "dim": "#8A8A86", "faint": "#B9B9B4",
    "primary": "#141414", "primary_hover": "#333333", "on_primary": "#FFFFFF",
    "accent": "#5B4BDB", "accent_soft": "#ECEAFB",
    "you": "#5B4BDB", "you_bg": "#ECEAFB", "claude": "#141414",
    "ok": "#1E8A4C", "ok_soft": "#E2F3E8", "bad": "#C8372D", "bad_soft": "#FBE6E3",
    "warn": "#A85A00", "warn_soft": "#FFF4E2", "tool": "#9A9A95",
    "shadow": "#000000", "ring_a": "#C9C3FF", "ring_b": "#8FE3D3", "ring_c": "#FFFFFF",
}
NIGHT = {
    "bg": "#0F0F11", "surface": "#1B1B1F", "surface2": "#26262B", "border": "#2E2E34",
    "text": "#EEEEEC", "dim": "#8E8E93", "faint": "#55555B",
    "primary": "#F2F2F0", "primary_hover": "#FFFFFF", "on_primary": "#111111",
    "accent": "#9C8FFF", "accent_soft": "#25223F",
    "you": "#B3A9FF", "you_bg": "#221F3B", "claude": "#EEEEEC",
    "ok": "#4FD088", "ok_soft": "#16301F", "bad": "#FF8177", "bad_soft": "#3A1D1B",
    "warn": "#FFC45C", "warn_soft": "#352A12", "tool": "#6E6E74",
    "shadow": "#000000", "ring_a": "#FF7A1A", "ring_b": "#FFB15C", "ring_c": "#FFE0BF",
}

T: dict = {}                 # the current colours as wx.Colour
CURRENT = {"name": "day"}    # "day" or "night"
HERE = Path(__file__).resolve().parent


def system_is_dark() -> bool:
    try:
        if hasattr(wx.SystemSettings, "GetAppearance"):
            return bool(wx.SystemSettings.GetAppearance().IsDark())
    except Exception:
        pass
    return wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW).GetLuminance() < 0.5


def resolve(choice: str) -> str:
    """'auto' follows the computer's setting."""
    if choice in ("day", "night"):
        return choice
    return "night" if system_is_dark() else "day"


def set_theme(name: str) -> None:
    CURRENT["name"] = name
    src = NIGHT if name == "night" else DAY
    T.clear()
    T.update({k: wx.Colour(v) for k, v in src.items()})


def alpha(c: wx.Colour, a: int) -> wx.Colour:
    return wx.Colour(c.Red(), c.Green(), c.Blue(), max(0, min(255, int(a))))


def font(size_delta: int = 0, weight=wx.FONTWEIGHT_NORMAL, display: bool = False) -> wx.Font:
    """Segoe UI Variable on Windows 11, else the system font."""
    base = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    face = "Segoe UI Variable Display" if display else "Segoe UI Variable Text"
    f = wx.Font(base)
    if wx.FontEnumerator.IsValidFacename(face):
        f.SetFaceName(face)
    f.SetPointSize(max(7, base.GetPointSize() + 1 + size_delta))
    f.SetWeight(weight)
    return f


# ---------------------------------------------------------------- the user's setting (theme only)
def _settings_file() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "Boardwright" / "chat-settings.json"


def load_choice() -> str:
    try:
        v = json.loads(_settings_file().read_text("utf-8")).get("theme")
        return v if v in ("auto", "day", "night") else "auto"
    except (OSError, ValueError, AttributeError):
        return "auto"


def save_choice(choice: str) -> None:
    f = _settings_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if f.exists():
            try:
                data = json.loads(f.read_text("utf-8"))
            except ValueError:
                data = {}
        data["theme"] = choice
        f.write_text(json.dumps(data, indent=2), "utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- drawing helpers
def soft_shadow(gc, x, y, w, h, r, spread: int = 6, strength: int = 26) -> None:
    """A soft drop shadow under a rounded shape: a few faint rounded rects, larger and fainter."""
    gc.SetPen(wx.TRANSPARENT_PEN)
    night = CURRENT["name"] == "night"
    base = strength * (2.2 if night else 1.0)
    for i in range(spread, 0, -1):
        a = base * (1 - i / (spread + 1)) / spread * 2
        gc.SetBrush(wx.Brush(alpha(T["shadow"], a)))
        gc.DrawRoundedRectangle(x - i, y - i + 3, w + 2 * i, h + 2 * i, r + i)


def parent_bg(win: wx.Window) -> wx.Colour:
    return win.GetParent().GetBackgroundColour()


class _Painted(wx.Control):
    """Base for the self-drawn controls: no flicker, hand cursor, hover and press tracking."""

    def __init__(self, parent, tip: str = ""):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.hover = False
        self.down = False
        if tip:
            self.SetToolTip(tip)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))

    def clickable(self) -> None:
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._hover(True))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._hover(False))
        self.Bind(wx.EVT_LEFT_DOWN, self._down)
        self.Bind(wx.EVT_LEFT_DCLICK, self._down)
        self.Bind(wx.EVT_LEFT_UP, self._up)

    def _hover(self, on: bool) -> None:
        self.hover = on
        if not on:
            self.down = False
        self.Refresh()

    def _down(self, e) -> None:
        if self.IsEnabled():
            self.down = True
            self.Refresh()

    def _up(self, e) -> None:
        if not (self.down and self.IsEnabled()):
            return
        self.down = False
        self.Refresh()
        self.clicked()

    def clicked(self) -> None:
        ev = wx.CommandEvent(wx.wxEVT_BUTTON, self.GetId())
        ev.SetEventObject(self)
        wx.PostEvent(self.GetEventHandler(), ev)

    def Enable(self, enable=True):
        r = super().Enable(enable)
        self.Refresh()
        return r

    def _gc(self):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(parent_bg(self)))
        dc.Clear()
        return dc, wx.GraphicsContext.Create(dc)

    def _paint(self, e) -> None:
        dc, gc = self._gc()
        if gc is not None:
            self.draw(gc, *self.GetClientSize())

    def draw(self, gc, w, h) -> None:
        pass


class Pill(_Painted):
    """A rounded button. kind:
      primary  - filled (black in day, white at night)
      ghost    - quiet, filled with the second surface colour
      danger   - soft red
      suggest  - white pill with a soft shadow and a round "+" at the end (the starting suggestions)
      chip     - small stage chip; colour from status (done, failed, current, pending)
      circle   - round icon button (send, stop, theme, menu); filled=True for the send button
    Sends EVT_BUTTON when clicked."""

    SHADOW = 5

    def __init__(self, parent, label: str = "", kind: str = "ghost", tip: str = "", status: str = "",
                 filled: bool = False, size: int = 34):
        super().__init__(parent, tip)
        self.kind = kind
        self.status = status
        self.filled = filled
        self.side = size
        super().SetLabel(label)
        self.SetFont(font(-2 if kind == "chip" else 0,
                          wx.FONTWEIGHT_SEMIBOLD if kind == "primary" else wx.FONTWEIGHT_NORMAL))
        self.clickable()
        self.SetMinSize(self.DoGetBestSize())

    def SetLabel(self, label):
        if label == self.GetLabel():
            return
        super().SetLabel(label)
        self.InvalidateBestSize()
        self.SetMinSize(self.DoGetBestSize())
        self.Refresh()

    def set_status(self, status: str, tip: str = "") -> None:
        self.status = status
        if tip:
            self.SetToolTip(tip)
        self.Refresh()

    def DoGetBestSize(self):
        if self.kind == "circle":
            return wx.Size(self.side, self.side)
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        w, h = dc.GetTextExtent(self.GetLabel() or "Ag")
        if self.kind == "chip":
            return wx.Size(w + 20, h + 10)
        if self.kind == "suggest":
            s = self.SHADOW
            return wx.Size(w + 20 + 20 + 10 + 2 * s, h + 18 + 2 * s)
        return wx.Size(w + 30, h + 16)

    def draw(self, gc, w, h) -> None:
        on = self.IsEnabled()
        k = self.kind
        if k == "suggest":
            s = self.SHADOW
            x, y, ww, hh = s, s - 1, w - 2 * s, h - 2 * s
            soft_shadow(gc, x, y, ww, hh, hh / 2, spread=4, strength=16 if not self.hover else 28)
            gc.SetBrush(wx.Brush(T["surface"]))
            gc.SetPen(wx.Pen(T["border"], 1))
            gc.DrawRoundedRectangle(x, y, ww, hh, hh / 2)
            gc.SetFont(self.GetFont(), T["text"] if on else T["dim"])
            tw, th = gc.GetTextExtent(self.GetLabel())[:2]
            gc.DrawText(self.GetLabel(), x + 14, y + (hh - th) / 2)
            d = 18
            cx, cy = x + ww - 10 - d, y + (hh - d) / 2
            gc.SetBrush(wx.Brush(T["primary"] if self.hover and on else T["faint"]))
            gc.SetPen(wx.TRANSPARENT_PEN)
            gc.DrawEllipse(cx, cy, d, d)
            gc.SetPen(wx.Pen(T["on_primary"] if self.hover and on else T["surface"], 2))
            gc.StrokeLine(cx + 5, cy + d / 2, cx + d - 5, cy + d / 2)
            gc.StrokeLine(cx + d / 2, cy + 5, cx + d / 2, cy + d - 5)
            return
        if k == "circle":
            d = min(w, h) - 1
            if self.filled:
                if on:
                    soft_shadow(gc, 1, 1, d - 2, d - 2, (d - 2) / 2, spread=3, strength=20)
                bg = (T["primary_hover"] if self.hover else T["primary"]) if on else T["surface2"]
                fg = T["on_primary"] if on else T["dim"]
                gc.SetBrush(wx.Brush(bg))
                gc.SetPen(wx.TRANSPARENT_PEN)
            else:
                bg = T["surface2"] if self.hover else T["surface"]
                fg = T["text"] if on else T["dim"]
                gc.SetBrush(wx.Brush(bg))
                gc.SetPen(wx.Pen(T["border"], 1))
            gc.DrawEllipse(0.5, 0.5, d, d)
            f = font(1 if self.filled else 0)
            gc.SetFont(f, fg)
            tw, th = gc.GetTextExtent(self.GetLabel())[:2]
            gc.DrawText(self.GetLabel(), (d - tw) / 2 + 0.5, (d - th) / 2)
            return
        if k == "chip":
            st = self.status
            bg, fg = {"done": (T["ok_soft"], T["ok"]), "failed": (T["bad_soft"], T["bad"]),
                      "current": (T["primary"], T["on_primary"])}.get(st, (T["surface2"], T["dim"]))
            border = T["text"] if self.hover else None
        elif k == "primary":
            bg = (T["primary_hover"] if self.hover else T["primary"]) if on else T["surface2"]
            fg, border = (T["on_primary"] if on else T["dim"]), None
        elif k == "danger":
            bg, fg, border = T["bad_soft"], T["bad"], (T["bad"] if self.hover and on else None)
        else:  # ghost
            bg = T["surface"] if (self.hover and on) else T["surface2"]
            fg, border = (T["text"] if on else T["dim"]), (T["border"] if self.hover else None)
        r = (h - 1) / 2
        gc.SetBrush(wx.Brush(bg))
        gc.SetPen(wx.Pen(border, 1) if border else wx.TRANSPARENT_PEN)
        gc.DrawRoundedRectangle(0.5, 0.5, w - 1, h - 1, r)
        gc.SetFont(self.GetFont(), fg)
        tw, th = gc.GetTextExtent(self.GetLabel())[:2]
        gc.DrawText(self.GetLabel(), (w - tw) / 2, (h - th) / 2)


class Logo(_Painted):
    """The add-on's speech-bubble icon on a rounded tile."""

    def __init__(self, parent, size: int = 34):
        super().__init__(parent)
        self.side = size
        self.SetMinSize(wx.Size(size, size))
        self.bmp = None
        try:
            img = wx.Image(str(HERE / "icons" / "chat-48.png"))
            if img.IsOk():
                self.bmp = wx.Bitmap(img.Scale(int(size * 0.62), int(size * 0.62), wx.IMAGE_QUALITY_HIGH))
        except Exception:
            self.bmp = None

    def draw(self, gc, w, h) -> None:
        d = self.side - 1
        gc.SetBrush(wx.Brush(T["primary"]))
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.DrawRoundedRectangle(0.5, 0.5, d, d, 9)
        if self.bmp:
            bw = self.bmp.GetWidth()
            gc.DrawBitmap(self.bmp, (d - bw) / 2 + 0.5, (d - bw) / 2 + 1, bw, bw)


class Ring(_Painted):
    """The ring on the welcome screen. It is alive:
    - it breathes and turns slowly by itself, and faster while Claude works;
    - it leans towards the mouse and shivers when you move across it;
    - drag it to spin it (it keeps turning, then slows down);
    - click it: a ripple and a burst of tiny traces with vias, like a board being routed;
    - double-click: eight long traces route out from it at 45 degrees.
    Animates only while it is on screen."""

    BASE, BUSY = 0.010, 0.07          # turning speed, radians per frame

    def __init__(self, parent, size: int = 240):
        super().__init__(parent, "Drag to spin it. Click it. Double-click it.")
        self.SetMinSize(wx.Size(size, size))
        self.phase = 0.0
        self.speed = self.BASE
        self.busy = False
        self.t0 = time.monotonic()
        self.mouse = None             # (x, y) while over the ring
        self.hover = 0.0              # eases 0..1
        self.energy = 0.0             # from mouse movement; makes it shiver
        self.drag = None              # last angle while dragging
        self.moved = False
        self.ripples: list = []       # [start time]
        self.bits: list = []          # flying traces: dicts x, y, vx, vy, life, kind, col
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._tick, self.timer)
        self.Bind(wx.EVT_MOTION, self._move)
        self.Bind(wx.EVT_ENTER_WINDOW, lambda e: self._set_mouse(e.GetPosition()))
        self.Bind(wx.EVT_LEAVE_WINDOW, lambda e: self._set_mouse(None))
        self.Bind(wx.EVT_LEFT_DOWN, self._press)
        self.Bind(wx.EVT_LEFT_UP, self._release)
        self.Bind(wx.EVT_LEFT_DCLICK, self._double)
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))

    # ------------------------------------------------------------ control from the window
    def spin(self, on: bool) -> None:
        """Claude is working (faster turn)."""
        self.busy = on

    def active(self, on: bool) -> None:
        """Animate only while shown."""
        if on and not self.timer.IsRunning():
            self.timer.Start(30)
        elif not on and self.timer.IsRunning():
            self.timer.Stop()

    # ------------------------------------------------------------ geometry
    def _centre(self):
        w, h = self.GetClientSize()
        return w / 2, h / 2, min(min(w, h) * 0.30, 78)

    def _angle(self, p) -> float:
        cx, cy, _ = self._centre()
        return math.atan2(p[1] - cy, p[0] - cx)

    # ------------------------------------------------------------ mouse
    def _set_mouse(self, p) -> None:
        self.mouse = (p.x, p.y) if p is not None else None
        if p is None:
            self.drag = None

    def _move(self, e) -> None:
        p = e.GetPosition()
        if self.mouse:
            d = math.hypot(p.x - self.mouse[0], p.y - self.mouse[1])
            self.energy = min(1.0, self.energy + d * 0.004)
        self.mouse = (p.x, p.y)
        if self.drag is not None and e.LeftIsDown():
            a = self._angle(self.mouse)
            d = (a - self.drag + math.pi) % (2 * math.pi) - math.pi
            self.phase += d
            self.speed = max(-0.35, min(0.35, d))
            self.drag = a
            if abs(d) > 0.02:
                self.moved = True

    def _press(self, e) -> None:
        p = e.GetPosition()
        self.drag = self._angle((p.x, p.y))
        self.moved = False
        if not self.HasCapture():
            self.CaptureMouse()

    def _release(self, e) -> None:
        if self.HasCapture():
            self.ReleaseMouse()
        if self.drag is not None and not self.moved:
            p = e.GetPosition()
            self._burst(p.x, p.y)
        self.drag = None

    def _double(self, e) -> None:
        cx, cy, R = self._centre()
        cols = self._cols()
        for k in range(8):
            a = k * math.pi / 4 + self.phase
            self.bits.append({"x": cx + R * 1.05 * math.cos(a), "y": cy + R * 1.05 * math.sin(a),
                              "x0": cx + R * 1.05 * math.cos(a), "y0": cy + R * 1.05 * math.sin(a),
                              "vx": 3.2 * math.cos(a), "vy": 3.2 * math.sin(a), "life": 1.0, "kind": "route",
                              "col": cols[k % 3], "turn": k % 2})
        self.ripples.append(time.monotonic())
        self.speed += 0.15

    @staticmethod
    def _cols():
        """Colours for the flying traces; the pale one would vanish on the light day background."""
        return (T["ring_a"], T["ring_b"], T["ring_c"] if CURRENT["name"] == "night" else T["accent"])

    def _burst(self, x, y) -> None:
        self.ripples.append(time.monotonic())
        self.energy = 1.0
        cols = self._cols()
        for k in range(22):
            a = k / 22 * 2 * math.pi + (k % 3) * 0.2
            v = 2.0 + (k * 37 % 11) / 4
            self.bits.append({"x": x, "y": y, "vx": v * math.cos(a), "vy": v * math.sin(a),
                              "life": 1.0, "kind": "spark", "col": cols[k % 3]})

    # ------------------------------------------------------------ animation
    def _tick(self, e) -> None:
        if not self.IsShownOnScreen():
            return
        target = self.BUSY if self.busy else self.BASE
        if self.drag is None:
            self.speed += (target - self.speed) * 0.03
            self.phase = (self.phase + self.speed) % (2 * math.pi)
        self.hover += ((1.0 if self.mouse else 0.0) - self.hover) * 0.08
        self.energy *= 0.95
        now = time.monotonic()
        self.ripples = [r for r in self.ripples if now - r < 1.2]
        alive = []
        for b in self.bits:
            if b["kind"] == "route":
                b["x"] += b["vx"]
                b["y"] += b["vy"]
                b["life"] -= 0.014
            else:
                b["x"] += b["vx"]
                b["y"] += b["vy"]
                b["vx"] *= 0.94
                b["vy"] *= 0.94
                b["life"] -= 0.022
            if b["life"] > 0:
                alive.append(b)
        self.bits = alive
        self.Refresh(False)

    def draw(self, gc, w, h) -> None:
        t = time.monotonic() - self.t0
        cx, cy, R = self._centre()
        # lean a little towards the mouse
        ux = uy = 0.0
        if self.mouse:
            dx, dy = self.mouse[0] - cx, self.mouse[1] - cy
            dist = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / dist, dy / dist
            cx += dx * 0.05 * self.hover
            cy += dy * 0.05 * self.hover
        R *= 1 + 0.025 * math.sin(t * 1.3) + 0.04 * self.hover
        a, b, c = T["ring_a"], T["ring_b"], T["ring_c"]
        wob = 0.07 + 0.10 * self.energy
        n = 42
        gc.SetBrush(wx.TRANSPARENT_BRUSH)
        for i in range(n):
            ang = self.phase + i / n * 2 * math.pi
            rx = R * (1 + wob * math.sin(ang * 2 + 0.6 + t * 0.7))
            ry = R * (1 + wob * math.cos(ang * 3 + 0.2 - t * 0.5))
            ox = 6 * math.cos(ang) + ux * 9 * self.hover * (0.5 + 0.5 * math.sin(ang * 2 + t))
            oy = 6 * math.sin(ang * 1.3) + uy * 9 * self.hover * (0.5 + 0.5 * math.sin(ang * 2 + t))
            mix = (math.sin(ang + t * 0.4) + 1) / 2
            col = wx.Colour(int(a.Red() * mix + b.Red() * (1 - mix)), int(a.Green() * mix + b.Green() * (1 - mix)),
                            int(a.Blue() * mix + b.Blue() * (1 - mix)), int(72 + 70 * self.energy))
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(col).Width(2.2)))
            gc.DrawEllipse(cx - rx + ox, cy - ry + oy, 2 * rx, 2 * ry)
        # light on glass, turning with the ring
        path = gc.CreatePath()
        start = math.radians(200) + self.phase * 0.6
        path.AddArc(cx, cy, R * 1.02, start, start + math.radians(50), True)
        gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(alpha(c, 170)).Width(3)))
        gc.StrokePath(path)
        # ripples
        now = time.monotonic()
        for r0 in self.ripples:
            k = (now - r0) / 1.2
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(alpha(a, 150 * (1 - k))).Width(2)))
            rr = R * (1 + 0.9 * k)
            gc.DrawEllipse(cx - rr, cy - rr, 2 * rr, 2 * rr)
        # flying traces: a short L-shaped track with a via at its head, like a tiny piece of routing
        for bt in self.bits:
            col = alpha(bt["col"], 230 * bt["life"])
            gc.SetPen(gc.CreatePen(wx.GraphicsPenInfo(col).Width(1.8)))
            x, y = bt["x"], bt["y"]
            if bt["kind"] == "route":
                x0, y0 = bt["x0"], bt["y0"]
                mid = (x, y0) if bt["turn"] else (x0, y)          # one 90-degree bend, as routers do
                gc.StrokeLines([(x0, y0), mid, (x, y)])
                vr = 4.0
            else:
                tx, ty = x - bt["vx"] * 4, y - bt["vy"] * 4
                gc.StrokeLines([(tx, ty), (x, ty), (x, y)])
                vr = 2.6
            gc.SetBrush(wx.Brush(T["bg"]))
            gc.DrawEllipse(x - vr, y - vr, 2 * vr, 2 * vr)
        gc.SetBrush(wx.TRANSPARENT_BRUSH)


class RoundInput(wx.Panel):
    """The message box: a big rounded field with a soft shadow, a borderless text box inside and a round
    send button at the right end (it turns into a stop button while Claude works)."""

    S = 8   # shadow margin

    def __init__(self, parent, on_key: Callable, on_send: Callable, on_stop: Callable):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.text = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_WORDWRAP | wx.TE_RICH2 | wx.BORDER_NONE
                                | wx.TE_NO_VSCROLL, size=(-1, 44))
        self.text.SetFont(font(1))
        self.text.Bind(wx.EVT_KEY_DOWN, on_key)
        self.hint = wx.StaticText(self, label="Ask anything about this board...")
        self.hint.SetFont(font(1))
        self.hint.Bind(wx.EVT_LEFT_DOWN, lambda e: self.text.SetFocus())
        self.text.Bind(wx.EVT_TEXT, lambda e: (self._hint(), e.Skip()))
        self.send_btn = Pill(self, "→", "circle", tip="Send (Enter)", filled=True, size=40)
        self.send_btn.Bind(wx.EVT_BUTTON, lambda e: on_send())
        self.stop_btn = Pill(self, "■", "circle", tip="Stop (Esc). Your next message continues the chat.",
                             filled=True, size=40)
        self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: on_stop())
        self.stop_btn.Hide()
        s = wx.BoxSizer(wx.HORIZONTAL)
        s.AddSpacer(self.S + 20)
        stack = wx.BoxSizer(wx.VERTICAL)
        stack.Add(self.hint, 0, wx.TOP, 2)
        stack.Add(self.text, 1, wx.EXPAND)
        self._stack = stack
        s.Add(stack, 1, wx.ALIGN_CENTER_VERTICAL | wx.TOP | wx.BOTTOM, self.S + 8)
        s.Add(self.send_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        s.Add(self.stop_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        s.AddSpacer(self.S + 10)
        self.SetSizer(s)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))
        self._hint()

    def _hint(self) -> None:
        empty = not self.text.GetValue()
        if self.hint.IsShown() != empty:
            self.hint.Show(empty)
            self.Layout()

    def busy(self, on: bool) -> None:
        self.send_btn.Show(not on)
        self.stop_btn.Show(on)
        self.Layout()

    def apply(self) -> None:
        self.SetBackgroundColour(T["surface"])     # what the round buttons inside sit on
        for c in (self.text, self.hint):
            c.SetBackgroundColour(T["surface"])
        self.text.SetForegroundColour(T["text"])
        self.text.SetDefaultStyle(wx.TextAttr(T["text"], T["surface"]))
        self.hint.SetForegroundColour(T["dim"])
        self.Refresh()

    def _paint(self, e) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(parent_bg(self)))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return
        w, h = self.GetClientSize()
        s = self.S
        r = min(30, (h - 2 * s) / 2)
        soft_shadow(gc, s, s - 2, w - 2 * s, h - 2 * s, r, spread=7, strength=22)
        gc.SetBrush(wx.Brush(T["surface"]))
        gc.SetPen(wx.Pen(T["border"], 1))
        gc.DrawRoundedRectangle(s, s - 2, w - 2 * s, h - 2 * s, r)


class Card(wx.Panel):
    """A rounded panel with a soft shadow (setup checks, permission requests). Put children in .body."""

    S = 6

    def __init__(self, parent, tone: str = "surface"):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.tone = tone
        self.body = wx.Panel(self)
        self.body.bw_bg = tone
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(self.body, 1, wx.EXPAND | wx.ALL, self.S + 8)
        self.SetSizer(s)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, lambda e: (self.Refresh(), e.Skip()))

    def _paint(self, e) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(parent_bg(self)))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return
        w, h = self.GetClientSize()
        s = self.S
        soft_shadow(gc, s, s - 2, w - 2 * s, h - 2 * s, 16, spread=5, strength=18)
        gc.SetBrush(wx.Brush(T[self.tone]))
        gc.SetPen(wx.Pen(T["border"], 1))
        gc.DrawRoundedRectangle(s, s - 2, w - 2 * s, h - 2 * s, 16)


# ---------------------------------------------------------------- stages (read from reports/)
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


def apply_colours(win: wx.Window, bg_key: str = "bg") -> None:
    """Background and text colours for plain panels and labels under win (painted controls draw themselves)."""
    win.SetBackgroundColour(T[bg_key])
    for c in win.GetChildren():
        tag = getattr(c, "bw_bg", None)
        if isinstance(c, RoundInput):
            c.apply()
        elif isinstance(c, Card):
            c.SetBackgroundColour(T[bg_key])
            apply_colours(c.body, c.tone)
        elif isinstance(c, _Painted):
            pass
        elif isinstance(c, wx.CheckBox):
            c.SetForegroundColour(T["text"])
            c.SetBackgroundColour(T[tag or bg_key])
        elif isinstance(c, wx.StaticText):
            c.SetForegroundColour(T[getattr(c, "bw_fg", "text")])
            c.SetBackgroundColour(T[tag or bg_key])
        elif isinstance(c, wx.TextCtrl):
            c.SetBackgroundColour(T[tag or bg_key])
            c.SetForegroundColour(T["text"])
        elif isinstance(c, wx.Panel):
            apply_colours(c, tag or bg_key)
        c.Refresh()


def label(parent, text: str, fg: str = "text", weight=wx.FONTWEIGHT_NORMAL, size_delta: int = 0,
          bg: Optional[str] = None, display: bool = False, centre: bool = False,
          wrap: bool = False) -> wx.StaticText:
    style = wx.ALIGN_CENTRE_HORIZONTAL if centre else 0
    if not wrap:
        style |= wx.ST_ELLIPSIZE_END
    s = wx.StaticText(parent, label=text, style=style)
    s.bw_fg = fg
    if bg:
        s.bw_bg = bg
    s.SetFont(font(size_delta, weight, display))
    return s
