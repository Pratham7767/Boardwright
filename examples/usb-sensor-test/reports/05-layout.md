# Stage 5 - Layout

Date: 2026-11-15. Done in an unattended run; the user was offline.
**The stage 2 gate is still open** (boot pin polarity not on file, AHT20 footprint pad size, 10 uF capacitor datasheet). Carried forward by the user's decision of 2026-11-14.
**Decisions in this stage were taken by Claude and are NOT reviewed by the user:** board outline and connector positions, the whole placement, the placement review. See "Decisions" below.

## What was found at the start
The board file held the 33 parts in KiCad's default grid (as dropped by "Update PCB from Schematic"), no outline, no tracks. This stage therefore did the outline, the full placement, the routing and the pours.

## Board
| Item | Value |
|---|---|
| Size | 30.0 x 40.0 mm, rectangle, corners at (100,100) and (130,140) in KiCad page coordinates |
| Layers | 2, both with a ground pour |
| Parts | 33 footprints, all on the front (27 SMD fitted by the fab, 2 through-hole headers, 4 mounting holes) |
| Mounting holes | 4 x M3 (3.2 mm, not plated), centres 3.5 mm from each corner |
| Copper | 149 track segments, 351.8 mm; 29 vias (0.6 mm pad, 0.3 mm hole); 2 pours; 4 no-pour areas |

## Floorplan (written before placing)
Current flows bottom to top. Blocks and the loops that matter:
1. **USB entry, bottom edge centre:** J1, then U4 (ESD) 5.3 mm above its pads, CC resistors R1/R2 beside the pads, fuse F1 3.8 mm from the VBUS pad. Loop: connector pad to U4 pad to ground via.
2. **Regulator, bottom left:** F1 to U2, C1 at the input pin, C2 at the output pin. Loops: C1-VIN-GND and VOUT-C2-GND.
3. **Microcontroller, centre:** U1 turned so its USB pins face the connector. 3.3 V enters at pin 17 and runs under the chip to pins 5 and 1; one capacitor outside each supply pin (C4 at 17, C6+C7 at 5, C3 at 1), C5 (4.7 uF) on the feed. Loops: pin-capacitor-ground pin.
4. **Sensor, top right edge:** U3 with C9 and R8, 29 mm from the regulator and 16 mm from the microcontroller (spec R23: away from heat).
5. **Headers and buttons on the edges:** I2C header J3 top edge, SWD header J2 right edge, reset button left edge, boot button right edge, LEDs left.

## Placement (centre x, y in mm; rotation)
| Ref | Position | Ref | Position | Ref | Position |
|---|---|---|---|---|---|
| J1 | 115.0, 137.34, 0 | U1 | 114.2, 118.5, 270 | U2 | 106.0, 127.5, 90 |
| U3 | 121.0, 102.5, 0 | U4 | 115.0, 126.9, 270 | F1 | 108.6, 131.05, 180 |
| J2 | 127.8, 130.76, 180 | J3 | 116.62, 102.0, 270 | SW1 | 103.8, 111.5, 270 |
| SW2 | 126.2, 112.0, 270 | C1 | 103.35, 128.64, 180 | C2 | 103.35, 126.36, 180 |
| C3 | 117.48, 112.4, 0 | C4 | 111.4, 124.9, 270 | C5 | 109.3, 125.9, 180 |
| C6 | 112.75, 112.3, 90 | C7 | 113.8, 112.3, 90 | C8 | 114.85, 112.3, 90 |
| C9 | 119.6, 105.3, 0 | D1 | 102.99, 122.4, 270 | D2 | 105.5, 116.5, 0 |
| R1 | 111.7, 130.1, 180 | R2 | 118.3, 130.1, 0 | R3 | 122.8, 113.2, 90 |
| R4 | 119.09, 108.75, 0 | R5 | 119.85, 111.0, 0 | R6 | 103.5, 124.5, 180 |
| R7 | 108.05, 116.5, 180 | R8 | 118.83, 107.2, 90 | H1-H4 | 103.5/126.5, 103.5/136.5 |

**USB-C connector and the board edge.** TYPE-C-31-M-12.pdf p1 ("Recommend P.C.B layout") dimensions the PCB edge 5.79 mm from the centre line of the front shell slots. The footprint has those slots 3.13 mm behind its origin, so the edge is 2.66 mm in front of the origin and J1 sits at y = 140 - 2.66 = 137.34. The connector body overhangs the edge by about 1 mm. This is my reading of one dimension chain on a drawing: **check it on the 1:1 print** (`reports/05-front-fab-1to1.pdf`).

