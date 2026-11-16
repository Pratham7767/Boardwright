# What works and what is next

## Works today (0.5.0)

- All eight stages, from idea to factory files, with a check at the end of each.
- Two real boards taken through the pipeline: a mains power supply and a USB sensor board.
- Tested on Windows 11 and Ubuntu 24.04 with KiCad 10.0.8.
- Safety checks for mains boards: safe distances, fuse and safety capacitors, discharge time, safety parts list.
- Interference checks: common layout mistakes, and a list of frequencies to test first.
- Fast-signal checks: matched lengths, layer changes, estimated impedance.
- Power check: capacitors near the chips.
- A chat button inside KiCad.
- One-command install on Windows and Linux.

## Not done yet

- **The safety distances are not checked against the official standards.** They come from published summaries, and the reports say so. To fix this, buy IEC 60664-1 and IS/IEC 62368-1, check each table, and record it with `python tools/mark_table_checked.py`.
- **No tester has designed a new board from scratch yet.** Each check has been tested, and a full review runs end to end through Claude.
- **Mac** is untested.
- **Simulation** is not built in. The board can be exported for professional tools such as HyperLynx and CST (`sim_export.py`), but running them is a person's job.
- **Stock checks** cover LCSC automatically. Other suppliers are checked by hand from a list of links.
- **3-D clearance** over part bodies, coated boards and inner-layer safety rules are not checked.
- **Boards with 4 or more layers** and controlled impedance have not been tried on a real design.

## Next

1. Testers design a first board from scratch and report what went wrong.
2. Check the safety tables against the purchased standards.
3. Optional simulation: a conducted-noise model of switching power supplies in ngspice, and a signal model of a USB pair with openEMS.
4. Import of near-field probe scans, to compare measured interference with what the checks predicted.
5. Profiles for more board factories than JLCPCB.

## Ideas welcome

Open an issue on GitHub with the **Tester feedback** form.
