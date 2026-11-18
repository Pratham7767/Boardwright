---
name: pcb-auto
description: One prompt to a board - runs the whole pipeline in express mode, driven by the stage graph, stopping only where a person must decide
argument-hint: "<what the board should do, in one or two sentences>"
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python scripts/run_gates.py . --no-export*), PowerShell(python scripts/run_gates.py . --no-export*), Bash(python scripts/run_gates.py . --sch-only*), PowerShell(python scripts/run_gates.py . --sch-only*), Bash(python scripts/sch_check.py .*), PowerShell(python scripts/sch_check.py .*), Bash(python scripts/status.py .*), PowerShell(python scripts/status.py .*), Bash(python scripts/plan.py .*), PowerShell(python scripts/plan.py .*), Bash(python scripts/safety_class.py .*), PowerShell(python scripts/safety_class.py .*), Bash(python scripts/mains_check.py .*), PowerShell(python scripts/mains_check.py .*), Bash(python scripts/creepage_rules.py .*), PowerShell(python scripts/creepage_rules.py .*), Bash(python scripts/emc_harmonics.py .*), PowerShell(python scripts/emc_harmonics.py .*), Bash(python scripts/impedance_check.py .*), PowerShell(python scripts/impedance_check.py .*), Bash(python scripts/pdn_check.py .*), PowerShell(python scripts/pdn_check.py .*), Bash(python scripts/parts_register.py .*), PowerShell(python scripts/parts_register.py .*), Bash(python scripts/doctor.py .*), PowerShell(python scripts/doctor.py .*), Bash(* -I scripts/barrier_check.py .*), Bash(python scripts/barrier_check.py .*), PowerShell(* -I scripts/barrier_check.py .*), PowerShell(python scripts/barrier_check.py .*), Bash(* -I scripts/emc_geometry.py .*), Bash(python scripts/emc_geometry.py .*), PowerShell(* -I scripts/emc_geometry.py .*), PowerShell(python scripts/emc_geometry.py .*), Bash(* -I scripts/hs_rules.py .*), Bash(python scripts/hs_rules.py .*), PowerShell(* -I scripts/hs_rules.py .*), PowerShell(python scripts/hs_rules.py .*), Bash(* -I scripts/board_digest.py .*), Bash(python scripts/board_digest.py .*), PowerShell(* -I scripts/board_digest.py .*), PowerShell(python scripts/board_digest.py .*), Bash(* -I scripts/block_check.py .*), Bash(python scripts/block_check.py .*), PowerShell(* -I scripts/block_check.py .*), PowerShell(python scripts/block_check.py .*), Bash(* -I scripts/emc_rules.py .*), Bash(python scripts/emc_rules.py .*), PowerShell(* -I scripts/emc_rules.py .*), PowerShell(python scripts/emc_rules.py .*), mcp__plugin_boardwright_kicad-schematic__get_net_connections, mcp__plugin_boardwright_kicad-schematic__get_pin_positions, mcp__plugin_boardwright_kicad-schematic__get_schematic_summary, mcp__plugin_boardwright_kicad-schematic__get_symbol_pins, mcp__plugin_boardwright_kicad-schematic__list_schematic_bus_entries, mcp__plugin_boardwright_kicad-schematic__list_schematic_components, mcp__plugin_boardwright_kicad-schematic__list_schematic_global_labels, mcp__plugin_boardwright_kicad-schematic__list_schematic_hierarchical_labels, mcp__plugin_boardwright_kicad-schematic__list_schematic_junctions, mcp__plugin_boardwright_kicad-schematic__list_schematic_labels, mcp__plugin_boardwright_kicad-schematic__list_schematic_no_connects, mcp__plugin_boardwright_kicad-schematic__list_schematic_sheets, mcp__plugin_boardwright_kicad-schematic__list_schematic_wires, mcp__plugin_boardwright_kicad-schematic__list_unconnected_pins, mcp__plugin_boardwright_kicad-live__kicad_status, mcp__plugin_boardwright_kicad-live__pcb_summary, mcp__plugin_boardwright_kicad-live__pcb_list_footprints, mcp__plugin_boardwright_kicad-live__pcb_list_nets, mcp__plugin_boardwright_kicad-live__pcb_list_tracks, mcp__plugin_boardwright_kicad-live__pcb_list_zones, mcp__plugin_boardwright_kicad-live__pcb_get_footprint, mcp__plugin_boardwright_kicad-live__pcb_net_report, mcp__plugin_boardwright_kicad-live__pcb_layers, mcp__plugin_boardwright_kicad-live__pcb_stackup, mcp__plugin_boardwright_kicad-live__pcb_get_selection, mcp__plugin_boardwright_kicad-live__sch_summary, mcp__plugin_boardwright_kicad-live__sch_list_symbols, mcp__plugin_boardwright_kicad-live__sch_get_symbol, mcp__plugin_boardwright_kicad-live__sch_netlist, mcp__plugin_boardwright_kicad-live__sch_bom, Write(reports/**), Edit(reports/**), mcp__plugin_boardwright_boardwright__status, mcp__plugin_boardwright_boardwright__check, mcp__plugin_boardwright_boardwright__find, mcp__plugin_boardwright_boardwright__history, mcp__plugin_boardwright_boardwright__digest
---

You are already in the project folder: do not `cd`. Read-only checks and KiCad queries run without asking; anything that changes the design asks the user.

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
