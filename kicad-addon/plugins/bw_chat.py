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

DEFAULT_WIDTH = 480
QUICK = (("Check setup", "/boardwright:pcb-doctor"),
         ("Continue", "/boardwright:pcb-run"),
         ("Run gates", "/boardwright:pcb-gates"),
         ("Review board", "/boardwright:pcb-review"))


def out(msg: str) -> None:
    if sys.stdout is not None:
        try:
            print(msg, flush=True)
        except Exception:
            pass


def run_gui(project: str, claude_override: Optional[str], selftest: bool, mode: str,
            width: int, side: str) -> int:
    import wx

    class Frame(wx.Frame):
        def __init__(self) -> None:
            super().__init__(None, title=core.window_title(project))
            self.project = project
            self.mode = mode
            self.model_key = core.DEFAULT_MODEL
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
            dark = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW).GetLuminance() < 0.5
            self.col = {
                "text": wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
                "you": wx.Colour(110, 170, 255) if dark else wx.Colour(0, 70, 170),
                "dim": wx.Colour(150, 150, 150) if dark else wx.Colour(105, 105, 105),
                "bad": wx.Colour(255, 110, 110) if dark else wx.Colour(180, 0, 0),
                "ok": wx.Colour(110, 200, 130) if dark else wx.Colour(20, 120, 50),
                "warn": wx.Colour(235, 180, 80) if dark else wx.Colour(160, 100, 0),
            }
            self._build()
            self._place(width, side)
            self.Bind(wx.EVT_CLOSE, self.on_close)
            self.beat = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda e: core.acquire_lock(self.project), self.beat)
            self.beat.Start(15000)
            self.stop_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_stop_timeout, self.stop_timer)
            self.add(f"{core.APP_NAME}  ·  {self.project}\n", "dim")
            self.add("This window talks to your own Claude Code. Messages use your Claude plan.\n\n", "dim")
            self.update_controls()
            self.recheck()

        # ---------------- layout ----------------
        def _build(self) -> None:
            p = self.panel = wx.Panel(self)
            root = wx.BoxSizer(wx.VERTICAL)

            top = wx.BoxSizer(wx.HORIZONTAL)
            self.mode_choice = wx.Choice(p, choices=[core.MODES[k][0] for k in core.MODES])
            self.mode_choice.SetSelection(list(core.MODES).index(self.mode))
            self.mode_choice.Bind(wx.EVT_CHOICE, self.on_mode)
            self.model_choice = wx.Choice(p, choices=[core.MODELS[k][0] for k in core.MODELS])
            self.model_choice.SetSelection(list(core.MODELS).index(self.model_key))
            self.model_choice.Bind(wx.EVT_CHOICE, self.on_model)
            self.new_btn = wx.Button(p, label="New chat")
            self.new_btn.Bind(wx.EVT_BUTTON, lambda e: self.new_chat())
            self.setup_btn = wx.Button(p, label="Setup")
            self.setup_btn.Bind(wx.EVT_BUTTON, lambda e: self.toggle_setup())
            top.Add(self.mode_choice, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
            top.Add(self.model_choice, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
            top.Add(self.new_btn, 0, wx.RIGHT, 4)
            top.Add(self.setup_btn, 0)
            root.Add(top, 0, wx.EXPAND | wx.ALL, 6)

            # --- setup panel (first run) ---
            self.setup = wx.Panel(p)
            box = wx.StaticBoxSizer(wx.VERTICAL, self.setup, "Setup")
            sb = box.GetStaticBox()
            self.rows = {}
            grid = wx.FlexGridSizer(cols=2, vgap=4, hgap=8)
            grid.AddGrowableCol(0, 1)
            for key in ("claude", "auth", "plugin", "helpers"):
                lab = wx.StaticText(sb, label="checking...")
                btn = wx.Button(sb, label="", style=wx.BU_EXACTFIT)
                btn.Hide()
                grid.Add(lab, 1, wx.ALIGN_CENTER_VERTICAL | wx.EXPAND)
                grid.Add(btn, 0, wx.ALIGN_CENTER_VERTICAL)
                self.rows[key] = (lab, btn)
            self.rows["claude"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_install_claude())
            self.rows["auth"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_sign_in())
            self.rows["plugin"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_install_plugin())
            self.rows["helpers"][1].Bind(wx.EVT_BUTTON, lambda e: self.on_install_helpers())
            box.Add(grid, 0, wx.EXPAND | wx.ALL, 4)
            self.setup_note = wx.TextCtrl(sb, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE,
                                          size=(-1, 54))
            self.setup_note.SetBackgroundColour(sb.GetBackgroundColour())
            box.Add(self.setup_note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 4)
            row = wx.BoxSizer(wx.HORIZONTAL)
            self.recheck_btn = wx.Button(sb, label="Check again")
            self.recheck_btn.Bind(wx.EVT_BUTTON, lambda e: self.recheck())
            row.Add(self.recheck_btn, 0)
            box.Add(row, 0, wx.ALL, 4)
            self.setup.SetSizer(box)
            root.Add(self.setup, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

            self.log = wx.TextCtrl(p, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_WORDWRAP)
            root.Add(self.log, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

            # --- permission bar ---
            self.perm = wx.Panel(p)
            ps = wx.BoxSizer(wx.VERTICAL)
            self.perm_label = wx.StaticText(self.perm, label="")
            f = self.perm_label.GetFont()
            f.SetWeight(wx.FONTWEIGHT_BOLD)
            self.perm_label.SetFont(f)
            self.perm_detail = wx.TextCtrl(self.perm, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 70))
            pr = wx.BoxSizer(wx.HORIZONTAL)
            self.allow_btn = wx.Button(self.perm, label="Allow")
            self.always_btn = wx.Button(self.perm, label="Allow, don't ask again")
            self.deny_btn = wx.Button(self.perm, label="Deny")
            self.allow_btn.Bind(wx.EVT_BUTTON, lambda e: self.answer(True))
            self.always_btn.Bind(wx.EVT_BUTTON, lambda e: self.answer(True, remember=True))
            self.deny_btn.Bind(wx.EVT_BUTTON, lambda e: self.answer(False))
            for b in (self.allow_btn, self.always_btn, self.deny_btn):
                pr.Add(b, 0, wx.RIGHT, 4)
            ps.Add(self.perm_label, 0, wx.EXPAND | wx.BOTTOM, 2)
            ps.Add(self.perm_detail, 0, wx.EXPAND | wx.BOTTOM, 4)
            ps.Add(pr, 0)
            self.perm.SetSizer(ps)
            self.perm.Hide()
            root.Add(self.perm, 0, wx.EXPAND | wx.ALL, 6)

            quick = wx.BoxSizer(wx.HORIZONTAL)
            self.quick_btns = []
            for label, text in QUICK:
                b = wx.Button(p, label=label, style=wx.BU_EXACTFIT)
                b.SetToolTip(text)
                b.Bind(wx.EVT_BUTTON, lambda e, t=text: self.send(t))
                quick.Add(b, 1, wx.RIGHT, 4)
                self.quick_btns.append(b)
            root.Add(quick, 0, wx.EXPAND | wx.ALL, 6)

            self.inp = wx.TextCtrl(p, style=wx.TE_MULTILINE | wx.TE_WORDWRAP, size=(-1, 84))
            self.inp.SetHint("Ask Claude about this board  (Enter sends, Shift+Enter = new line)")
            self.inp.Bind(wx.EVT_KEY_DOWN, self.on_key)
            root.Add(self.inp, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

            row = wx.BoxSizer(wx.HORIZONTAL)
            self.send_btn = wx.Button(p, label="Send")
            self.send_btn.Bind(wx.EVT_BUTTON, lambda e: self.send_input())
            self.stop_btn = wx.Button(p, label="Stop")
            self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: self.stop())
            row.Add(self.send_btn, 1, wx.RIGHT, 4)
            row.Add(self.stop_btn, 1)
            root.Add(row, 0, wx.EXPAND | wx.ALL, 6)

            self.status = wx.StaticText(p, label="", style=wx.ST_ELLIPSIZE_END)
            self.status.SetForegroundColour(self.col["dim"])
            root.Add(self.status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
            p.SetSizer(root)

        def _place(self, w: int, side: str) -> None:
            area = wx.Display(0).GetClientArea()
            w = max(340, min(w, area.width))
            x = area.x + (0 if side == "left" else area.width - w)
            self.SetSize(wx.Rect(x, area.y, w, area.height))

        # ---------------- transcript ----------------
        def add(self, text: str, colour: str = "text", bold: bool = False) -> None:
            if not text:
                return
            attr = wx.TextAttr(self.col[colour])
            f = self.log.GetFont()
            f.SetWeight(wx.FONTWEIGHT_BOLD if bold else wx.FONTWEIGHT_NORMAL)
            attr.SetFont(f)
            self.log.SetDefaultStyle(attr)
            self.log.AppendText(text)
            self.at_line_start = text.endswith("\n")
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
                notes.append("Install Claude Code: open PowerShell and run\n    " + cmd +
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
                if pl["ok"]:
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
            self.setup_note.SetValue("\n".join(notes))
            self.setup_note.Show(bool(notes))
            self.recheck_btn.Enable()
            all_ok = res["ready"] and pl and pl["ok"] and not missing
            if not res["ready"] or not was_ready:
                self.setup.Show(not all_ok)
            if res["ready"] and not was_ready:
                self.waiting_login = False
                self.line("Ready. Type a question below.", "ok")
            self.update_controls()
            self.panel.Layout()

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
            self.new_btn.Enable(not self.busy)
            self.mode_choice.Enable(not self.busy)
            self.model_choice.Enable(not self.busy)
            for b in self.quick_btns:
                b.Enable(ready and not self.busy)
            sid = (self.session.session_id if self.session else None) or self.resume_id
            bits = [core.MODES[self.mode][0]]
            if self.model:
                bits.append(self.model)
            if sid:
                bits.append("chat " + sid[:8])
            if self.busy:
                bits.append("working...")
            elif self.last_turn:
                bits.append(self.last_turn)
            self.status.SetLabel("  |  ".join(bits))

        # ---------------- chat ----------------
        def ensure_session(self) -> bool:
            if self.session and self.session.alive:
                return True
            ch = self.checks
            use_bundle = ch["bundle"] and not (ch["plugin"] and ch["plugin"]["installed"])
            argv = core.build_argv(ch["claude"]["path"], self.mode, resume=self.resume_id,
                                   plugin_dir=str(core.bundle_dir() / "plugin") if use_bundle else None,
                                   model=self.model_key)
            sess = core.ClaudeSession(argv, self.project,
                                      lambda k, p, s=None: wx.CallAfter(self.on_event, sess, k, p))
            try:
                sess.start()
            except OSError as exc:
                self.line(f"Could not start Claude Code: {exc}", "bad")
                return False
            self.session = sess
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
            self.at_line_start = True
            self.add("New chat.\n\n", "dim")
            self.update_controls()

        def on_mode(self, _e) -> None:
            self.mode = list(core.MODES)[self.mode_choice.GetSelection()]
            self.drop_session(keep_chat=True)       # applies from the next message, same chat
            self.line(f"Mode: {core.MODES[self.mode][0]}")
            self.update_controls()

        def on_model(self, _e) -> None:
            self.model_key = list(core.MODELS)[self.model_choice.GetSelection()]
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
            self.fresh_line()
            self.add("You: ", "you", bold=True)
            self.add(text + "\n", "you")
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
                self.add("Claude: ", "text", bold=True)

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
                self.line(("    ↳ " if p["sub"] else "  ⚙ ") + p["summary"], "dim")
                self.need_header = True
            elif kind == "tool_error":
                self.line("    ✗ " + p, "warn")
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
                if p.get("cost"):
                    bits.append(f"${p['cost']:.3f}")
                bits.append(f"{p['tokens_in']} in / {p['tokens_out']} out")
                self.last_turn = "last turn " + ", ".join(bits)
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
            self.perm_label.SetLabel("Claude asks to use: " + p["summary"].split(":")[0])
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
                self.line("    allowed" + (" (and remembered)" if remember else ""), "dim")
            else:
                self.session.deny(p["request_id"])
                self.line("    denied", "warn")
            self.show_permission()

        def ask_questions(self, p: dict) -> None:
            """Claude's multiple-choice questions (AskUserQuestion)."""
            answers = {}
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
                    self.session.deny(p["request_id"], "The user closed the question without answering.")
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
            self.session.allow(p["request_id"], dict(p["input"], answers=answers))

        def on_close(self, e) -> None:
            self.waiting_login = False
            if self.session:
                self.session.kill()
            self.beat.Stop()
            core.release_lock(self.project)
            e.Skip()

    app = wx.App(False)
    if not core.acquire_lock(project):
        core.raise_window(project)
        out(f"{core.APP_NAME} is already open for {project}")
        return 3
    frame = Frame()
    frame.Show()
    frame.inp.SetFocus()
    if selftest:
        state = {"ok": False}

        def finish() -> None:
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
    return run_gui(project, a.claude, a.selftest, a.mode, a.width, a.side)


if __name__ == "__main__":
    sys.exit(main())
