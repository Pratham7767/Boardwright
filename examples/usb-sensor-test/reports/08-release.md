# Stage 8 - Release

**Two gates are open: stage 2 (parts: 3 items) and stage 7 (BOM: R3 out of stock, U1 3 of 5 at LCSC, JLCPCB parts library not checked). The user chose to release with both open** (stage 2 on 2026-11-14, as recorded in `03-power.md` and `04-schematic.md`; stage 7 on 2026-11-15, in chat: "Yes, release"). **Do not order from these files until the checklist below is worked through.**

Date: 2026-11-15. Nothing was uploaded, ordered or published.

## Decisions taken by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user
Review each one first. They were made while the user was offline.
- [ ] Board outline 30 x 40 mm; M3 holes 3.5 mm from the corners, non-plated, not connected.
- [ ] Connector positions: USB-C centred on the bottom edge, overhanging about 1 mm (my reading of TYPE-C-31-M-12.pdf p1); I2C header top edge; SWD header right edge; reset button left, boot button right; sensor top right.
- [ ] The whole placement and its review (`05-layout.md`). The placement on file before this run was the default grid KiCad drops parts into.
- [ ] Vias 0.6 mm pad / 0.3 mm hole instead of the 0.7 mm of the net class.
- [ ] One USB D- connector pad (A7) reaches the ESD part through two vias (`06-emc.md` finding 1).
- [ ] 21 reference designators hidden on the silkscreen; headers and buttons carry no labels.
- [ ] Hand checks at Robu / element14 India not done; `07-hand-check.md` is empty.
- [ ] I2C speed 100 kHz recorded as an assumption; 4.7 k pull-ups kept (the instruction for this run; spec R9 says "up to 400 kHz", where 4.7 k is above the 3.5 k maximum for a 100 pF bus).
- [ ] The release checklist itself (this file) has not been gone through by the user.

## Gate summary
| Stage | Gate | Numbers |
|---|---|---|
| 1 Spec | PASSED 2026-11-14 | 30 of 30 requirements have a value and a source |
| 2 Parts | **NOT PASSED (open)** | boot pin polarity not on file; AHT20 pad size unverified; 10 uF capacitor not in the catalogue on file |
| 3 Power | PASSED | 56.0 mA worst case of 80 mA budget; regulator junction 83 C at 60 C ambient |
| 4 Schematic | PASSED | ERC 0 errors, 0 warnings; `sch_check.py` 0 errors, 2 warnings |
| 5 Layout | PASS | rule guard pass; DRC 0 errors, 17 warnings, 0 unconnected, 0 parity; `block_check.py` 0 errors, 0 warnings |
| 6 EMC | PASS | 16 rows, 0 CRITICAL; findings 1 MEDIUM, 6 LOW |
| 7 BOM | **NOT PASSED (open)** | 19 lines read at LCSC: 17 ok, R3 out of stock, U1 3 of 5; JLCPCB library: 19 lines could not be checked |
| 8 Release | files written | below |

### Release run (`python scripts/run_gates.py .`, 2026-11-15, log in `reports/release-run.log`)
| Row | Result |
|---|---|
| Rule guard | pass: 2 classes used by rules; 3 classes, 5 patterns |
| ERC | pass: 0 errors, 0 warnings |
| DRC | pass: 0 errors, 17 warnings, 0 unconnected, 0 parity |
| DRC after zone refill (on a copy) | pass: 0 errors, 17 warnings, 0 unconnected, 0 parity |
| Gerbers / drill | "10 files" and "12 files in fab/gerbers" as printed by the script; the folder holds 12 files in all |
| `block_check.py` B6 | BOM 27 references, placement 27 references, they match |
| `block_check.py` B7 | front paste: 113 flashes for 113 SMD pads; back paste: 0 for 0 |

The 17 DRC warnings are explained in `05-layout.md`: 14 "footprint does not match library" (text only; pads compared and unchanged), 2 connector silkscreen over the edge, 1 pin-1 mark on a pad.