## Measured on the placement, before routing (`emc_geometry.py`, `block_check.py`)
| Item | Before (as found) | Now | Limit used |
|---|---|---|---|
| U2 input pin to C1 | 26.0 mm | 1.2 mm | 5 mm (plugin default, engineering estimate) |
| U2 output loop VOUT-C2-GND | - | 2.5 mm2 | 10 mm2 (estimate) |
| U1 supply pin to nearest capacitor | 6.6 mm | 1.5 mm (C7 at pin 5); C3 at pin 1 and C4 at pin 17 both 1.7 to 1.9 mm | 5 mm (default) |
| U1 loops pin 1-C3-pin 32 / pin 17-C4-pin 16 | - | 2.9 / 1.9 mm2 | 10 mm2 (estimate) |
| U3 supply pin to C9 | 4.4 mm | 3.0 mm | 5 mm (default) |
| U4 to connector, D+ and D- | 14.9 to 17.1 mm | 5.3 mm | 10 mm (default; TI SLVA680 says "next to the connector") |
| U4 VBUS pin to connector VBUS pad | 15.7 mm | 5.8 mm | 10 mm (default) |
| I2C pull-ups 4.7 k | above the 400 kHz maximum | inside 967 to 11802 ohm for standard mode | TI SLVA689, 100 pF assumed |

`block_check.py` on the final board: 17 rows, 0 errors, 0 warnings.

## Rules (set in the earlier part of this stage, unchanged)
| Rule | Value |
|---|---|
| Net classes (5 patterns) | Default 0.2 mm track / 0.2 mm clearance; Power (`/VBUS*`, `/+3V3`, `/3V3_SENS`, `/GND`) 0.4 mm track; USB (`/USB_D*`) 0.25 mm track |
| Custom rules (`.kicad_dru`) | copper 1.5 mm clear of the mounting holes; Power tracks never below 0.3 mm; USB tracks never below 0.2 mm |
| Board minimums | track 0.15 mm, clearance 0.15 mm, via 0.6 mm pad / 0.3 mm hole, annular ring 0.15 mm, copper to edge 0.3 mm |
| Pours | clearance 0.25 mm, minimum width 0.2 mm, thermal relief gap 0.5 mm and spoke 0.5 mm |

**Fab page.** https://jlcpcb.com/capabilities/pcb-capabilities was read on 2026-11-15 through a page-summary tool (cached copy of 2026-11-14), not line by line. It returned: track/spacing 0.10/0.10 mm, via-hole spacing 0.2 mm, via hole to track 0.2 mm, plated hole to track 0.28 mm (0.35 recommended), copper to routed edge 0.2 mm or more, non-plated hole 0.5 mm or more, silkscreen line 0.15 mm and text 1.0 mm. Its via and annular-ring figures contradicted each other, so they are **unverified**. The board uses the plugin's conservative defaults and is inside every figure above, but **the 0.6 / 0.3 mm via (0.15 mm annular ring) must be confirmed by the user on JLCPCB's page before ordering.** The net class asks for 0.7 mm vias; 0.6 mm was used because several vias sit between USB-C pads tracks with 0.22 to 0.28 mm to spare.

## Routing (all by hand, coordinates chosen by Claude; no autorouter)
| Group | Layer and width | Notes |
|---|---|---|
| VBUS | front 0.4 mm; back 0.4 mm link | Left VBUS pads go straight to F1. Right VBUS pads cross to the left on the back (2 vias); a third via feeds U4 pin 5. |
| VBUS_F | front 0.4 mm, 0.3 mm under U2 | F1 to U2 EN and VIN, then C1. |
| +3V3 | front 0.4 mm (0.3 mm C6-C7 link); one back link | U2 to C2, C5, C4, pin 17, under U1 to pins 5 and 1, C3, then up to the pull-ups, R8 and J3. From the J3 pad on the back to the boot button, then along the right edge to J2. |
| 3V3_SENS | front 0.4 mm | R8 to C9 to U3, 5.2 mm. |
| USB D+ / D- | front 0.25 mm | Each connector pad runs to a U4 pad and on to U1 (D+ 16.0 mm, D- 17.2 mm of track in total, both pad pairs included). Three of the four pads reach U4 with no via. **Pad A7 (D-) reaches U4 through two vias and 2 mm on the back**, because the two D- pads sit either side of a D+ pad and cannot be joined on one layer. TI SLVA680 asks for no via before the ESD part; full-speed USB tolerates it, an ESD strike on that one pad sees slightly more inductance. |
| CC1 / CC2 | front 0.2 mm | 4.0 and 3.8 mm to R1 / R2. |
| I2C | front 0.2 mm; back to J3 | SCL changes layer once between U1 and the sensor (it has to cross SDA). J3 is reached on the back. SCL 34.2 mm, SDA 29.4 mm including the header branches. |
| NRST | front; back to J2 pin 4 | 41.6 mm in total. A long reset line; C8 (100 nF) is 1.5 mm from the pin. |
| BOOT0 | front; back under the I2C lines | 13.9 mm, 2 vias. |
| SWD, LEDs | front 0.2 mm | no vias. |
| GND | pours on both layers | 18 stitching vias at capacitor, IC and resistor ground pads. No back-layer track runs under U1 or under the USB pair between U4 and U1. |

Four small no-pour areas (front, one also back): at the USB-C pad field (so the pour does not creep between 0.3 mm pads), and at three crowded ground pads (J3 pin 4, J2 pin 5, the C6-C8 ground pads) where the pour could reach the pad with one thermal spoke only. Those pads are connected by a track and a via instead.

