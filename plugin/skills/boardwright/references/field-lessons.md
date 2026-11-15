# What goes wrong on real boards

A checklist built from designers' own post-mortems and fab-house guidance (sources at the end, read 2026-11-15). It is ordered by how often a mistake came up across the sources, which is a small sample. Go through the part for a stage before that stage's gate. An item marked **script** is already checked by a pipeline script; the rest you check yourself and record in the stage report.

## Stage 2: parts
1. **Footprint does not match the real part** (pad pitch, row spacing, body size). The most reported mistake. Compare pad pitch, row span and pad count with the land-pattern page of the datasheet for every non-passive part. Do not trust a downloaded or stock footprint by its name.
2. **Pad numbering differs from the symbol** although the outline looks right (a transistor with source and drain swapped, a 24-pad footprint under a 20-pin symbol). **script:** `sch_check.py` S3 flags symbol pins with no pad. You still compare pin functions with the datasheet table.
3. **Pinout read from the wrong view.** Record for every cited pinout whether the drawing is a top or a bottom view. Check pin 1 of every connector against the maker's drawing, especially through-hole and bottom-entry parts.
4. **Wrong variant of the right part** (momentary or latching switch, suffix with another pinout or voltage). Write the function needed next to each part and confirm the ordering code.
5. **Part not obtainable.** Do a quick stock and lifecycle look for every non-passive part now, not only at stage 7. A swap after layout costs the layout.
6. **Symmetric parts mounted turned** (tactile switches). Wire only diagonal pins so a 90 degree turn still works.

## Stage 3 and 4: power and schematic
7. **Power and ground swapped on a connector or regulator.** Compare each connector pin's net with the interface list from stage 1, pin by pin.
8. **Unfamiliar circuit never tried before.** Mark every block that is not taken from a reference design as "not previously proven" in the report, and suggest a test board or a bench test for it.
9. **No test points.** Every rail and every signal needed for bring-up gets a pad a probe can reach.
10. **ERC checked on one sheet only.** Read the ERC result for every sheet.

## Stage 5: layout
11. **Decoupling capacitors far from the pin, or reached through vias.** Measure the distance from each IC power pin to its capacitor on the same layer.
12. **DRC warnings dismissed or rules loosened until it passes.** Never. Rule 2 of the skill.
13. **Board not updated from the schematic.** **script:** the DRC gate runs with schematic parity.
14. **Track too narrow for its current**, including thin necks and single vias in a power path. Take the current from the power budget and check the narrowest point of each power net (`board_digest.py --section net NAME` prints minimum width).
15. **Ground plane missing, broken or split under signals.** Check pour islands and tracks that cross a gap.
16. **Silkscreen on pads.** **script:** DRC reports it as a warning; fix it, because fabs reject or clip it.
17. **Board outline not one closed loop; plated and unplated holes mixed up.** Check Edge.Cuts and each mounting hole's type.
18. **Parts too close to each other or to the edge** for assembly; vias the fab cannot build. Compare with the fab page read at this stage.
19. **Polarity and pin-1 marks missing** on the silkscreen.
20. **Layout never checked at real size.** Export the front fabrication layer 1:1 and ask the user to print it and lay the real connectors and large parts on it. This is cheap and catches what no script does.
21. **Autorouter used without review.** Only on request, and every autorouted net is reviewed.

## Stage 6: EMC
22. **Switching-regulator loops and feedback routing.** Follow the layout section of the regulator's datasheet; measure the input-capacitor loop and the distance from the feedback trace to the switch node.
23. **Impedance and matching ignored** for antennas and fast pairs. See `high-speed.md`.
24. **Isolation barrier crossed.** **script:** `barrier_check.py`. Slots and board edges still need a hand check.

## Stage 8: release (assembly files are where fabs stop orders)
25. **Paste layers missing from the export.** JLCPCB calls this the most frequent cause of a halted assembly order. **script:** the Gerber export always includes both paste layers; check they are not empty when the board has SMD parts.
26. **Placement file origin differs from the Gerber origin**, or **rotations are wrong** for the assembler's convention. The plugin exports KiCad's rotations unchanged; say in the release checklist that the user must check the assembler's placement preview before confirming.
27. **Designators differ between BOM and placement file**, or are written as ranges. Compare the two sets.
28. **Wrong project or stale files uploaded.** **script:** `run_gates.py` regenerates `fab/` and lists anything it did not write.
29. **No fiducials** on a machine-assembled board. Add them if the user chose machine assembly; take the size and count from the assembler's page.

## What experienced designers do to need fewer iterations
- Start from the fab's rules, so DRC means "this can be built".
- Start every block from the maker's reference design and record deviations.
- Check every footprint against the datasheet before layout.
- Check availability early and again before release.
- Place first, review the placement, then route. Decoupling and regulator parts are placed before anything else in their block.
- Use a written pre-order checklist and a second reviewer (here: `gate-reviewer` and the user).
- Print 1:1 and fit real parts.
- Prefer parts the assembler stocks when the board is machine assembled.

## Sources
Designer post-mortems and guides: DigiKey forum "Common PCB design mistakes beginners make"; AISLER community "Before it hurts: three practical lessons"; Predictable Designs "Top 5 mistakes on PCB layout"; RS DesignSpark "First PCB project, back to the drawing board"; circuit.rocks forum "First PCB design with KiCad"; Hackaday "Fail of the week: how not to use pushbuttons"; Hackaday.io Chessmate reproduction log; Michael VL KiCad best-practices wiki; Flux "5 PCB design mistakes"; Altium "8 common DFM problems" and "PCB layout review checklist"; PCBWay "Common mistakes to avoid when ordering PCBs".
Fab pages: JLCPCB capabilities, "Common PCB design issues", "Files needed for PCB assembly", "Fiducial marks"; OSH Park KiCad design rules; Hack Club "Fixing DRC errors".
Not readable when this was written: Reddit r/PrintedCircuitBoard, EEVblog, Analog Devices AN-139. Mains-creepage and buck-layout items rest on search snippets only. Fab numbers are deliberately not copied here: read the fab's page at stage 5 and record the values with the date.
