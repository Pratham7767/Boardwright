# Retro - usb-sensor-test, live run of 2026-11-15 (stages 5 to 7)

Evidence: `status.py`, `plan.py --all`, git log (9 commits; stage 2 and stage 5 two each), stage reports, `gates.json`, `emc-geometry.json`. The unattended run stopped at the stage 7 gate; the user then chose to release with it open, and stage 8 ran.

## Rework
- **Stage 5 gate run three times** (2, then 5, then 0 errors, all "thermal relief incomplete"). Cause 1: pours created through the API had 0 mm thermal gap and spoke. Cause 2: crowded ground pads with one spoke. Could have been caught before the gate: the dry run on a scratch copy did not show it, because zones made by `pcbnew` and zones made over the API got different defaults. Evidence: `05-layout.md` "Gate results". Once.
- **Stage 7 lookups done twice.** Three helpers shared one browser tab; two returned "could not check" for 29 of 31 lines. Evidence: `07-bom.md` "Machine assembly". Once.
- **USB entry re-planned** when the connector's edge position was read from the datasheet after the fan-out was designed (1 mm shift). Once.

## Late findings
- Stock: U1 fell from 16 to 3 and R3 from 8,400 to 0 between stage 2 (2026-11-14) and stage 7. The planner still lists `parts.stock_quick` as never run. Owner: stage 2.
- The "placement" found at the start was KiCad's default grid with no outline; `layout.outline` is a stage 5 user step that had never happened although stage 5 was "started".
- 14 "footprint does not match library" warnings appeared only after live placement (stage 5), cause not found.

## Wasted steps
- The first three helpers' 250 k tokens for 9 usable lines.
- `emc.config` ran twice: once to feed `layout.place_measure`, once at stage 6.

## Checks that never fired / were missing
- Never fired here: barrier check, crystal row, B3 (no crystal), fast-signal steps.
- Missing: a check that pours have non-zero thermal settings; a courtyard pre-check on the planned placement; a check that hidden reference designators leave connectors unlabeled; fiducials for machine assembly; via size against the fab page; stock re-check when a stage report is older than a day.

## Proposals (evidence: this project, each seen once unless noted)
1. `init_project.py --update-scripts` copies `pipeline.json` too. Without it `plan.py` cannot start.
2. Planner: do not infer `user` steps (outline, placement review) as done from later evidence; require `--done` with a note, and let `--done` record a note on an inferred step.
3. Planner: `layout.place_measure` writes the evidence files of `emc.measure` and `layout.blocks`, which marks later steps done. Give the placement measurement its own output file.
4. kicad-live: a zone tool (copper pour and rule area, with thermal gap and spoke set), and a tool to move or hide reference text. Both were done through the IPC library directly.
5. Skill: tell parallel helpers to open their own browser tab, or run browser helpers one at a time; say which browser to use when Chrome is not connected.
6. kicad-live: find `kicad-cli` from the KiCad install (as `doctor.py` and `run_gates.py` already do) instead of needing `KICAD_CLI`.
7. Lessons file: "USB-C 16-pin receptacle: the two D- pads straddle a D+ pad; plan one via pair or a different ESD footprint before placing."
8. `status.py`: "next stage" must not move past a stage whose gate says NOT PASSED; list the `block` section.
9. Scripts: accept net names without the leading slash, or document `MSYS_NO_PATHCONV=1`; Git Bash turns `/USB_DM` into a path.
10. `fab-jlcpcb.md`: state the via and annular-ring figures with a date, since the capability page did not summarise reliably.

