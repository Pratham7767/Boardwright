---
name: pcb-run
description: Continue the PCB pipeline from the stage this project is at
argument-hint: "[stage number to (re)run]"
disable-model-invocation: true
---

Continue the PCB project in the current folder using the boardwright skill.

1. Run `python scripts/status.py .` and read `PROJECT.md`. Say in two lines which stage the project is at and what is still open.
2. If a stage number was given, run that stage. Otherwise run the first stage that has no passing report.
3. Before a stage that edits the board, do the live-mode setup check.
4. Follow the mode in `PROJECT.md` for when to stop. Always stop when a gate fails, when a waiver is needed, or when a decision belongs to the user.

Arguments: $ARGUMENTS
