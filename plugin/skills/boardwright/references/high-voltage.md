# Hazardous voltage and mains

Applies when any net is above 60 V DC or 30 V AC, or the board connects to mains. These rules hold in both modes and the user cannot switch them off. A user may make them stricter.

## Tell the user first
Before stage 2, say this in plain words and record the answer in `PROJECT.md`:
- A mistake on this board can cause electric shock or fire. The pipeline's checks reduce mistakes; they do not make the board safe.
- A qualified person must review the design before it is powered, and it must be tested (hipot, first power-up through an isolation transformer) by someone who knows how.
- In guided mode, also offer the safer alternative: a certified, enclosed power module, so that the user's own board carries only low voltage. Go on with the discrete design only if the user chooses it.

## Design rules
1. **Name the domains.** Every net belongs to one: mains (before the rectifier), primary high voltage, primary low voltage, secondary. Net classes follow the domains.
2. **Isolation distance.** Derive creepage and clearance from the standard that applies to the product (for example IEC 62368-1) for the working voltage, pollution degree and material group, and cite the table. If no standard was chosen, use at least 6 mm between mains or primary copper and anything a person can touch, and say that it is a default, not a derived value. The reference project used 6.4 mm for reinforced insulation at 250 Vrms.
3. **Enforce it in DRC.** A custom rule in the `.kicad_dru` for clearance and creepage between the hazardous classes and everything else. Then prove it fires (stage 5).
4. **Only rated parts cross the barrier:** a transformer with reinforced insulation, an optocoupler with the needed creepage, Y1 or Y2 capacitors. Cite the datasheet page for each rating.
5. **No copper pour** on the mains or primary side, and none within the isolation distance of it. No secondary track under a primary part.
6. **Mounting holes and heatsinks.** A metal screw or heatsink is a conductor. Keep the isolation distance to it, or tie it deliberately to one domain.
7. **Protection in order at the entry:** fuse first, then surge and inrush parts, then the filter. Fuse rating from a calculation, cited.
8. **Stored charge.** Bulk capacitors need a discharge path and a warning on the silkscreen.
9. **Route by hand:** mains, rectified bus, switch node, clamp, feedback. No autorouter, no helper choosing a path.

## Checks
- `barrier_check.py` measures the real copper distance across the barrier independently of DRC. It must pass, and you compare its number with the DRC rule.
- High-voltage pad-to-pad spacing inside the primary (for example across a drain-source capacitor) is not covered by a track rule. Measure it and list it in the report.
- The release checklist must include: insulation ratings to confirm, the hipot test, the fuse, the discharge time, conformal coating where spacing is tight, and the enclosure.

Values in this file are engineering defaults (unverified against any one standard). The standard that applies to the user's product takes priority.
