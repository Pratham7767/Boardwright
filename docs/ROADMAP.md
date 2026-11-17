# What works and what is next

## Works today (0.6.0)

- All eight stages, from idea to factory files, with a check at the end of each.
- Two real boards taken through the pipeline: a mains power supply and a USB sensor board.
- Tested on Windows 11 and Ubuntu 24.04 with KiCad 10.0.8.
- Safety checks for mains boards: safe distances, fuse and safety capacitors, discharge time, safety parts list.
- Interference checks: common layout mistakes, and a list of frequencies to test first.
- Fast-signal checks: matched lengths, layer changes, estimated impedance.
- Power check: capacitors near the chips.
- A chat button inside KiCad.
- One-command install on Windows and Linux.
- Undo: a snapshot of the design files after every edit, a commit after each passed stage, and one editor at a time.
- One-call board edits with the DRC difference as the answer, placing a part next to a pin, and a simple router that refuses mains, hazardous and fast nets.
- An optional routing plan that only the designer can approve.
- Factory profiles for JLCPCB, PCBWay, OSH Park and Eurocircuits, each value with its page and date. A check that fails when the factory files are out of date.
- Part lifecycle check from LCSC's public product data.
- Cheaper models do the work and the strongest model checks stages 2, 4, 5, 6, 7 and 8.
- Support for other AI agents: an `AGENTS.md` file and a small read-only tool server (MCP).

## Not done yet

- **The safety distances are not checked against the official standards.** They come from published summaries, and the reports say so. To fix this, buy IEC 60664-1 and IS/IEC 62368-1, check each table, and record it with `python tools/mark_table_checked.py`.
- **No tester has designed a new board from scratch yet.** Each check has been tested, and a full review runs end to end through Claude.
- **Mac** is untested.
- **Simulation** is not built in. The board can be exported for professional tools such as HyperLynx and CST (`sim_export.py`), but running them is a person's job.
- **Stock and lifecycle checks** cover LCSC only. Other suppliers are checked by hand from a list of links. LCSC's status is the seller's, not the manufacturer's.
- **Factory profiles** are only as complete as the factories' pages. Many Eurocircuits limits are "unverified".
- **3-D clearance** over part bodies, coated boards and inner-layer safety rules are not checked.
- **Boards with 4 or more layers** and controlled impedance have not been tried on a real design.

## Next

0. Version 0.6 ([PLAN-0.6.md](PLAN-0.6.md)) is done. Its measured effect is in [benchmark.md](benchmark.md). Next for editing: measure bigger boards and more runs.
1. Testers design a first board from scratch and report what went wrong.
2. Check the safety tables against the purchased standards.
3. Optional simulation: a conducted-noise model of switching power supplies in ngspice, and a signal model of a USB pair with openEMS.
4. Import of near-field probe scans, to compare measured interference with what the checks predicted.
5. Stock checks for suppliers other than LCSC.

## Ideas welcome

Open an issue on GitHub with the **Tester feedback** form.
