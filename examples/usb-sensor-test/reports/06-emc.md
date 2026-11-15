# Stage 6 - EMC and signal integrity

Date: 2026-11-15. Unattended run. **The stage 2 gate is still open.**
This is a risk estimate from geometry, not a compliance result. No target standard (spec R30). A lab measurement is the only proof.

## What can radiate or be upset on this board
- No switching regulator (U2 is linear), no crystal (U1 uses its internal 48 MHz oscillator; no crystal check applies).
- Fastest signals: USB full-speed (12 Mbit/s), I2C at 100 kHz (assumed), SWD during debugging only.
- Entry points for ESD: the USB-C connector, the two headers, the two buttons, the bare board itself (no enclosure).

## Measured (`emc_geometry.py`, final board, 16 rows: 15 ok, 0 CRITICAL, 0 HIGH, 0 MEDIUM, 1 LOW)
| ID | Item | Measured | Limit | Source of the limit | Result |
|---|---|---|---|---|---|
| E1 | U2 input loop C1-VIN-GND | 0 mm2 (parts in line), 6 mm around | 10 mm2 | estimate | ok |
| E2 | U2 output loop VOUT-C2-GND | 2.5 mm2 | 10 mm2 | estimate | ok |
| E3 | U1 pin 1-C3-pin 32 | 2.9 mm2 | 10 mm2 | estimate | ok |
| E4 | U1 pin 17-C4-pin 16 | 1.9 mm2 | 10 mm2 | estimate | ok |
| E5, E6 | U4 to connector, D- and D+ | 5.3 mm | 10 mm | plugin default; TI SLVA680 s2.1 says next to the connector | ok |
| E7 | U4 VBUS pin to connector VBUS pad | 5.8 mm | 10 mm | estimate | ok |
| E8 | U1 VDDA to C7 | 1.5 mm | 3 mm | estimate | ok |
| E9 | U3 supply to C9 | 3.0 mm | 5 mm | estimate | ok |
| E10 | F1 to connector VBUS pad | 3.8 mm | 10 mm | estimate | ok |
| E11, E12 | USB D+ / D- track, all branches | 16.0 / 17.2 mm | 40 mm | estimate | ok |
| E13 | NRST track, all branches | 41.6 mm; 6.9 mm from the USB pair | 30 mm; 1 mm | estimate | **LOW** (length) |
| E14 | NRST to I2C clock, same layer | 1.3 mm | 0.5 mm | estimate | ok |
| E15 | USB pair to SWD, same layer | 0.3 mm (at the U1 pins) | 0.2 mm | net-class clearance | ok |
| E16 | Closest track to the board edge | 0.45 mm (+3V3, right edge) | 0.3 mm | plugin fab default | ok |

## USB pair
- Target impedance: **none**. USB full-speed, classified "not fast" in stage 1. A 90 ohm pair cannot be made with 0.25 mm tracks on a 1.6 mm two-layer board, and at 12 Mbit/s over 11 mm it does not need to be.
- Length from connector pad to U1 pin: D+ 10.9 mm, D- 10.9 mm through pad B7 (both run the same route side by side, 1.9 mm apart at U4, 0.8 mm at U1). The second pad of each line adds a 2 to 4 mm branch.
- Vias: D+ none. D- two, on the branch from pad A7 only.
- Ground under the pair: unbroken on the back from U4 to U1. Next to the connector pads the back layer is cut by the VBUS link and the D- bridge (finding 2).

## Findings
| # | Severity | Item | Measured | Guide | Proposed fix |
|---|---|---|---|---|---|
| 1 | MEDIUM | Connector pad A7 (D-) reaches the ESD part through 2 vias and 2 mm on the back | 2 vias | TI SLVA680 s2.1-2.3: no via before the ESD part | Leave. The other D- pad (B7) and both D+ pads reach U4 on one layer. A fix needs a different ESD part or connector footprint (schematic and stage 2 change: the user's decision). |
| 2 | LOW | Back-layer ground is cut for 9.7 mm under the connector pad field by the VBUS link, plus the D- bridge | 0.4 mm wide gap, 2 mm from the pads | block guide 10: one continuous plane | Leave at full speed. For a later revision: bring the right VBUS pads round on the front, outside R2. |
| 3 | LOW | NRST is 41.6 mm long with branches to the button and to the SWD header | E13 | estimate 30 mm | Leave. C8 (100 nF) is 1.5 mm from the pin and the pin has an internal pull-up. If the board resets when touched, add a series resistor at the header (schematic change). |
| 4 | LOW | +3V3 runs 13 mm along the right edge, 0.45 mm from it, to feed the SWD header | E16 | fab minimum 0.3 mm | Leave; it is a supply line with capacitors at both ICs. |
| 5 | LOW | Ground pours are tied together only at the 18 component vias and the through-hole pads; no stitching vias along the edges | 18 vias on 12 cm2 | block guide 10: stitch large pours | Leave; add stitching in a later revision if a measurement asks for it. |
| 6 | LOW | No enclosure and four floating mounting holes: any ESD from handling goes into the board | - | - | The user's choice (spec R19). |
| 7 | LOW | USB-C shell is tied straight to ground | - | no reference on file (stage 4 assumption) | Leave; confirm against the USB-C documentation. |

No CRITICAL and no HIGH finding. No fix was applied in this stage, so the board is the one that passed the stage 5 gate.

## Passing checks
Regulator and decoupling loops, ESD part distance, fuse distance, edge clearance, USB length, USB to SWD spacing (rows above).

## Limits
- Loop areas are polygons through pad centres, not field calculations.
- The limits marked "estimate" are engineering estimates, not from a datasheet or standard.
- Nothing here predicts emissions or immunity. Only a measurement does.

## Gate
No CRITICAL finding (`emc_geometry.py`: Gate PASS). Stage 6: **PASS** (with the stage 2 gate still open).