## Files in `fab/` (all written by this run; nothing else is in the folder)
| File | What |
|---|---|
| `usb-sensor-test-gerbers.zip` (62,890 bytes) | the contents of `fab/gerbers`: copper, mask, paste and silkscreen for front and back, outline, drill file, drill map, job file |
| `usb-sensor-test-pos.csv` | placement, 27 parts |
| `usb-sensor-test-bom.csv` | BOM with MPN and LCSC number |
| `usb-sensor-test-schematic.pdf` | schematic |
| `usb-sensor-test-jlc-bom.csv` | BOM with JLCPCB column names, 20 lines for 19 different parts (SW1 and SW2 are two lines with the same number C318884), none without an LCSC number |
| `usb-sensor-test-jlc-cpl.csv` | placement with JLCPCB column names, 27 parts |

Also for the user: `reports/05-front-fab-1to1.pdf` (print at 100 %).

## Checklist before ordering (tick each)
### Parts and stock
- [ ] R3 (10 k, C25744): out of stock at LCSC on 2026-11-15. Wait, or choose a substitute; a substitute goes back through stage 2. **The files still name C25744.**
- [ ] U1 (STM32F042K6T6, C69216): 3 in the own stock of LCSC, 5 needed. Decide: 3 boards, another offer, or another source.
- [ ] JLCPCB assembly library: stock and Basic/Extended type of all 19 parts, and the set-up fees. Not checked.
- [ ] J2, J3 pin headers: buy by hand (`07-hand-check.md`).
- [ ] Cost in INR: parts are about USD 5.57 per board without R3 at the price breaks read; no exchange rate, shipping, duty or tax included.

### Unverified items from stage 2 (gate open)
- [ ] Boot pin polarity: BOOT0 pulled low by R3, high by SW2 - from AN2606 read online, not on file.
- [ ] AHT20 footprint: land pattern drawn by Claude from the package drawing (AHT20.pdf p1): pads 0.9 x 0.45 mm, 1.0 mm pitch, columns 2.3 mm apart. Compare with a real part.
- [ ] 10 uF capacitor CL10A106KP8NNNC: part number not in the catalogue on file.
- [ ] Datasheet figures marked "helper" in `02-parts.md` and `03-power.md` were not re-opened.
- [ ] `sch_check.py` warnings: U1 and U2 datasheet files are matched by family name, not part name.
- [ ] U4 (USBLC6-2SC6) footprint: only the 0.95 mm pitch was compared with the datasheet; the other dimensions are unverified (`02-parts.md` item 4).
- [ ] U3 (AHT20) in humid use: accuracy is stated for non-condensing air only; long exposure above 80 %RH gives a temporary +3 %RH drift; the datasheet says nothing about conformal coating (`02-parts.md` item 3). The spec expects condensation.
- [ ] Footprints that differ from the maker's pattern: U1 pads 1.5 mm long against 1.2 mm; U2 land pattern read by a helper only; F1 pads slightly smaller than the maker's (`02-parts.md` footprint table).
- [ ] U2 electrical table (AP2112.pdf p8) was read by position from scrambled text; AN4879 (USB hardware guidelines) was never obtained.
- [ ] LED resistor power rating (62.5 mW) is from the LCSC listing; the series datasheet was not opened.

### Assumptions from stages 1, 3 and 4
- [ ] USB input 4.4 to 5.5 V; the USB standard is not on file.
- [ ] 20 mA allowance for a device on the spare I2C header.
- [ ] U1 analog supply current 0.3 mA (rounded-up typical).
- [ ] Thermal resistances are the test-board figures of the makers.
- [ ] USB-C: 5.1 k on each CC pin and the shell tied to ground - general practice, the USB-C standard is not on file.
- [ ] VDDA tied straight to +3V3, no filter (the ADC is unused).
- [ ] The schematic was built with tools and checked by netlist; look it over in KiCad.
- [ ] U1, U2 and U4 use base library symbols (`STM32F042K_4-6_Tx`, `AP2204K-1.5`, `USBLC6-2P6`) with the real part names in the Value and MPN fields (`04-schematic.md`, symbol notes). Confirm the pins against the datasheets.
- [ ] Green LED D1: forward voltage 2.6 to 3.4 V (XL-1608UGC-04.pdf p3, helper) on a 3.3 V rail through 1 k. It may be dim or dark. Not measured.
- [ ] Outdoor use: -20 to +60 C, condensation; conformal coating by the user after assembly, sensor opening and connectors left uncoated; no enclosure (spec R21, R22).

