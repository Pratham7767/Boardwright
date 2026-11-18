#!/usr/bin/env python3
"""Boardwright chat window (wxPython, run with KiCad's own Python).

    python bw_chat.py --project <folder of the KiCad project>
    python bw_chat.py --project <dir> --selftest      open, wait 2 s, exit 0

A separate top-level window at the right screen edge (KiCad has no API for a
docked third-party panel).  All Claude Code logic is in bw_core.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bw_core as core                                              # noqa: E402
import bw_dock                                                      # noqa: E402

DEFAULT_WIDTH = 480
# Suggestions under the message box: (label, tooltip, "send" or "fill", text).
# "fill" puts a sentence starter in the box for the user to finish.
QUICK = (("Next step", "Carry on with the next stage. Claude stops when it needs you.",
          "send", "/boardwright:pcb-run"),
         ("Run checks", "Run every check (ERC, DRC, the stage gates) and say in plain words what fails.",
          "send", "/boardwright:pcb-gates"),
         ("Review", "Have the strongest model check the work so far against the evidence.",
          "send", "/boardwright:pcb-review"),
         ("Doctor", "Check that Claude Code, the plugin, KiCad and the routing engine work.",
          "send", "/boardwright:pcb-doctor"))
WELCOME_NEW = (
    ("Start a new board", "Describe it in your own words; Claude asks the rest",
     "fill", "I want to design a board that "),
    ("Use my schematic", "Claude checks the schematic you have and takes it through the remaining stages",
     "send", "This project already has a schematic. Check it, tell me what you find, and take it through "
             "the remaining stages. Ask before changing anything."),
    ("Check my setup", "Claude Code, the plugin, KiCad, the routing engine",
     "send", "/boardwright:pcb-doctor"),
)
WELCOME_STARTED = (
    ("Where am I?", "One plain line per stage, then the next step",
     "send", "Where does this board stand? One plain line per stage, then tell me the single next step."),
    ("Next step", "Claude works on and stops when it needs you", "send", "/boardwright:pcb-run"),
    ("Fix what's failing", "Each problem with a proposed fix; asks before changing anything",
     "send", "Show me what is failing on this board, in plain words, with a proposed fix for each. "
             "Ask before changing anything."),
    ("Run checks", "Every check, in plain words", "send", "/boardwright:pcb-gates"),
)


class _Flag:
    """The dock on/off state (shown as a check mark in the menu)."""

    def __init__(self) -> None:
        self.v = False

    def GetValue(self) -> bool:
        return self.v

    def SetValue(self, v: bool) -> None:
        self.v = bool(v)


def out(msg: str) -> None:
    if sys.stdout is not None:
        try:
            print(msg, flush=True)
        except Exception:
            pass


def run_gui(project: str, claude_override: Optional[str], selftest: bool, mode: str,
            width: int, side: str, theme_arg: Optional[str] = None, snapshot: Optional[str] = None) -> int:
    import wx
    import bw_theme as theme

    class Frame(wx.Frame):
        def __init__(self) -> None:
            super().__init__(None, title=core.window_title(project))
            self.project = project
            self.mode = mode
            saved_mode = core.settings_get("mode")
            if saved_mode in core.MODES and mode == core.DEFAULT_MODE:
                self.mode = saved_mode
            saved_model = core.settings_get("model")
            self.model_key = saved_model if saved_model in core.MODELS else core.DEFAULT_MODEL
            self.cost_seen = 0.0                       # Claude Code reports a running total per process
            saved_tools = core.settings_get("kicad_tools")
            self.kicad_tools = saved_tools if saved_tools in core.KICAD_TOOLS else "auto"
            self.session_kicad = None                  # whether the running session has the KiCad tools
            self.checks: Optional[dict] = None
            self.session: Optional[core.ClaudeSession] = None
            self.resume_id: Optional[str] = None       # session to pick up after a restart
            self.pending: list = []                    # permission requests waiting for the user
            self.waiting_login = False
            self.at_line_start = True
            self.need_header = False
            self.turn_text = ""
            self.last_turn = ""
            self.model = ""
            self.theme_choice = theme_choice
            self.col = theme.T                         # transcript colours follow the theme
            self.segs: list = []                       # transcript as (text, role, bold), for repainting
            self.talked = False                        # the welcome panel shows until the first message
            self._build()
            self._place(width, side)
            self.Bind(wx.EVT_CLOSE, self.on_close)
            self.beat = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda e: core.acquire_lock(self.project), self.beat)
            self.beat.Start(15000)
            self.stop_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_stop_timeout, self.stop_timer)
            # docked to the PCB Editor's side by default (the user's choice); the Dock button turns it off
            self.dock = bw_dock.Dock(self, Path(self.project).name, width=max(380, min(width, 520)),
                                     on_change=lambda on: self.dock_btn.SetValue(on))
            self.dock_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda e: self.dock.poll(), self.dock_timer)
            self.dock_tries = 0
            wx.CallLater(300, self.try_dock)
            self.add("Runs your own Claude Code in this folder. Each message uses your Claude plan.\n\n", "dim")
            self.apply_theme()
            self.refresh_stages()
            self.stage_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda e: self.refresh_stages(), self.stage_timer)
            self.stage_timer.Start(20000)
            self.update_controls()
            self.recheck()

        # ---------------- layout ----------------
        def _build(self) -> None:
            P = theme.Pill
            p = self.panel = wx.Panel(self)
            p.SetFont(theme.font())
            root = wx.BoxSizer(wx.VERTICAL)

            # --- top bar: logo, board name, day/night, menu ---
            head = wx.BoxSizer(wx.HORIZONTAL)
            head.Add(theme.Logo(p, 34), 0, wx.ALIGN_CENTER_VERTICAL)
            names = wx.BoxSizer(wx.VERTICAL)
            title = theme.label(p, Path(self.project).name or self.project, "text", wx.FONTWEIGHT_SEMIBOLD)
            title.SetToolTip(self.project)
            names.Add(title, 0, wx.EXPAND)
            names.Add(theme.label(p, "Boardwright", "dim", size_delta=-2), 0, wx.EXPAND)
            head.Add(names, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
            self.theme_btn = P(p, "", "circle", tip="Day or night colours")
            self.theme_btn.Bind(wx.EVT_BUTTON, lambda e: self.toggle_theme())
            self.menu_btn = P(p, "⋯", "circle", tip="Mode, model, dock, new chat, setup")
            self.menu_btn.Bind(wx.EVT_BUTTON, lambda e: self.show_menu())
            head.Add(self.theme_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
            head.Add(self.menu_btn, 0, wx.ALIGN_CENTER_VERTICAL)
            root.Add(head, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 16)

            # --- the eight stages; click one to ask about it ---
            strip = wx.WrapSizer(wx.HORIZONTAL, 0)
            self.stage_btns = []
            for num, name, _f in core.STAGES:
                b = P(p, f"{num} {name}", "chip", tip=name)
                b.Bind(wx.EVT_BUTTON, lambda e, n=num, nm=name: self.ask_stage(n, nm))
                strip.Add(b, 0, wx.RIGHT | wx.BOTTOM, 4)
                self.stage_btns.append(b)
            root.Add(strip, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.LEFT | wx.RIGHT | wx.TOP, 14)

            # --- home: the ring and a short welcome (until the first message) ---
            self.home = wx.Panel(p)
            hs = wx.BoxSizer(wx.VERTICAL)
            self.ring = theme.Ring(self.home, 120)
            hs.Add(self.ring, 1, wx.EXPAND)                # grows into the free space, shrinks when cards show
            self.home_title = theme.label(self.home, "", "text", wx.FONTWEIGHT_NORMAL, size_delta=7,
                                          display=True, centre=True)
            hs.Add(self.home_title, 0, wx.EXPAND | wx.TOP, 18)
            self.home_sub = theme.label(self.home, "", "dim", centre=True, wrap=True)
            hs.Add(self.home_sub, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP | wx.BOTTOM, 8)
            self.home.SetSizer(hs)
            root.Add(self.home, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 20)

            # --- transcript (the chat view) ---
            self.log = wx.TextCtrl(p, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_WORDWRAP
                                   | wx.BORDER_NONE)
            self.log.SetMargins(6, 6)
            self.log.SetFont(theme.font(1))
            self.log.bw_bg = "bg"
            root.Add(self.log, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 14)

            # --- setup checks (first run), as a card ---
            self.setup = theme.Card(p, "surface")
            sb = self.setup.body
            box = wx.BoxSizer(wx.VERTICAL)
            box.Add(theme.label(sb, "Setup", "text", wx.FONTWEIGHT_SEMIBOLD, bg="surface"), 0, wx.BOTTOM, 6)
            self.rows = {}
            grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
            grid.AddGrowableCol(0, 1)
            for key in ("claude", "auth", "plugin", "helpers", "engine"):
                lab = theme.label(sb, "checking...", "dim", bg="surface")
                btn = P(sb, "", "primary")
                btn.Hide()
                grid.Add(lab, 1, wx.ALIGN_CENTER_VERTICAL | wx.EXPAND)
                grid.Add(btn, 0, wx.ALIGN_CENTER_VERTICAL)
                self.rows[key] = (lab, btn)
            self.rows["claude"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_install_claude())
            self.rows["auth"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_sign_in())
            self.rows["plugin"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_install_plugin())
            self.rows["helpers"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_install_helpers())
            self.rows["engine"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_install_engine())
            box.Add(grid, 0, wx.EXPAND | wx.RIGHT, 4)
            self.setup_note = wx.TextCtrl(sb, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE,
                                          size=(-1, 54))
            self.setup_note.bw_bg = "surface"
            box.Add(self.setup_note, 0, wx.EXPAND | wx.TOP, 6)
            self.recheck_btn = P(sb, "↻  Check again", "ghost")
            self.recheck_btn.Bind(wx.EVT_BUTTON, lambda e: self.recheck())
            box.Add(self.recheck_btn, 0, wx.TOP, 4)
            sb.SetSizer(box)
            root.Add(self.setup, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

            # --- one question after sign-in: keep a usage log? ---
            self.feedback_card = theme.Card(p, "surface")
            fb = self.feedback_card.body
            fs = wx.BoxSizer(wx.VERTICAL)
            fs.Add(theme.label(fb, "Help make Boardwright better?", "text", wx.FONTWEIGHT_SEMIBOLD, bg="surface"))
            msg = theme.label(fb, "If you agree, a private usage log stays on this computer for the boards you open "
                                  "here: which steps ran, "
                                  "errors, token counts and cost. Nothing is sent by itself. When you choose "
                                  "Send feedback, you read the report and post it yourself on GitHub.",
                              "dim", size_delta=-1, bg="surface", wrap=True)
            msg.Wrap(370)
            fs.Add(msg, 0, wx.EXPAND | wx.TOP, 4)
            self.fb_prompts = wx.CheckBox(fb, label="Also keep my messages (passwords, keys and paths are removed)")
            self.fb_prompts.bw_bg = "surface"
            fs.Add(self.fb_prompts, 0, wx.TOP, 6)
            fr = wx.BoxSizer(wx.HORIZONTAL)
            yes = P(fb, "Yes, keep a usage log", "primary")
            no = P(fb, "No thanks", "ghost")
            yes.Bind(wx.EVT_BUTTON, lambda e: self.answer_usage_log(True))
            no.Bind(wx.EVT_BUTTON, lambda e: self.answer_usage_log(False))
            fr.Add(yes, 0, wx.RIGHT, 6)
            fr.Add(no, 0)
            fs.Add(fr, 0, wx.TOP, 8)
            later = theme.label(fb, "You can change it any time in the \u22ef menu.", "dim", size_delta=-2,
                                bg="surface", wrap=True)
            later.Wrap(330)
            fs.Add(later, 0, wx.TOP, 6)
            fb.SetSizer(fs)
            self.feedback_card.Hide()
            root.Add(self.feedback_card, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

            # --- permission request, as a card ---
            self.perm = theme.Card(p, "warn_soft")
            pb = self.perm.body
            ps = wx.BoxSizer(wx.VERTICAL)
            self.perm_label = theme.label(pb, "", "warn", wx.FONTWEIGHT_SEMIBOLD, bg="warn_soft")
            self.perm_help = theme.label(pb, "Read what it wants to do, then choose. Deny is always safe.",
                                         "dim", size_delta=-1, bg="warn_soft")
            self.perm_detail = wx.TextCtrl(pb, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE,
                                           size=(-1, 64))
            self.perm_detail.bw_bg = "surface"
            pr = wx.BoxSizer(wx.HORIZONTAL)
            self.allow_btn = P(pb, "Allow", "primary", tip="Let Claude do this once")
            self.always_btn = P(pb, "Always allow", "ghost", tip="Allow this kind of action from now on")
            self.deny_btn = P(pb, "Deny", "danger", tip="Refuse; Claude is told and carries on")
            self.allow_btn.Bind(wx.EVT_BUTTON, lambda e: self.answer(True))
            self.always_btn.Bind(wx.EVT_BUTTON, lambda e: self.answer(True, remember=True))
            self.deny_btn.Bind(wx.EVT_BUTTON, lambda e: self.answer(False))
            for b in (self.allow_btn, self.always_btn, self.deny_btn):
                pr.Add(b, 0, wx.RIGHT, 6)
            ps.Add(self.perm_label, 0, wx.EXPAND)
            ps.Add(self.perm_help, 0, wx.EXPAND | wx.TOP, 2)
            ps.Add(self.perm_detail, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 8)
            ps.Add(pr, 0)
            pb.SetSizer(ps)
            self.perm.Hide()
            root.Add(self.perm, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

            # --- suggestions (home) or one-click requests (chat), then the message box ---
            self.suggest_sizer = wx.WrapSizer(wx.HORIZONTAL, 0)
            self.quick_btns = []
            root.Add(self.suggest_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
            self.box = theme.RoundInput(p, self.on_key, self.send_input, self.stop)
            self.inp = self.box.text
            self.send_btn, self.stop_btn = self.box.send_btn, self.box.stop_btn
            root.Add(self.box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
            self.status = theme.label(p, "", "dim", size_delta=-2, centre=True)
            self.status.SetStatusText = self.status.SetLabel       # same call the old status bar took
            root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
            p.SetSizer(root)
            self.dock_btn = _Flag()
            self.spinner = None
            self.SetMinSize(wx.Size(360, 600))
            self.build_welcome()

        # ---------------- home, suggestions, stages, theme, menu ----------------
        def build_welcome(self) -> None:
            """Home view until the first message: the ring, a welcome line, suggestions under it."""
            started = core.has_started(self.project)
            name = Path(self.project).name
            self.home_title.SetLabel("Welcome back" if started else "What are we building?")
            self.home_sub.SetLabel(
                f"Your own Claude Code, working on {name}. Pick a suggestion or ask anything; "
                "it asks before it changes your board." if started else
                "Describe a board in your own words. Claude plans it with you, stage by stage, "
                "and asks before it changes anything.")
            self.home_sub.Wrap(max(240, self.GetClientSize().width - 80))
            items = list(WELCOME_STARTED if started else WELCOME_NEW)
            last = (core.settings_get("last_chats", {}) or {}).get(self.project)
            if last:
                items.insert(0, ("Continue last chat", "Pick up the conversation you had about this board",
                                 "resume", last))
            self.fill_suggestions(items)
            self.show_view()

        def fill_suggestions(self, items) -> None:
            s = self.suggest_sizer
            s.Clear(delete_windows=True)
            self.quick_btns = []
            for title, tip, action, text in items:
                b = theme.Pill(self.panel, title, "suggest", tip=tip)
                b.Bind(wx.EVT_BUTTON, lambda e, a=action, t=text: self.on_card(a, t))
                s.Add(b, 0, wx.RIGHT, 2)
                self.quick_btns.append(b)

        def show_view(self) -> None:
            home = not self.talked
            self.home.Show(home)
            self.ring.active(home)
            self.log.Show(not home)
            if not home and not getattr(self, "_chat_suggestions", False):
                self._chat_suggestions = True
                self.fill_suggestions(QUICK)
            elif home:
                self._chat_suggestions = False
            self.panel.Layout()

        def check_tool_set(self) -> None:
            """In Automatic, a new stage may need the KiCad editing tools (or no longer need them): the next
            message then restarts Claude Code with the right set, in the same chat."""
            if self.session is None or self.session_kicad is None or self.busy:
                return
            want = core.kicad_tools_wanted(self.project, self.kicad_tools)
            if want != self.session_kicad and core.bundle_dir() is not None:
                self.drop_session(keep_chat=True)
                self.line("KiCad editing tools " + ("loaded for the schematic and layout stages."
                          if want else "unloaded to save tokens; Boardwright's own tools stay.") , "dim")
                self.update_controls()

        def pick_kicad_tools(self, i: int) -> None:
            self.kicad_tools = list(core.KICAD_TOOLS)[i]
            core.settings_set("kicad_tools", self.kicad_tools)
            self.drop_session(keep_chat=True)       # applies from the next message, same chat
            self.line("KiCad editing tools: " + core.KICAD_TOOLS[self.kicad_tools], "dim")
            self.update_controls()

        def remember_chat(self) -> None:
            sid = (self.session.session_id if self.session else None) or self.resume_id
            if sid:
                chats = core.settings_get("last_chats", {}) or {}
                chats[self.project] = sid
                core.settings_set("last_chats", chats)

        def on_card(self, action: str, text: str) -> None:
            if action == "resume":
                self.resume_id = text
                self.talked = True
                self.show_view()
                self.line("Continuing your last chat about this board. Type your next message.", "dim")
                self.inp.SetFocus()
                return
            if action == "feedback":
                self.send_feedback()
                return
            if action == "fill":                 # put a sentence starter in the box for the user to finish
                self.inp.SetValue(text)
                self.inp.SetFocus()
                self.inp.SetInsertionPointEnd()
            else:
                self.send(text)

        def ask_stage(self, num: str, name: str) -> None:
            self.send(f"Tell me where stage {num} ({name}) stands, in plain words: what was done, what is "
                      f"open, and what I should do next. Don't change anything.")

        def refresh_stages(self) -> None:
            labels = {"done": "done", "failed": "needs attention", "current": "next", "pending": "not started"}
            for b, (num, name, state, note) in zip(self.stage_btns, core.stage_states(self.project)):
                b.set_status(state, f"Stage {num}, {name}: {labels[state]}\n{note}\nClick to ask Claude about it.")

        def toggle_theme(self) -> None:
            self.set_theme_choice("day" if theme.CURRENT["name"] == "night" else "night")

        def set_theme_choice(self, choice: str) -> None:
            self.theme_choice = choice
            theme.save_choice(choice)
            theme.set_theme(theme.resolve(choice))
            self.apply_theme()

        def apply_theme(self) -> None:
            night = theme.CURRENT["name"] == "night"
            self.theme_btn.SetLabel("☀" if night else "☾")
            self.theme_btn.SetToolTip("Switch to day colours" if night else "Switch to night colours")
            self.SetBackgroundColour(theme.T["bg"])
            theme.apply_colours(self.panel)
            self.repaint_log()
            self.update_controls()
            self.Refresh()

        def show_menu(self) -> None:
            m = wx.Menu()

            def radio(sub, items, current, pick):
                for i, text in enumerate(items):
                    it = sub.AppendRadioItem(wx.ID_ANY, text)
                    it.Check(i == current)
                    self.Bind(wx.EVT_MENU, lambda e, i=i: pick(i), it)
            mode = wx.Menu()
            radio(mode, [core.MODES[k][0] for k in core.MODES], list(core.MODES).index(self.mode), self.pick_mode)
            m.AppendSubMenu(mode, "How much Claude may do")
            model = wx.Menu()
            radio(model, [core.MODELS[k][0] for k in core.MODELS], list(core.MODELS).index(self.model_key),
                  self.pick_model)
            m.AppendSubMenu(model, "Model")
            look = wx.Menu()
            choices = ["auto", "day", "night"]
            radio(look, ["Follow my computer", "Day", "Night"], choices.index(self.theme_choice)
                  if self.theme_choice in choices else 0, lambda i: self.set_theme_choice(choices[i]))
            m.AppendSubMenu(look, "Colours")
            m.AppendSeparator()
            if bw_dock.Dock.available():
                it = m.AppendCheckItem(wx.ID_ANY, "Dock to the PCB Editor")
                it.Check(self.dock_btn.GetValue())
                self.Bind(wx.EVT_MENU, lambda e: (self.dock_btn.SetValue(not self.dock_btn.GetValue()),
                                                  self.on_dock_toggle(None)), it)
            it = m.Append(wx.ID_ANY, "New chat")
            it.Enable(not self.busy)
            self.Bind(wx.EVT_MENU, lambda e: self.new_chat(), it)
            kt = wx.Menu()
            radio(kt, list(core.KICAD_TOOLS.values()), list(core.KICAD_TOOLS).index(self.kicad_tools),
                  self.pick_kicad_tools)
            m.AppendSubMenu(kt, "KiCad editing tools")
            it = m.Append(wx.ID_ANY, "Setup checks")
            self.Bind(wx.EVT_MENU, lambda e: self.toggle_setup(), it)
            m.AppendSeparator()
            it = m.Append(wx.ID_ANY, "Send feedback\u2026")
            self.Bind(wx.EVT_MENU, lambda e: self.send_feedback(), it)
            it = m.AppendCheckItem(wx.ID_ANY, "Keep a usage log for this board")
            it.Check(core.usage_log_on(self.project))
            self.Bind(wx.EVT_MENU, lambda e: self.toggle_usage_log(), it)
            self.menu_btn.PopupMenu(m, (0, self.menu_btn.GetSize().height + 4))
            m.Destroy()

        def _place(self, w: int, side: str) -> None:
            area = wx.Display(0).GetClientArea()
            w = max(340, min(w, area.width))
            x = area.x + (0 if side == "left" else area.width - w)
            self.SetSize(wx.Rect(x, area.y, w, area.height))

        # ---------------- transcript ----------------
        # roles: text, dim, you, you_msg (your message, tinted), claude, tool, ok, bad, warn
        def _paint_seg(self, text: str, role: str, bold: bool) -> None:
            T = theme.T
            fg = {"you_msg": T["text"], "tool": T["tool"]}.get(role) or T.get(role) or T["text"]
            attr = wx.TextAttr(fg, T["you_bg"] if role == "you_msg" else T["bg"])
            f = self.log.GetFont()
            f.SetWeight(wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL)
            attr.SetFont(f)
            self.log.SetDefaultStyle(attr)
            self.log.AppendText(text)

        def add(self, text: str, colour: str = "text", bold: bool = False) -> None:
            if not text:
                return
            if self.segs and self.segs[-1][1] == colour and self.segs[-1][2] == bold:
                self.segs[-1] = (self.segs[-1][0] + text, colour, bold)
            else:
                self.segs.append((text, colour, bold))
            self._paint_seg(text, colour, bold)
            self.at_line_start = text.endswith("\n")
            self.log.ShowPosition(self.log.GetLastPosition())

        def repaint_log(self) -> None:
            """Draw the whole transcript again in the current colours."""
            self.log.Freeze()
            try:
                self.log.Clear()
                for text, role, bold in self.segs:
                    self._paint_seg(text, role, bold)
            finally:
                self.log.Thaw()
            self.log.ShowPosition(self.log.GetLastPosition())

        def fresh_line(self) -> None:
            if not self.at_line_start:
                self.add("\n")

        def line(self, text: str, colour: str = "dim", bold: bool = False) -> None:
            """A note on its own line."""
            self.fresh_line()
            self.add(text + "\n", colour, bold)

        # ---------------- first-run checks ----------------
        def recheck(self) -> None:
            self.recheck_btn.Disable()
            for lab, btn in self.rows.values():
                lab.SetLabel("checking...")
                lab.bw_fg = "dim"
                lab.SetForegroundColour(self.col["dim"])
                btn.Hide()

            def work() -> None:
                res = core.run_all_checks(claude_override)
                wx.CallAfter(self.show_checks, res)
            threading.Thread(target=work, daemon=True).start()

        def set_row(self, key: str, state: str, text: str, button: str = "") -> None:
            lab, btn = self.rows[key]
            mark = {"ok": "✓", "bad": "✗", "warn": "!"}[state]
            lab.SetLabel(f"{mark}  {text}")
            lab.bw_fg = state
            lab.SetForegroundColour(self.col[state])
            btn.SetLabel(button)
            btn.Show(bool(button))

        def show_checks(self, res: dict) -> None:
            was_ready = bool(self.checks and self.checks["ready"])
            self.checks = res
            c, a, pl = res["claude"], res["auth"], res["plugin"]
            notes = []
            if c["ok"]:
                self.set_row("claude", "ok", f"Claude Code installed ({c['version'] or 'version unknown'})")
            else:
                self.set_row("claude", "bad", "Claude Code is not installed", "How to install")
                cmd = core.INSTALL_COMMANDS.get(sys.platform, core.INSTALL_COMMANDS["linux"])
                notes.append("Install Claude Code: open " + ("PowerShell" if sys.platform == "win32" else "a terminal") +
                             " and run\n    " + cmd +
                             "\nthen press 'Check again'. The button opens the official instructions "
                             "and copies this command.")
            if not c["ok"]:
                self.set_row("auth", "warn", "Sign-in: checked after Claude Code is installed")
                self.set_row("plugin", "warn", "boardwright plugin: checked after Claude Code is installed")
            else:
                if a["ok"]:
                    self.set_row("auth", "ok", "Signed in to Claude")
                elif self.waiting_login:
                    self.set_row("auth", "warn", "Waiting for you to finish signing in...", "Sign in again")
                else:
                    self.set_row("auth", "bad", "Not signed in to Claude", "Sign in")
                    notes.append("'Sign in' starts Claude Code's own sign-in: a small black window opens "
                                 "and your browser asks you to log in to Claude. This plugin never sees "
                                 "your password or any key.")
                if pl["ok"] and pl.get("older"):
                    self.set_row("plugin", "warn", f"an older Boardwright ({pl.get('version')}) is installed; the chat "
                                 f"uses the newer one that came with this add-on ({pl.get('bundle_version')})")
                    notes.append(f"An older Boardwright ({pl.get('version')}) is installed; the chat uses the newer one "
                                 f"that came with this add-on ({pl.get('bundle_version')}). Update with:  "
                                 + core.PLUGIN_UPDATE_COMMAND)
                elif pl["ok"]:
                    self.set_row("plugin", "ok", f"boardwright plugin installed ({pl.get('version') or '?'})")
                elif pl["installed"]:
                    self.set_row("plugin", "warn", "boardwright plugin is installed but switched off")
                    notes.append("Switch it on with:  claude plugin enable " + core.PLUGIN_ID)
                elif res["bundle"]:
                    self.set_row("plugin", "warn", "boardwright plugin not installed (using the built-in copy)",
                                 "Install")
                    cmds = core.plugin_install_commands()
                    notes.append("This chat loads the copy that came with the KiCad add-on. To have it in "
                                 "every Claude Code session, press Install, or run:\n    "
                                 + "\n    ".join(" ".join(f'"{x}"' if " " in x else x for x in cm) for cm in cmds))
                else:
                    self.set_row("plugin", "bad", "boardwright plugin not installed")
                    notes.append("Install the boardwright Claude Code plugin, then press 'Check again'.")
            missing = [h["name"] for h in res["helpers"] if not h["ok"]]
            if missing:
                self.set_row("helpers", "warn", "KiCad tools missing: " + ", ".join(missing), "Install helpers")
                notes.append("Without " + ", ".join(missing) + " Claude can chat and read files but cannot "
                             "drive KiCad. 'Install helpers' opens a console that asks before each install "
                             "(uv, kicad-buddy, the schematic tools) and can tick KiCad's API setting.")
            else:
                self.set_row("helpers", "ok", "KiCad tools found (kicad-buddy, uvx, kicad-cli)")
            eng = res.get("engine") or {"ok": False}
            if eng["ok"]:
                self.set_row("engine", "ok", "Routing engine installed (Freerouting, KiCadRoutingTools)")
            else:
                self.set_row("engine", "warn", "Routing engine not installed (optional)", "Install engine")
                notes.append("The routing engine routes most nets for you before Claude steps in, which saves "
                             "time and your Claude plan. 'Install engine' shows what it downloads and asks first.")
            self.setup_note.SetValue("\n".join(notes))
            self.setup_note.Show(bool(notes))
            self.recheck_btn.Enable()
            all_ok = res["ready"] and pl and pl["ok"] and not pl.get("older") and not missing
            if not res["ready"] or not was_ready:
                self.setup.Show(not all_ok)
            if res["ready"] and not was_ready:
                self.waiting_login = False
                self.line("Ready. Type a question below.", "ok")
                self.after_sign_in()
            self.update_controls()
            self.panel.Layout()

        # ---------------- usage log and feedback ----------------
        def after_sign_in(self) -> None:
            """Ask once, right after sign-in, whether to keep a usage log; apply a 'yes' to each board opened."""
            answer = core.settings_get("usage_log")
            if answer is None:
                self.feedback_card.Show()
                self.panel.Layout()
            elif answer.get("on") and not core.usage_log_decided(self.project):
                core.set_usage_log(self.project, True, bool(answer.get("prompts")),
                                   "chat: the user said yes to the usage log for every board")

        def answer_usage_log(self, on: bool) -> None:
            prompts = bool(on and self.fb_prompts.GetValue())
            core.settings_set("usage_log", {"on": on, "prompts": prompts})
            ok = core.set_usage_log(self.project, on, prompts,
                                    "chat: the user clicked " + ("Yes" if on else "No thanks"))
            self.feedback_card.Hide()
            self.panel.Layout()
            if on:
                self.line("Thanks. A private usage log is kept on this computer. Nothing is sent: use "
                          "\u22ef \u2192 Send feedback when you want to share it." if ok else
                          "Could not switch the usage log on (the plugin copy was not found).", "ok" if ok else "bad")
            else:
                self.line("No usage log is kept. You can still send feedback from the \u22ef menu.", "dim")

        def toggle_usage_log(self) -> None:
            on = not core.usage_log_on(self.project)
            prev = core.settings_get("usage_log") or {}
            core.settings_set("usage_log", {"on": on, "prompts": bool(prev.get("prompts")) and on})
            core.set_usage_log(self.project, on, bool(prev.get("prompts")) and on,
                               "chat: the user switched the usage log " + ("on" if on else "off") + " in the menu")
            self.line("Usage log " + ("on" if on else "off") + " for this board.", "dim")

        def send_feedback(self) -> None:
            """The user's feedback (and, if the usage log is on, its redacted report) as a GitHub issue they
            post themselves: the text goes on the clipboard and the browser opens the new-issue page."""
            dlg = wx.TextEntryDialog(self, "What should we know? What worked, what didn't, what you expected.",
                                     "Send feedback", style=wx.TextEntryDialogStyle | wx.TE_MULTILINE)
            dlg.SetSize((460, 300))
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
            text = dlg.GetValue().strip()
            dlg.Destroy()
            parts = ["## Feedback", "", text or "(no text)", ""]
            if core.usage_log_on(self.project):
                wx.BeginBusyCursor()
                try:
                    report, note = core.build_report(self.project)
                finally:
                    wx.EndBusyCursor()
                if report:
                    if len(report) > 60000:
                        report = report[:60000] + "\n\n(cut: the full report is at " + note + ")"
                    parts += ["## Usage report (redacted)", "", report]
                else:
                    parts += [f"(no usage report: {note})"]
            parts += ["", f"Add-on {core.bundle_version() or '?'}, {sys.platform}"]
            body = "\n".join(parts)
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(body))
                wx.TheClipboard.Close()
            webbrowser.open(core.feedback_issue_url())
            wx.MessageBox("Your feedback is on the clipboard. In the GitHub page that opened, paste it into the "
                          "description, read it, and press Submit. Nothing is sent until you do.",
                          "Send feedback", wx.OK | wx.ICON_INFORMATION, self)

        def toggle_setup(self) -> None:
            self.setup.Show(not self.setup.IsShown())
            self.panel.Layout()

        def on_install_claude(self) -> None:
            cmd = core.INSTALL_COMMANDS.get(sys.platform, core.INSTALL_COMMANDS["linux"])
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject(cmd))
                wx.TheClipboard.Close()
            webbrowser.open(core.INSTALL_DOCS_URL)
            self.line("Opened the official install page; the install command is on the clipboard. "
                      "Press 'Check again' when it has finished.")

        def on_install_helpers(self) -> None:
            err = core.start_helper_setup()
            if err:
                self.line(err, "bad")
                return
            self.line("A console window opened with the helper setup. Answer its questions there, "
                      "then press 'Check again'.", "dim")

        def on_install_engine(self) -> None:
            msg = core.engine_downloads_text() + "\n\nA console window shows the progress. Install now?"
            if wx.MessageBox(msg, "Install the routing engine", wx.YES_NO | wx.ICON_QUESTION, self) != wx.YES:
                return
            err = core.start_engine_setup()
            if err:
                self.line(err, "bad")
                return
            self.line("The routing engine is installing in its own window. Press 'Check again' when it "
                      "says it has finished.", "dim")

        def on_sign_in(self) -> None:
            claude = self.checks["claude"]["path"]
            err = core.start_login(claude)
            if err:
                self.line(err, "bad")
                return
            self.waiting_login = True
            self.line("Claude Code's sign-in has started in its own window. Finish it in your browser; "
                      "this window continues by itself.")
            self.set_row("auth", "warn", "Waiting for you to finish signing in...", "Sign in again")
            self.panel.Layout()

            def poll() -> None:
                for _ in range(200):                       # about 10 minutes
                    if not self.waiting_login:
                        return
                    threading.Event().wait(3)
                    if core.check_auth(claude)["ok"]:
                        wx.CallAfter(self.recheck)
                        return
                wx.CallAfter(self.login_timeout)
            threading.Thread(target=poll, daemon=True).start()

        def login_timeout(self) -> None:
            self.waiting_login = False
            self.recheck()

        def on_install_plugin(self) -> None:
            claude = self.checks["claude"]["path"]
            self.rows["plugin"][1].Disable()
            self.line("Installing the boardwright Claude Code plugin...")

            def work() -> None:
                ok, text = core.install_plugin(claude)
                wx.CallAfter(done, ok, text)

            def done(ok: bool, text: str) -> None:
                self.line(text, "dim" if ok else "bad")
                self.rows["plugin"][1].Enable()
                if ok and self.session:            # running chat still uses the built-in copy
                    self.line("Installed. New chats will use it.", "ok")
                self.recheck()
            threading.Thread(target=work, daemon=True).start()

        # ---------------- state ----------------
        @property
        def busy(self) -> bool:
            return bool(self.session and self.session.busy)

        def update_controls(self) -> None:
            ready = bool(self.checks and self.checks["ready"])
            self.send_btn.Enable(ready and not self.busy)
            self.stop_btn.Enable(self.busy)
            self.box.busy(self.busy)
            self.ring.spin(self.busy)
            for b in self.quick_btns:
                b.Enable(ready and not self.busy)
            bits = [core.MODES[self.mode][0]]
            if self.session_kicad is not None:
                bits.append("KiCad tools " + ("on" if self.session_kicad else "off"))
            if self.model_key != "default":
                bits.append(core.MODELS[self.model_key][0])
            elif self.model:
                bits.append(self.model)
            if self.busy:
                bits.insert(0, "Claude is working\u2026")
            elif self.last_turn:
                bits.append(self.last_turn)
            self.status.SetStatusText("   \u00b7   ".join(bits))
            self.panel.Layout()

        # ---------------- chat ----------------
        def ensure_session(self) -> bool:
            if self.session and self.session.alive:
                return True
            ch = self.checks
            pl = ch["plugin"]
            use_bundle = ch["bundle"] and not (pl and pl["installed"] and not pl.get("older"))
            # the KiCad editing tools only when they are needed (they double the tokens of every question)
            self.session_kicad = core.kicad_tools_wanted(self.project, self.kicad_tools)
            lean = None
            if not self.session_kicad:
                root = core.bundle_dir() / "plugin" if ch["bundle"] else None
                lean = core.lean_mcp_config(root)
                self.session_kicad = lean is None          # no plugin copy to point at: load everything
            argv = core.build_argv(ch["claude"]["path"], self.mode, resume=self.resume_id,
                                   plugin_dir=str(core.bundle_dir() / "plugin") if use_bundle else None,
                                   model=self.model_key, lean_mcp=lean)
            sess = core.ClaudeSession(argv, self.project,
                                      lambda k, p, s=None: wx.CallAfter(self.on_event, sess, k, p))
            try:
                sess.start()
            except OSError as exc:
                self.line(f"Could not start Claude Code: {exc}", "bad")
                return False
            self.session = sess
            self.cost_seen = 0.0
            return True

        def drop_session(self, keep_chat: bool = True) -> None:
            if self.session:
                self.resume_id = (self.session.session_id or self.resume_id) if keep_chat else None
                old, self.session = self.session, None
                threading.Thread(target=old.close, daemon=True).start()
            elif not keep_chat:
                self.resume_id = None
            self.pending.clear()
            self.show_permission()

        def new_chat(self) -> None:
            self.drop_session(keep_chat=False)
            self.last_turn = ""
            self.log.Clear()
            self.segs = []
            self.at_line_start = True
            self.talked = False
            self.build_welcome()
            self.add("New chat\n\n", "dim")
            self.update_controls()

        def pick_mode(self, i: int) -> None:
            self.mode = list(core.MODES)[i]
            core.settings_set("mode", self.mode)
            self.drop_session(keep_chat=True)       # applies from the next message, same chat
            self.line(f"Mode: {core.MODES[self.mode][0]}")
            self.update_controls()

        def pick_model(self, i: int) -> None:
            self.model_key = list(core.MODELS)[i]
            core.settings_set("model", self.model_key)
            self.drop_session(keep_chat=True)       # applies from the next message, same chat
            self.line(core.MODELS[self.model_key][0] if self.model_key != "default"
                      else "Model: your Claude Code default")
            self.update_controls()

        def on_key(self, e) -> None:
            if e.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not e.ShiftDown():
                self.send_input()
            elif e.GetKeyCode() == wx.WXK_ESCAPE and self.busy:
                self.stop()
            else:
                e.Skip()

        def send_input(self) -> None:
            text = self.inp.GetValue().strip()
            if text and self.send(text):
                self.inp.Clear()

        def send(self, text: str) -> bool:
            if not (self.checks and self.checks["ready"]) or self.busy:
                return False
            if not self.ensure_session():
                return False
            if not self.talked:
                self.talked = True
                self.show_view()
            self.fresh_line()
            self.add("\u25cf You\n", "you", bold=True)
            self.add(" " + text.replace("\n", "\n ") + " \n", "you_msg")
            self.add("\n", "text")
            if not self.session.send(text):
                self.line("Claude Code is not running; try again.", "bad")
                self.drop_session()
                return False
            self.need_header = True
            self.turn_text = ""
            self.update_controls()
            return True

        def header(self) -> None:
            if self.need_header:
                self.need_header = False
                self.fresh_line()
                self.add("\u25c6 Claude\n", "claude", bold=True)

        def stop(self) -> None:
            if not self.busy:
                return
            self.session.interrupt()
            self.line("Stopping...", "warn")
            self.stop_btn.Disable()
            self.stop_timer.StartOnce(6000)

        def on_stop_timeout(self, _e) -> None:
            if self.busy:                      # did not stop by itself: end the process, keep the chat
                self.session.kill()

        def on_event(self, sess, kind: str, p) -> None:
            if sess is not self.session:
                return                          # a chat that was already closed
            if kind == "init":
                self.model = str(p.get("model") or "")
                bad = [n for n, s in p.get("mcp") or [] if s not in ("connected", "pending")]
                if bad:
                    self.line("KiCad tools that did not start: " + ", ".join(map(str, bad)), "warn")
            elif kind == "text":
                self.header()
                self.add(p)
                self.turn_text += p
            elif kind == "tool":
                self.line(("      \u203a " if p["sub"] else "   \u203a ") + p["summary"], "tool")
                self.need_header = True
            elif kind == "tool_error":
                self.line("   ! " + p, "warn")
            elif kind == "permission":
                self.pending.append(p)
                self.show_permission()
            elif kind == "permission_cancel":
                self.pending = [q for q in self.pending if q["request_id"] != p]
                self.show_permission()
            elif kind == "raw":
                self.line("[claude] " + p[:400], "warn")
            elif kind == "result":
                self.stop_timer.Stop()
                self.pending.clear()
                self.show_permission()
                if p["is_error"] and p["text"] and p["text"] not in self.turn_text:
                    self.line(p["text"], "bad")
                if p["is_error"] and core.looks_like_limit(p["text"]):
                    self.line("Pick another model in the model menu at the top and send again; "
                              "the chat carries on.", "dim")
                if p["auth"]:
                    self.line("Claude Code says you are not signed in. Use 'Sign in' above.", "bad")
                    self.drop_session()
                    self.setup.Show()
                    self.recheck()
                bits = []
                if p.get("cost") is not None:
                    total = float(p["cost"] or 0)
                    turn = max(0.0, total - self.cost_seen)    # the running total includes earlier answers
                    self.cost_seen = total
                    bits.append(f"about ${turn:.3f}")
                bits.append(f"{p['tokens_in']:,} in / {p['tokens_out']:,} out")
                self.last_turn = "last answer " + ", ".join(bits)
                self.remember_chat()
                self.refresh_stages()
                self.check_tool_set()
                self.fresh_line()
                self.add("\n")
            elif kind == "exit":
                self.stop_timer.Stop()
                code = p.get("code")
                self.resume_id = sess.session_id or self.resume_id
                self.session = None
                self.pending.clear()
                self.show_permission()
                if p.get("killed"):
                    self.line("Stopped. Your next message continues this chat.", "warn")
                elif code not in (0, None):
                    self.line(f"Claude Code ended (exit code {code}). Your next message starts it again.", "bad")
            self.update_controls()

        # ---------------- permission requests ----------------
        def show_permission(self) -> None:
            if not self.pending:
                if self.perm.IsShown():
                    self.perm.Hide()
                    self.panel.Layout()
                return
            p = self.pending[0]
            if p["tool_name"] == "AskUserQuestion":
                self.pending.pop(0)
                self.ask_questions(p)
                wx.CallAfter(self.show_permission)
                return
            self.perm_label.SetLabel("\u26a0  Claude asks: may it use " + p["summary"].split(":")[0] + "?")
            detail = p.get("title") or ""
            body =json.dumps(p["input"], indent=2, ensure_ascii=False)
            self.perm_detail.SetValue((detail + "\n" if detail else "") + body)
            self.always_btn.Show(bool(p.get("suggestions")))
            self.perm.Show()
            self.panel.Layout()
            self.RequestUserAttention()

        def answer(self, allow: bool, remember: bool = False) -> None:
            if not self.pending or not self.session:
                return
            p = self.pending.pop(0)
            if allow:
                self.session.allow(p["request_id"], p["input"], p["suggestions"] if remember else None)
                self.line("   Allowed" + (" (and remembered)" if remember else ""), "dim")
            else:
                self.session.deny(p["request_id"])
                self.line("   Denied", "warn")
            self.show_permission()

        def ask_questions(self, p: dict) -> None:
            """Claude's multiple-choice questions (AskUserQuestion)."""
            answers = {}
            sess = self.session          # Claude Code may exit while a dialog is open

            def reply_ok() -> bool:
                if sess is None or self.session is not sess:
                    self.line("    Claude Code ended while the question was open; no answer was sent", "warn")
                    return False
                return True
            for q in p["input"].get("questions") or []:
                text = str(q.get("question", ""))
                opts = [o for o in q.get("options") or [] if isinstance(o, dict)]
                labels = [str(o.get("label", "")) + (f"  -  {o['description']}" if o.get("description") else "")
                          for o in opts] + ["Other (type my own answer)"]
                picked = None
                if q.get("multiSelect"):
                    dlg = wx.MultiChoiceDialog(self, text, str(q.get("header") or "Claude asks"), labels)
                    if dlg.ShowModal() == wx.ID_OK:
                        picked = dlg.GetSelections()
                else:
                    dlg = wx.SingleChoiceDialog(self, text, str(q.get("header") or "Claude asks"), labels)
                    if dlg.ShowModal() == wx.ID_OK:
                        picked = [dlg.GetSelection()]
                dlg.Destroy()
                if picked is None:
                    if reply_ok():
                        sess.deny(p["request_id"], "The user closed the question without answering.")
                        self.line("    question closed without an answer", "warn")
                    return
                vals = []
                for i in picked:
                    if i < len(opts):
                        vals.append(str(opts[i].get("label", "")))
                    else:
                        t = wx.TextEntryDialog(self, text, "Your answer")
                        if t.ShowModal() == wx.ID_OK and t.GetValue().strip():
                            vals.append(t.GetValue().strip())
                        t.Destroy()
                answers[text] = ", ".join(vals)
                self.line(f"    {text}  →  {answers[text]}", "you")
            if reply_ok():
                sess.allow(p["request_id"], dict(p["input"], answers=answers))

        # ---------------- docking to the PCB Editor ----------------
        def try_dock(self) -> None:
            """Dock at start; KiCad may still be drawing the PCB Editor, so try a few times."""
            if self.dock.docked or not bw_dock.Dock.available():
                return
            if self.dock.attach():
                self.dock_timer.Start(300)
                self.status.SetStatusText("Docked to the PCB Editor. Click Dock to float the chat.")
            elif self.dock_tries < 5:
                self.dock_tries += 1
                wx.CallLater(1000, self.try_dock)

        def on_dock_toggle(self, e) -> None:
            if self.dock_btn.GetValue():
                if self.dock.attach():
                    self.dock_timer.Start(300)
                    self.status.SetStatusText("Docked to the PCB Editor.")
                else:
                    self.dock_btn.SetValue(False)
                    self.status.SetStatusText("The PCB Editor for this board is not open, so there is nothing to dock to.")
            else:
                self.dock_timer.Stop()
                self.dock.detach()
                self.status.SetStatusText("Floating. Click Dock to attach the chat to the PCB Editor again.")

        def on_close(self, e) -> None:
            self.stage_timer.Stop()
            self.ring.active(False)
            self.dock_timer.Stop()
            self.dock.detach()
            self.waiting_login = False
            if self.session:
                self.session.kill()
            self.beat.Stop()
            core.release_lock(self.project)
            e.Skip()

    app = wx.App(False)
    theme_choice = theme_arg or theme.load_choice()
    theme.set_theme(theme.resolve(theme_choice))
    if theme.CURRENT["name"] == "night" and hasattr(app, "MSWEnableDarkMode"):
        try:
            app.MSWEnableDarkMode(1)            # dark scrollbars, menus and dialogs on Windows
        except Exception:
            pass
    if not core.acquire_lock(project):
        core.raise_window(project)
        out(f"{core.APP_NAME} is already open for {project}")
        return 3
    frame = Frame()
    frame.Show()
    frame.inp.SetFocus()
    if selftest:
        state = {"ok": False}

        def demo_chat() -> None:
            """Selftest pictures only: a made-up exchange and a permission request, nothing is sent."""
            frame.setup.Hide()
            frame.talked = True
            frame.show_view()
            frame.add("● You\n", "you", bold=True)
            frame.add(" Where does this board stand? \n", "you_msg")
            frame.add("\n◆ Claude\n", "claude", bold=True)
            frame.add("   › Read reports/07-bom.md\n", "tool")
            frame.add("Stages 1 and 3 to 6 are done. Stage 2 (parts) and stage 7 (BOM) need attention: "
                      "R3 is out of stock.\n", "text")
            frame.add("✓ DRC: 0 errors\n", "ok")
            frame.pending = [{"tool_name": "Edit", "summary": "Edit: reports/07-bom.md", "request_id": "demo",
                              "input": {"file_path": "reports/07-bom.md"}, "suggestions": [{}], "title": ""}]
            frame.show_permission()
            frame.panel.Layout()

        def finish() -> None:
            if snapshot:
                shots = [(t, v) for v in ("welcome", "setup", "consent", "home", "chat") for t in ("day", "night")] \
                    if "*" in snapshot else [(None, "welcome")]
                for name, view in shots:
                    if view == "setup":
                        frame.feedback_card.Hide()
                        frame.setup.Show()
                        frame.panel.Layout()
                    if view == "home":
                        frame.setup.Hide()
                        frame.feedback_card.Hide()
                        frame.panel.Layout()
                    if view == "consent":
                        frame.setup.Hide()
                        frame.feedback_card.Show()
                        frame.panel.Layout()
                    if view == "chat" and frame.home.IsShown():
                        demo_chat()
                    if name:
                        theme.set_theme(name)
                        frame.apply_theme()
                    frame.Update()
                    wx.Yield()
                    w, h = frame.GetSize()
                    bmp = wx.Bitmap(w, h)
                    mdc = wx.MemoryDC(bmp)
                    if os.name == "nt":             # PrintWindow draws it even when other windows cover it
                        import ctypes
                        pw = ctypes.windll.user32.PrintWindow
                        pw.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
                        pw(frame.GetHandle(), mdc.GetHandle(), 2)
                    else:
                        mdc.Blit(0, 0, w, h, wx.WindowDC(frame), 0, 0)
                    mdc.SelectObject(wx.NullBitmap)
                    bmp.SaveFile(snapshot.replace("*", f"{name}-{view}" if name else ""), wx.BITMAP_TYPE_PNG)
            state["ok"] = frame.IsShown() and frame.GetSize().width > 0 and frame.checks is not None
            out(f"selftest: shown={frame.IsShown()} size={tuple(frame.GetSize())} checks={frame.checks}")
            frame.Close()
        wx.CallLater(8000, finish)
        app.MainLoop()
        core.release_lock(project)
        return 0 if state["ok"] else 1
    app.MainLoop()
    core.release_lock(project)
    return 0


