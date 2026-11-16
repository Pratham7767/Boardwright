# Hazardous voltage and mains

Applies when any net is above 60 V DC or 30 V AC, or the board connects to mains. These rules hold in both modes and the user cannot switch them off. A user may make them stricter.

## Tell the user first
Before stage 2, say this in plain words and record the answer in `PROJECT.md`:
- A mistake on this board can cause electric shock or fire. The pipeline's checks reduce mistakes; they do not make the board safe.
- A qualified person must review the design before it is powered, and it must be tested (hipot, first power-up through an isolation transformer) by someone who knows how.
- In guided mode, also offer the safer alternative: a certified, enclosed power module, so that the user's own board carries only low voltage. Go on with the discrete design only if the user chooses it.

## Design rules
1. **Name the domains.** Every net belongs to one: mains (before the rectifier), primary high voltage, primary low voltage, secondary. Net classes follow the domains.
2. **Isolation distance.** `creepage_rules.py` derives creepage and clearance by the IEC 60664-1 method from the `safety` section (mains voltage, overvoltage category, pollution degree, material group from the laminate CTI, altitude, insulation type per barrier). It uses the tables in `scripts/spacing_tables.json`, which are marked "secondary source" until someone checks them against the purchased standard. The product standard (for example IEC 62368-1) may require more: put a stricter value in the barrier's `use_mm` and say where it comes from. The reference project used 6.4 mm for reinforced insulation at 250 Vrms, against a calculated 3.0 mm clearance and 5.0 mm creepage.
3. **Enforce it in DRC.** `python scripts/creepage_rules.py . --write` writes the clearance and creepage rules at the end of the `.kicad_dru` (they win over earlier rules). The stage 5 gate then proves they fire: KiCad's DRC and `barrier_check.py` must agree.
4. **Only rated parts cross the barrier:** a transformer with reinforced insulation, an optocoupler with the needed creepage, Y1 or Y2 capacitors. Cite the datasheet page for each rating.
5. **No copper pour** on the mains or primary side, and none within the isolation distance of it. No secondary track under a primary part.
6. **Mounting holes and heatsinks.** A metal screw or heatsink is a conductor. Keep the isolation distance to it, or tie it deliberately to one domain.
7. **Protection in order at the entry:** fuse first, then surge and inrush parts, then the filter. Fuse rating from a calculation, cited.
8. **Stored charge.** Bulk capacitors need a discharge path and a warning on the silkscreen.
9. **Route by hand:** mains, rectified bus, switch node, clamp, feedback. No autorouter, no helper choosing a path.

## The `safety` section of boardwright.json
Filled at stage 1 (step `spec.safety`), before any layout. The standard and the product class are the user's decisions: ask, never assume.

```json
"safety": {
  "standard": "IEC 62368-1:2023",
  "product_class": "II",
  "mains": {"vrms": 230, "max_vrms": 250, "hz": 50, "ovc": "II", "line": "/L_IN", "neutral": "/N_IN", "earth": null},
  "pollution_degree": 2, "altitude_m": 2000, "laminate_cti": null,
  "domains": [
    {"name": "Mains", "netclasses": ["Mains"], "kind": "mains", "vrms": 250},
    {"name": "Primary bus", "netclasses": ["Primary_HV"], "vdc": 375, "vpeak": 600, "mains_referenced": true},
    {"name": "Primary control", "netclasses": ["Primary"], "vdc": 20, "mains_referenced": true},
    {"name": "Secondary", "rest": true, "vdc": 12}
  ],
  "supplies": [{"name": "12 V output", "max_w": 12, "source": "01-spec.md"}],
  "barriers": [{"name": "primary-secondary", "between": ["Mains", "Primary bus", "Primary control"],
                "and": ["Secondary"], "insulation": "reinforced", "working_vrms": 250, "peak_v": 600,
                "use_mm": 6.4}]
}
```
- `mains_referenced: true` makes a domain ES3 whatever its voltage: a flyback controller's 15 V supply is mains.
- `laminate_cti: null` means unknown, which counts as material group IIIb (the worst case). Give the CTI only from the laminate's datasheet.
- On a low-voltage board, give only `supplies`, to record the PS class.

## Scripts, in pipeline order
| Stage | Script | Checks |
|---|---|---|
| 4 | `mains_check.py` | fuse first on the line input; X class across mains; Y class across each barrier (Y1 for reinforced); varistor after the fuse; X-capacitor discharge time through the bleeder; touch-current estimate; earth on class I |
| 5 | `safety_class.py` | every net in a domain; ES/PS classes; a barrier for every domain above ES1; a standard named |
| 5 | `creepage_rules.py --write`, then `run_gates.py`, `barrier_check.py`, `creepage_rules.py` | required distances per barrier; rules present; KiCad >= 10.0.6; KiCad's DRC and the independent 2-D check agree |

Parts get their role from a symbol field `safety_class` (fuse, X1, X2, Y1, Y2, MOV, xcap_discharge), or from their reference (F, RV) and value text ("X2", "Y1"). A common-mode choke needs a `windings` field (for example `1-2,3-4`) for the discharge path to pass through it.

## Checks
- `barrier_check.py` measures the real copper distance across the barrier independently of DRC. It must pass, and you compare its number with the DRC rule.
- High-voltage pad-to-pad spacing inside the primary (for example across a drain-source capacitor) is not covered by a track rule. Measure it and list it in the report.
- The release checklist must include: insulation ratings to confirm, the hipot test, the fuse, the discharge time, conformal coating where spacing is tight, and the enclosure.

Values in this file are engineering defaults (unverified against any one standard). The standard that applies to the user's product takes priority.
