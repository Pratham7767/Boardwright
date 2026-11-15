# Working live in KiCad

## Setup, once per session
1. Run `python scripts/doctor.py .` and fix anything marked FAIL.
2. Open the board in KiCad (PCB Editor). The live link needs Preferences > Plugins > Enable KiCad API server, then a KiCad restart.
3. `kicad_status` must show the board document open. Make no board change until it does.

## Rules
- Every board change goes through the `kicad-live` tools. Never write a `.kicad_pcb` that KiCad has open.
- Small visible steps: one footprint, one group of tracks or one zone per call. Zoom to the area first.
- After each step, one short line in chat: what changed and why.
- After each batch: save with KiCad's save action, run DRC with schematic parity, show the counts.
- "Undo" means KiCad's undo action, so the user sees it revert.
- Schematic changes: say what will change, edit with the schematic tools, ask the user to reload and to run Update PCB from Schematic, then run ERC.
- Commit at the end of each stage.

## Known traps
- **Two editors open.** With the Schematic Editor and PCB Editor both open, board edits fail with "BeginCommit without a document specified". Ask the user to close the Schematic Editor.
- **A KiCad process that never exited** keeps rewriting the `.kicad_pro` and can wipe net-class settings. Before restoring a project file, make sure no KiCad process is running.
- **Update PCB from Schematic** can clear per-net class assignments. Use patterns, and check the count after every update (the rule guard does this).
- **Update Footprints from Library** puts library graphics back; redo any silkscreen cleanup afterwards.
- **Zone fills go stale.** A fill made before a rule changed can violate the new rule without DRC showing it. Refill before every gate.
- **The user may move things.** If the board changed outside your edits, keep the user's version and re-read positions before the next step.