def ask_project_dialog() -> Optional[str]:
    import wx
    app = wx.App(False)
    dlg = wx.DirDialog(None, "Boardwright: choose the folder of your KiCad project")
    path = dlg.GetPath() if dlg.ShowModal() == wx.ID_OK else None
    dlg.Destroy()
    del app
    return path


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Boardwright chat window")
    ap.add_argument("--project", help="project folder (Claude Code runs here)")
    ap.add_argument("--ask-project", action="store_true", help="show a folder dialog first")
    ap.add_argument("--selftest", action="store_true", help="open, run the checks, exit 0")
    ap.add_argument("--claude", help="path of the claude executable")
    ap.add_argument("--mode", choices=list(core.MODES), default=core.DEFAULT_MODE)
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    ap.add_argument("--side", choices=("right", "left"), default="right")
    ap.add_argument("--theme", choices=("auto", "day", "night"), help="colours (default: your last choice)")
    ap.add_argument("--snapshot", help=argparse.SUPPRESS)      # selftest: save a picture of the window
    a = ap.parse_args(list(argv) if argv is not None else None)
    project = a.project
    if a.ask_project or not project:
        project = ask_project_dialog()
        if not project:
            return 2
    project = os.path.abspath(project)
    if not os.path.isdir(project):
        out(f"project folder not found: {project}")
        return 2
    return run_gui(project, a.claude, a.selftest, a.mode, a.width, a.side, a.theme, a.snapshot)


if __name__ == "__main__":
    sys.exit(main())
