# Lessons from real runs

Each of these cost hours on a real board. Check them before stage 5.

1. **DRC passed while the rules were not applied.** Net-class membership had been wiped from the project file, so every net fell back to the default class and the isolation rules matched nothing. Fix: classes as patterns; `expect_netclass_patterns` in `boardwright.json`; the rule guard in `run_gates.py` fails when a rule names a class with no members.
2. **A rule matched more than intended.** `memberOfFootprint('H*')` for mounting holes also matched heatsinks `HS1`. Use `H?` or exact references, and look at what a new rule matches.
3. **Track rules do not cover pads.** A 1.5 mm rule for high-voltage tracks did not flag a pad 0.5 mm from another net. Measure pad spacing separately.
4. **Through-hole courtyards count on both sides.** A part placed on the bottom under a through-hole part overlaps its courtyard.
5. **A part swap can reverse a pinout.** The same generic part number from another maker had cathode and reference swapped in the same package. Every substitute goes back through the datasheet check.
6. **Helper output looked right and was not.** Router output passed its own checks and still ran a 12 V track under a heatsink body. Review every delegated route against the mechanical parts, not only against DRC.
7. **Stale release files.** `fab/` still held Gerbers of an earlier design. The release step clears and regenerates; never hand over files you did not just export.
8. **Stitching vias collided with mounting hardware.** Check via positions against holes and heatsink pins before pushing a batch.
9. **Stock pages lie by omission.** A supplier listing can show a part with zero own stock and a marketplace offer. Record which stock number you read.
10. **The exported BOM used reference ranges.** KiCad wrote `R103-R105` in one cell, so three parts looked missing next to the placement file, which assemblers reject. The export now disables ranges, and `block_check.py` compares BOM and placement designators after every release export.
11. **Reports go stale silently.** A stage report written before the last schematic or board change still said PASS. `plan.py` reopens such steps; rerun the check and update the report before relying on it.