## Plugin problems met in this run
| # | Where | Command or call | What happened |
|---|---|---|---|
| 1 | init | `python "<plugin>\scripts\init_project.py" . --update-scripts` then `python scripts/plan.py .` | `setup problem: cannot read <project>\scripts\pipeline.json: [Errno 2] No such file or directory`. Only `*.py` are copied. Worked around by copying the file by hand. The script also prints "Next step: ... run /boardwright:pcb-new" on an update. |
| 2 | planner | `python scripts/plan.py . --done layout.outline --note "..."` (same for floorplan, place, place_measure, place_review, route_rest, pours, proof_rules, emc.review) | `layout.outline is already done (inferred from a later step done by evidence); nothing recorded.` User steps were skipped without a record; the notes asked for by the task could not be stored. |
| 3 | planner | `python scripts/plan.py .` | Header says `stage 2 parts` throughout; `emc.review` was READY before any copper existed; `parts.stock_quick` and `parts.check` stay READY for ever while stage 2 is open. |
| 4 | skill | `layout.place_measure` = `emc_geometry.py` | Needs the `emc` section that the planner asks for only at stage 6 (`SETUP ERROR: no 'emc' section`), and `edge_clearance` dies with no tracks. |
| 5 | kicad-live | `kicad_status`, `sch_bom` | `"kicad_cli":{"found":false}`; `sch_bom` failed: `kicad-cli exited 127 ... kicad-cli not found. Install KiCad 9+ or set the KICAD_CLI environment variable`. `doctor.py` found it at `<kicad>\bin\kicad-cli.exe`. BOM exported with kicad-cli directly. |
| 6 | kicad-live | `pcb_paste_kicad_text` with a `(zone ...)` block, bare and inside `(kicad_pcb ...)` | `{"ok":true,"message":"Created 0 item(s) from pasted text."}`. No error, nothing created. No other zone tool exists. |
| 7 | kicad-live / IPC | zones created with `kipy` | saved as `(thermal_gap 0) (thermal_bridge_width 0)`: 2 DRC errors until set by hand. |
| 8 | kicad-live | `pcb_place_footprints` (33 parts) | afterwards DRC shows `lib_footprint_mismatch x14` that were not there before; pads proven unchanged. |
| 9 | kicad-live | no tool | reference text cannot be moved or hidden; `pcb-mechanic`'s "silkscreen cleanup" has no tool to do it with. |
| 10 | scripts | `board_digest.py . --section net /USB_DM` in Git Bash | `ERROR: no net named 'C:/Program Files/Git/USB_DM' (41 nets)`. |
| 11 | scripts | `board_digest.py --help` | prints `ERROR: usage: ...` instead of help. |
| 12 | KiCad Python | own script calling `BOX2I.Merge` on footprint graphics | assert dialog `Overflow converting value 22518277318836388.000000 to int` hung the process for 120 s. Not a plugin script, but `board_digest.py`-style code can hit it; run KiCad Python with a timeout. |
| 13 | helpers | three `part-scout` in parallel | all used the built-in browser's single tab ("Claude in Chrome was not connected"); pages changed under each other; one navigation "denied". The agent brief names no browser and no tab rule. |
| 14 | skill | `fab-jlcpcb.md` "open the fab's capability page" | no fetch tool is named; the page read through a summary tool gave contradictory via figures. |
| 15 | status | `python scripts/status.py .` | `next stage: 08` while 07 says NOT PASSED; `boardwright.json sections:` omits `block`. |
| 16 | release | `run_gates.py` on a scratch copy | worked (all rows pass). `-jlc-cpl.csv` has page coordinates with negative Y (`C1,103.35,-128.637`); the skill does not say whether JLCPCB needs the Gerber origin to match. |
| 17 | skill | "Three failures at one gate: stop" | unclear whether pre-checks with the same `kicad-cli pcb drc` count as gate runs; I ran two pre-checks between gate runs 2 and 3 and say so in `05-layout.md`. |
| 18 | helper | `gate-reviewer` at stage 8 (brief: read-only) | It ran `run_gates.py . --no-export`, which overwrites `reports/gates.md`, `gates.json`, `erc.json`, `drc.json`, then restored them from its own backup. The agent file tells it to run that command and to be read-only; the two conflict. Its first verdict was "gate must not count yet" (3 MEDIUM, 8 LOW, all report gaps; fixed in `08-release.md`). |
| 19 | planner | after the release | `release.gates`, `release.files_check`, `release.reviewer` cannot be given a note (`already done (inferred ...)`); the header still says `stage 2 parts`. |
