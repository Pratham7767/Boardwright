---
name: pcb-new
description: Start a new PCB project in this folder - setup check, short interview, then stage 1
argument-hint: "[guided|express] [one-line idea]"
disable-model-invocation: true
---

Start a new PCB project in the current folder using the boardwright skill.

1. If `scripts/run_gates.py` is missing here, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py" .` to create the project files and copy the gate scripts.
2. Run `python scripts/doctor.py .` and show the table. If anything is marked FAIL, explain the fix in one line each and stop until it is fixed.
3. Mode: use the first argument if it is `guided` or `express`. Otherwise ask the user which one they want, with one line describing each.
4. Entry point: if the folder already has a `.kicad_sch` with parts in it, ask whether to start from that schematic (see "Entry points" in the skill) or from a new idea. Record the answer in `PROJECT.md`.
5. Idea: use the rest of the arguments if given. In guided mode, interview the user as stage 1 describes. In express mode, ask only for missing must-haves.
6. Write the answers into `PROJECT.md`, classify the board (highest voltage, mains yes/no), and if hazardous voltage is present, do the "Tell the user first" step from the high-voltage reference before anything else.
7. Write `reports/01-spec.md` and stop for the user to confirm it.

Arguments: $ARGUMENTS
