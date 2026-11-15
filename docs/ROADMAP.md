# Roadmap and known gaps

What 0.1.0 has been through: one real board (mains flyback, 2 layers, 176 x 110 mm) from spec to release files on Windows 11 with KiCad 10.0.8. The scripts were tested on that board, including their failure paths. The manifests pass `claude plugin validate`.

## Not yet proven

1. **No fresh end-to-end run through the plugin.** The skill, commands and helper agents were written from the lessons of the first board. They have not yet driven a new board from `/boardwright:pcb-new` to `fab/`. Do this first, on a simple low-voltage board (for example a USB-powered sensor board), in both modes.
2. **macOS and Linux** are untested. Path detection and the running-KiCad check have code for them that has never run.
3. **KiCad 9** is untested; only 10.0.8 was used.
4. **`${CLAUDE_PLUGIN_ROOT}` in commands** is used to find the scripts on first run. If a Claude Code version does not expand it there, run `init_project.py` by its full path once.
5. ~~`kicad-buddy --check` connected detection~~ confirmed on 2026-11-14 in the first test session (KiCad open, `ipc_connected: true` detected).
6. **Evals.** There is no eval suite (`claude plugin eval`). Add cases: a low-voltage board, a mains board (must trigger the high-voltage rules), a wiped net-class file (rule guard must fail), a request to waive a DRC error (must refuse).

## Missing features

- **Stock checks beyond LCSC are done by the user by hand** from a list with links (`references/suppliers.md`). India is the first region described; the supplier list there is a starting point and has not been tested. An API-based lookup is not built.
- **The "existing schematic" and "review only" entry points** are written but have not been run on a real project.
- **High-speed and multilayer guidance** (`references/high-speed.md`) is written from general practice and has not been exercised. There is no impedance calculation or SI simulation; widths come from the fab's calculator.
- **Fab profiles.** Only conservative JLCPCB-compatible defaults; the real capability values are read from the fab page per project. PCBWay and OSH Park profiles are not written.
- **Board edits with KiCad closed.** All board edits need KiCad open with the API server. There is no headless path, by design, but it means the user must be at the machine.
- **Autorouting.** Low-risk nets were routed with a one-off maze router written during the first board; it is not part of the plugin. Freerouting integration is described in the first project's notes only.
- **Schematic drawing quality.** Schematics are edited through file tools, not live, and the user must reload. Layout of the drawing is functional, not pretty.
- **4+ layer boards, controlled impedance, length matching, RF.** The export handles inner layers, but no stage has been exercised on them.
- **Creepage around slots and edges** is not measured by `barrier_check.py` (2-D copper distance only).
- **Thermal simulation** is not done; stage 3 is a hand calculation from datasheet thermal resistance.
- **JLCPCB assembly formats.** The release now also writes the BOM and placement list with JLCPCB's column names. Rotation offsets are not applied, and the files have not been uploaded to JLCPCB to confirm they are accepted.
- **A KiCad-side package** (Plugin and Content Manager) that installs the API setting and points to this plugin. Planned as phase two.

## Publishing checklist (for the maintainer)

- [x] Split the plugin into a clean public repo; no local paths or scratch files (0.2.0).
- [x] Check the licences of KiCAD-Buddy (MIT) and mcp-server-kicad (GPL-3.0, not bundled) and credit them (`THIRD_PARTY.md`).
- [ ] Add screenshots or a short recording of a live run.
- [ ] Run item 1 above with testers and fix what it finds.
- [ ] Decide the name. Search for name conflicts with "boardwright" before publishing widely.
- [x] Every description says this is a community plugin, not affiliated with KiCad or Anthropic.

## Added after 0.1.0 (tested on the first board only)

- `sch_check.py`: schematic verification before layout. Its datasheet-file match and decoupling checks are heuristics; several checks never fired on the first board and were tested only with a synthetic netlist.
- `board_digest.py`, `status.py`, grouped error output in `run_gates.py`: compact answers in place of large tool listings. The unrouted pair list is an approximation; the count comes from KiCad.
- `references/efficiency.md`: token rules and what to verify before each expensive step. Whether this gets a board right in one pass is unproven until the first fresh run.
- Not built: a measured token comparison (same board with and without the scripts).

