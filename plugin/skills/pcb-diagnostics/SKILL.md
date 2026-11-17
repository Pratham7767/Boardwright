---
name: pcb-diagnostics
description: Optional diagnostics. The user turns recording on or off, sees what was recorded, writes a report, exports it to send back by hand, or deletes it. Nothing is ever sent automatically
model: sonnet
disable-model-invocation: true
argument-hint: "on | on without prompts | off | status | report | export | delete"
allowed-tools: Bash(python scripts/diagnostics.py . status*), Bash(python scripts/diagnostics.py . report*), Bash(python scripts/diagnostics.py . export*), Bash(python3 scripts/diagnostics.py . status*), Bash(python3 scripts/diagnostics.py . report*), Bash(python3 scripts/diagnostics.py . export*), PowerShell(python scripts/diagnostics.py . status*), PowerShell(python scripts/diagnostics.py . report*), PowerShell(python scripts/diagnostics.py . export*), Read(.boardwright/diagnostics/**), Edit(.boardwright/diagnostics/report.md)
---

You are already in the project folder: do not `cd`.

The user typed `/boardwright:pcb-diagnostics $ARGUMENTS`. Diagnostics are off unless the user turns them on. When on, the plugin keeps a record in `.boardwright/diagnostics/` on this computer: the user's prompts (unless they chose "without prompts"), which Claude models ran with their token use and cost, tool errors and refusals, failed checks, and the stage reached. Keys, e-mail addresses, the home folder and the user name are removed before anything is written. Nothing leaves the computer unless the user sends the exported file themselves.

You never turn recording on or off yourself, and you never edit the consent file: the plugin's prompt hook records the user's own words (look for its note, "Diagnostics recording turned ...").

- **on**, **on without prompts**: confirm in two lines what is recorded and where, that nothing is sent, and how to turn it off (`/boardwright:pcb-diagnostics off`) or delete it (`delete`).
- **off**: confirm. Say that what was already recorded stays until they type `/boardwright:pcb-diagnostics delete`.
- **status** (or nothing): run `python scripts/diagnostics.py . status` and explain it in plain words.
- **report**: run `python scripts/diagnostics.py . report`. Read `.boardwright/diagnostics/report.md` and fill in its "Summary in plain words" section in 5 to 10 short sentences: what was designed, how far it got, what it cost, where time and money went, and the main things that went wrong, from the numbers in the report only (no guesses). Then show the user the summary and the findings.
- **export**: do the **report** step first, then run `python scripts/diagnostics.py . export`. Show the zip's path and size and the sending instructions it printed. Remind the user to read `report.md` before sending, because it can contain their prompts and part names, and that a GitHub issue is public. Never send, upload, attach or e-mail the file yourself, and never open the issue page for them.
- **delete**: ask for a clear yes first, then tell the user to run `python scripts/diagnostics.py . delete` themselves, or run it on their yes.