## Gate results (`python scripts/run_gates.py . --no-export`, final board)
| Gate | Result |
|---|---|
| Rule guard | pass: 2 classes used by rules; 3 classes, 5 patterns |
| ERC | pass: 0 errors, 0 warnings |
| DRC with schematic parity | **pass: 0 errors, 17 warnings, 0 unconnected, 0 parity** |

The DRC gate was run three times after the pours: 2 errors, then 5 errors, then 0. All errors were "thermal relief incomplete". Cause of the first: the pours were created with 0 mm thermal gap and spoke; cause of the second: with 0.5 mm set, three more crowded pads had one spoke. Fixed as described above, not waived. Between gate runs 2 and 3 the same DRC command was run twice by hand as a pre-check (1 error, then 0).

### Remaining warnings (17)
| Count | Warning | Why it is left |
|---|---|---|
| 14 | Footprint does not match its library copy (U1, U2, U4, SW1, SW2, J2, F1, C1, C2, C5, R1, R6, R7, D1) | Appeared after the parts were turned and their reference text hidden. Pad numbers, pad positions inside the footprint, drill sizes and nets of all 33 footprints were compared with the board of commit 3839a4f: no difference. The difference is in text, not copper. Do **not** run "Update Footprints from Library" without redoing the silkscreen clean-up. |
| 2 | J1 silkscreen clipped by the board edge | The connector overhangs the edge by design. |
| 1 | U2 pin-1 mark over C1 pad 1 | The mark is clipped at the pad. Cosmetic. |

Silkscreen: 21 reference designators were hidden because they lay on pads or on each other (C2, C6-C9, D1, D2, H1, H2, H4, J2, J3, R4-R8, SW2, U2, U3, U4). The board therefore has **no printed names for the headers and no pin labels**. Use the assembly drawing. Adding labels is an open item.

## Proof that the rules fire (scratch copy, never the project)
| Deliberate fault | Result |
|---|---|
| 0.2 mm track on /+3V3 | error `track_width`, rule `power_min_width` (min 0.3 mm, actual 0.2 mm) |
| via 2.5 mm from the centre of H1 | 4 x error `hole_clearance`, rule `mounting_hole_keepout` |
| class pattern `/USB_D*` removed from the project file | Rule guard FAIL: "'USB' has no patterns or assignments (rule never fires); expected 5 netclass patterns, found 4" |

## Checklist from "what goes wrong on real boards", stage 5
| # | Item | Result |
|---|---|---|
| 11 | Decoupling far from the pin or through vias | measured above; no via between any supply pin and its capacitor |
| 13 | Board not updated from schematic | parity 0 |
| 14 | Track too narrow for its current | narrowest Power track 0.3 mm against 0.017 mm needed for 56 mA (TI AN-1229 rule in `block_check.py`); single vias in VBUS carry 56 mA |
| 15 | Ground plane broken under signals | whole under U1 and under the USB pair from U4 to U1; cut by the VBUS link and the D- bridge on the back in the 2 mm next to the connector pads, and by the I2C, NRST, BOOT0 and +3V3 back-layer links in the top right quarter |
| 16 | Silkscreen on pads | fixed except 1 (above) |
| 17 | Outline closed, hole types | one rectangle; the 4 mounting holes are non-plated |
| 18 | Parts too close to the edge | closest pad to the edge: SW1 and J3, 1.1 mm; closest track 0.5 mm (+3V3 on the right edge) |
| 19 | Polarity and pin-1 marks | footprint marks are present; D2's terminals are numbered opposite to KiCad's (stage 4 open item 3) |
| 20 | Checked at real size | **not done**: `reports/05-front-fab-1to1.pdf` is exported for the user to print |
| 29 | Fiducials | **none on the board**. Open: read JLCPCB's page on fiducials for assembly and add them if required. |

## Decisions taken by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user
1. Board outline 30 x 40 mm; M3 holes 3.5 mm from the corners; USB-C centred on the bottom edge, overhanging about 1 mm; I2C header on the top edge; SWD header on the right edge; buttons on the left (reset) and right (boot) edges; sensor in the top right corner.
2. The placement as a whole, and its review.
3. I2C at 100 kHz (standard mode) recorded as an ASSUMPTION; 4.7 k pull-ups kept (the user's instruction for this run).
4. 0.6 mm vias instead of the class's 0.7 mm.
5. One D- pad reaches the ESD part through vias.
6. 21 reference designators hidden.

## Open items
1. Stage 2 gate (3 items).
2. Print the 1:1 drawing; lay the USB-C connector, the buttons and the headers on it; check the connector's position on the edge.
3. Confirm the via size against JLCPCB's capability page.
4. Fiducials; silkscreen labels for headers and buttons.
5. Mounting holes have no ground connection (spec left this to stage 5: decided "not connected", non-plated).

## Gate
Rule guard pass, DRC with schematic parity 0 errors, 0 unconnected: **PASS** (with the stage 2 gate still open, and with every placement decision unreviewed by the user).