### Layout and fabrication
- [ ] Print `05-front-fab-1to1.pdf` at 100 % and lay the USB-C connector, buttons and headers on it. Check the connector against the board edge.
- [ ] Via 0.6 / 0.3 mm (0.15 mm ring) against the JLCPCB capability page. The page was read through a summary tool on 2026-11-15 and its via figures were contradictory.
- [ ] Fiducials: none on the board. Read the JLCPCB assembly page; add them if required.
- [ ] The USB-C connector overhangs the bottom edge by about 1 mm: ask whether that clashes with the edge rails or panel the assembler adds.
- [ ] Board options at order time: 2 layers, 1.6 mm, 1 oz; ENIG finish (spec R22).
- [ ] Placement preview at JLCPCB: rotations in the `-jlc-cpl.csv` are the ones KiCad has, unchanged, and its coordinates are KiCad page coordinates (Y negative). Check every polarised and multi-pin part: U1, U2, U3, U4, J1, D1, D2, SW1, SW2.
- [ ] D2 (KT-0603R): the maker numbers its terminals opposite to KiCad; the cathode is on pad 1.
- [ ] Do not run "Update Footprints from Library" on this board without redoing the silkscreen clean-up.

### EMC
- [ ] `06-emc.md` findings 1 to 7 are accepted or scheduled for a later revision.

## Proposed waivers
None proposed, none approved.

## First power-up
1. Before powering: measure resistance 3V3 to GND at J2 (pin 1 = 3V3, pin 5 = GND), and VBUS to GND between the outer pad of F1 (the pad towards the USB connector) and J2 pin 5. There is no VBUS test point; this is the only place to reach it. Neither may be a short.
2. Power from a current-limited 5 V supply, or a USB port through a meter. The worst-case budget is 56 mA. Above 100 mA: unplug.
3. Measure 3V3 at J2 pin 1: about 3.3 V (3.25 to 3.35 V if the 1.5 % read from AP2112.pdf p8 is right; that table was read from scrambled text). The green LED may light only dimly (see the checklist); do not use it as the pass check.
4. Touch-test U2 and U1: neither may be hot.
5. Hold BOOT, tap RESET, release BOOT: the computer should list the STM32 USB bootloader. If it does not, the boot pin polarity (unverified) is the first suspect; use the SWD header instead.
6. Load firmware over SWD or USB, read the sensor over I2C (address from AHT20.pdf; not read by me), drive the red LED from PA4.

## Limits
- A clean ERC and DRC only prove the board obeys the rules that were set.
- The EMC stage is a risk estimate from geometry, not a compliance result. A lab measurement is required.
- Pin and footprint choices must be checked by a person against the datasheets before ordering.
- No hazardous voltage on this board (5 V maximum).

## Independent review (gate-reviewer helper, 2026-11-15)
First verdict: "gate must not count yet" - two stage 2 items missing from the checklist (U4 footprint, AHT20 humidity limits) and a power-up step that named a VBUS test point that does not exist. Those and its eight LOW findings are now in this file. It verified: both open gates stated in the first lines; every number above against `gates.md`, `release-run.log`, `block-check.md`, `drc.json` and `emc-geometry.json`; `fab/` holds exactly the listed files, all of 2026-11-15 11:16; the zip holds the 12 files of `fab/gerbers`; drill file 29 vias of 0.3 mm, 4 holes of 3.2 mm, 2 pegs of 0.65 mm, 9 header holes of 1.0 mm, 4 slots; both JLCPCB files list the same 27 designators without J2, J3, H1-H4; its own `run_gates.py --no-export` gave the same counts. It could not verify: the connector edge dimension and the AHT20 drawing (it could not render the PDFs), the "pads unchanged" comparison (no output on file), JLCPCB's rules, stock. The review was not repeated after these edits.
