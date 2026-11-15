---
name: pcb-auto
description: One prompt to a board - runs the whole pipeline in express mode, driven by the stage graph, stopping only where a person must decide
argument-hint: "<what the board should do, in one or two sentences>"
disable-model-invocation: true
---

Take the idea below from nothing to release files in the current folder using the boardwright skill, with as few stops as the rules allow.

Set-up
1. If `scripts/plan.py` is missing, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py" . --update-scripts`. Run `python scripts/doctor.py .`; stop on any FAIL.
2. Write `PROJECT.md` with mode `express`, entry point `from an idea`, and the idea. Fill every must-have you can from the idea; give every other one a conservative default marked `ASSUMPTION - confirm`.
3. Ask the user ONE batch of questions, only for what cannot be assumed safely: input power, output voltages and currents, connectors, board size limit, assembly (hand or machine), country and suppliers. Offer your default for each so the user can answer "defaults".

The loop
Repeat until `python scripts/plan.py .` shows nothing ready:
1. Run `python scripts/plan.py .` and read READY NOW.
2. Start every helper and script node of one "can run together" group at the same time. Do the model nodes yourself, in order.
3. Mark non-gate nodes with `python scripts/plan.py . --done <node>` when their work is finished. Gate nodes complete only through their evidence.
4. FAILED GATES: go back to the node the planner names, fix the cause, rerun the same gate. After three failed attempts at the same gate, stop and show the report.
5. REOPENED nodes are redone before anything downstream.

You stop only for
- the batch of questions above, and the hazardous-voltage acknowledgement if the board has hazardous voltage;
- every node of kind `user` (board outline and connector positions, placement review, parts the user must check by hand, the release checklist);
- a gate that failed three times, a proposed waiver, or a schematic change after the placement review;
- a part swap.

You never stop for progress reports: one line per finished stage is enough. You never skip a gate, and you never mark an open gate as passed; an open gate is reported as NOT PASSED (open) and carried to the release checklist only if the user says to go on.

End with `reports/08-release.md` and one message: what was built, which gates passed, what is open, and the checklist the user must go through. Do not upload or order.

Idea: $ARGUMENTS
