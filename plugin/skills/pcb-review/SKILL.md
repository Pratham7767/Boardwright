---
name: pcb-review
description: Review-only pass on an existing KiCad board - runs the gates and writes a findings report, changes nothing in the design
disable-model-invocation: true
---

Review the existing KiCad project in the current folder using the boardwright skill, entry point "review-only". Do not change the schematic, the board, the rules or the project file.

1. If `scripts/run_gates.py` is missing, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py" .` (it only adds files; it never overwrites).
2. Read the schematic and board with the read-only tools. Write down what the board is: voltages, interfaces, layer count, whether it has hazardous voltage or fast signals.
3. Run `python scripts/run_gates.py . --no-export`. Report the rule guard, ERC and DRC rows and every error verbatim.
4. Parts: list every part whose symbol has no MPN or no datasheet in `datasheets/`. Do not guess what a part is.
5. If the board has hazardous voltage, go through the high-voltage reference rule by rule. If it has fast signals or four or more layers, go through the high-speed reference.
6. Propose the `barrier` and `emc` sections for `boardwright.json`, show them to the user, and run the two geometry scripts only after the user agrees to the file being written.
7. Write `reports/review.md`: what was checked, findings by severity with evidence, what could not be checked and why, and the limits from the skill. Start one `gate-reviewer` on the result if the board has hazardous voltage or fast signals.

End by listing the fixes you would make, in order, and wait.