## Evidence from the first fresh run (usb-sensor-test, 2026-11-14)

A new session in an empty folder, guided mode, reached stage 5 (rules set, board still empty) in six commits.

Worked as designed:
- `/boardwright:pcb-doctor` and `/boardwright:pcb-new` found the plugin scripts and copied them into the project.
- The interview asked for assembly, country, currency and suppliers, and stopped for the user to confirm the spec.
- Stage 2 saved 11 datasheets, marked each fact "seen" or "helper", rejected look-alike parts, and reported its gate as NOT PASSED (open) on three items. The later stages carried that forward by the user's decision instead of hiding it.
- `sch_check.py` and the rule guard ran; net classes were stored as patterns with `expect_netclass_patterns`.

Problems found and fixed in the plugin:
- The release copy left out library folders such as `lib/` (only `*.pretty` at the root was copied). Fixed in `run_gates.py`.
- `sch_check.py` warned that family datasheets were missing (`STM32F042x4-x6.pdf` for STM32F042K6T6). It now also matches by prefix.
- At stage 4 the DRC row showed FAIL on an empty board. `run_gates.py --sch-only` now lists DRC as not run.
- Projects made with an older plugin copy kept old scripts. `init_project.py --update-scripts` replaces them.

Still open from that run:
- Stages 5 to 8 have not been run on it.
- The schematic is labelled blocks, not drawn wires; nobody has looked at it on screen.
- `datasheet_index.py` was written after that run. On its 11 datasheets it keeps 8.5% of the text, but finds nothing in four vendor datasheets with unusual headings and in two image-only drawings; those still need the PDF pages.

## KiCad add-on (kicad-addon/, replaces the kicad-panel prototype)

- Tested on Windows 11 and KiCad 10.0.8: install from file, the toolbar button, the first-run check, a real streamed reply with a tool call (2026-11-16), and Allow/Deny/Stop against a fake CLI.
- Not tested: macOS and Linux (the package declares Windows only), the window on other screen sizes, the Install helpers button on a machine without the helpers, and the official KiCad repository review.

## Stage graph, one-prompt run, retro (added 2026-11-15)

- `pipeline.json` + `plan.py`: 45 steps with dependencies, parallel groups, loops back from failed gates and reopening when a design file changes. Tested on the first board and on a copy of the sensor project. Not yet used by a live session to drive a board.
- `/boardwright:pcb-auto`: one prompt, express mode, stops only at user steps. Never run.
- `/boardwright:pcb-retro`: proposes pipeline improvements from a finished project's evidence. Never run. Applying a proposal to the plugin is a maintainer step, on purpose.
- `references/block-guides.md`: rules per circuit block from about 18 manufacturer documents. Only some of these rules are measured by a script; the rest are read and applied by the model.
- Next script checks worth building, from the research: decoupling capacitor distance per supply pin, TVS-to-connector distance and vias, crystal load-capacitance arithmetic, I2C pull-up range, track width against current, BOM versus placement designators, non-empty paste layers.
- Reviewer steps for stages 2, 5 and 6 are in the skill text but not in the graph (only the release reviewer is a node).

## Block checks (added 2026-11-15)

`block_check.py` measures decoupling distance, protection parts to connectors, crystal load capacitance, I2C pull-up range, track width against configured currents, BOM against placement designators, and paste layers. Tested on the first board and on a copy of the sensor project.

- It found a real release defect on the first board (BOM reference ranges), now fixed in the export.
- Limits: straight-line distances, nearest capacitor only, minimum segment width only (a short neck fails a wide net; zone-fed nets are not measured), I2C range depends on an assumed bus capacitance, paste check counts flashed pads only. The crystal check has never run on a real crystal circuit.
- Its default limits are engineering estimates and say so in the output.
