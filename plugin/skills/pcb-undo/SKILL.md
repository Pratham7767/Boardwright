---
name: pcb-undo
description: Show the design history of the board in this folder, compare two steps, or take the design files back to an earlier step
model: haiku
disable-model-invocation: true
allowed-tools: Bash(python scripts/history.py . list*), Bash(python scripts/history.py . diff*), Bash(python3 scripts/history.py . list*), Bash(python3 scripts/history.py . diff*), PowerShell(python scripts/history.py . list*), PowerShell(python scripts/history.py . diff*)
---

You are already in the project folder: do not `cd`.

The plugin saves a step after every edit to a design file (board, schematics, project, rules, libraries, `boardwright.json`). This command shows those steps and, only when the user chooses one, goes back to it.

1. Run `python scripts/history.py . list 15` (`python3` on macOS and Linux). Show the steps as a short table: number, time, what changed.
2. If the user named a step or a time in their message (`$ARGUMENTS`), run `python scripts/history.py . diff <N>` and say in plain words which files differ from now. Otherwise ask which step they want, and stop.
3. Before restoring, say which files will change and that the current state is saved as a step first, so the restore can itself be undone. Ask for a clear yes.
4. On yes: `python scripts/history.py . restore <N>`. If it says KiCad has a file open, ask the user to close the board or schematic in KiCad (or to agree to reload it in KiCad afterwards, then add `--force`).
5. After a restore, run `python scripts/run_gates.py . --no-export` and say which gates changed. Then remind the user to reload the files in KiCad if they had them open.

Never restore without the user's yes in this conversation.
