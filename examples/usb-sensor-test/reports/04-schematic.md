# Stage 4 - Schematic

Date: 2026-11-14.
**The stage 2 gate is still open** (boot pin polarity not on file, sensor footprint pad size, 10 uF capacitor). Carried forward by the user's decision of 2026-11-14.

## What was made
- KiCad project in the folder root: `usb-sensor-test.kicad_pro`, `.kicad_sch` (one A3 sheet), `.kicad_pcb` (empty board).
- Project library `lib/`: symbol `usb-sensor-test:AHT20` and footprint `usb-sensor-test:AHT20_3x3mm_P1.0mm`, registered in `sym-lib-table` and `fp-lib-table`.
- 33 parts on the sheet (27 fitted by the fab, 2 headers and 4 mounting holes marked "do not populate"), 18 named nets, 4 power flags, 20 no-connect marks.
- Every fitted part carries Footprint, MPN, LCSC and Datasheet fields.

## Gate results

| Check | Result |
|---|---|
| `sch_check.py` | 0 errors, 2 warnings (33 components, 41 nets) |
| ERC (`run_gates.py --no-export`) | 0 errors, 0 warnings |
| Rule guard | pass (no custom rules yet; 1 class, 0 patterns) |
| DRC with parity | **FAIL, as expected at this stage**: 33 missing footprints and 1 invalid outline, because the board is still empty. This is the stage 5 gate, not the stage 4 gate. |

### Remaining warnings
| Check | Part | Message | Why it is acceptable |
|---|---|---|---|
| S2 | U1 | no datasheet file matched (tried: stm32f042k6t6) | The check matches file names. The file is `STM32F042x4-x6.pdf`, the family datasheet that covers this part; the Datasheet field points to it. |
| S2 | U2 | no datasheet file matched (tried: ap2112k, 3trg1, ap2112k33) | Same reason: the file is `AP2112.pdf`. |

## Netlist as exported by KiCad (checked against the plan, all match)

| Net | Pins |
|---|---|
| VBUS | J1 A4, A9, B4, B9; F1.1; U4.5 |
| VBUS_F | F1.2; U2.1 (VIN); U2.3 (EN); C1.1 |
| +3V3 | U2.5 (VOUT); C2.1; U1.1 (VDD), U1.17 (VDDIO2), U1.5 (VDDA); C3.1, C4.1, C5.1, C6.1, C7.1; R4.1, R5.1, R6.1, R8.1; SW2.1; J2.1; J3.1 |
| 3V3_SENS | R8.2; C9.1; U3.2 (VDD) |
| GND | J1 A1, A12, B1, B12, SH; U1.16, U1.32; U2.2; U3.5; U4.2; C1-C9 pin 2; R1.2, R2.2, R3.2; D1.1, D2.1 (cathodes); SW1.2; J2.5; J3.4 |
| CC1 / CC2 | J1.A5, R1.1 / J1.B5, R2.1 |
| USB_DP | J1 A6, B6; U4.1, U4.6; U1.22 (PA12) |
| USB_DM | J1 A7, B7; U4.3, U4.4; U1.21 (PA11) |
| I2C_SCL | U1.29 (PB6); R4.2; U3.3; J3.3 |
| I2C_SDA | U1.30 (PB7); R5.2; U3.4; J3.2 |
| NRST | U1.4; C8.1; SW1.1; J2.4 |
| BOOT0 | U1.31; R3.1; SW2.2 |
| SWDIO / SWCLK | U1.23, J2.2 / U1.24, J2.3 |
| LED_STATUS, LED_STATUS_A | U1.10 (PA4), R7.1 / R7.2, D2.2 |
| LED_PWR_A | R6.2, D1.2 |
| Not connected (marked) | J1 A8, B8 (SBU); U1 pins 2, 3, 6-9, 11-15, 18-20, 25-28; U2.4; U3.1, U3.6 |

Header pinouts: J2 = 3V3, SWDIO, SWCLK, NRST, GND. J3 = 3V3, SDA, SCL, GND.

## Reference circuits and deviations

| Block | Reference | Followed | Deviation |
|---|---|---|---|
| Regulator U2 | AP2112.pdf p2 typical circuit (1 uF in, 1 uF out) | yes | EN is tied to the input instead of a control signal. Allowed: EN high level up to 6.0 V (p8); it must not float because of the internal 3 M pull-down (p2). |
| Sensor U3 | AHT20.pdf p8 Fig 15 (4.7 k pull-ups to the supply, 330-390 R series resistor, 10 uF) | yes: 4.7 k, 330 R, 10 uF | none |
| Microcontroller supply | STM32 datasheet Fig 13 p43 (helper): 100 nF per supply pin plus 4.7 uF; VDDA 10 nF + 1 uF | yes: C3, C4 (100 nF), C5 (4.7 uF), C6 (1 uF), C7 (10 nF) | VDDA is tied straight to +3V3, no filter bead. The ADC is not used. |
| Reset | STM32 datasheet Fig 25 p78 (helper): button and 100 nF to ground | yes: SW1, C8 | none |
| USB ESD U4 | USBLC6-2.pdf Fig 14 p8 | yes | VBUS pin is connected on the connector side of the fuse. |
| USB data | STM32 datasheet Table 65 p89 footnote (helper): no series resistors needed, pull-up is internal | yes | none |
| USB-C connector | no reference on file | - | 5.1 k from each CC pin to ground and the shell tied to ground are from general USB-C practice - **ASSUMPTION, the USB-C standard is not on file**. |
| Boot circuit | AN2606 (read online, not on file) | BOOT0 pulled down by 10 k (R3), SW2 pulls it to 3.3 V | **unverified by a file in datasheets/** |

## Symbol notes
- U1, U2 and U4 use the base library symbols `STM32F042K_4-6_Tx`, `AP2204K-1.5` and `USBLC6-2P6`, because the schematic tool cannot place derived symbols. KiCad's own symbols for the exact parts are derived from these and share their pins, which were checked against the datasheets in stage 2. The Value and MPN fields carry the real part names.
- Mounting holes H1-H4 and headers J2, J3 are marked "do not populate" so the fab does not look for them; they still go on the board.
- Power flags sit on VBUS, VBUS_F, GND and 3V3_SENS, where the source is a connector, a fuse or a resistor that the checker cannot see through.

## Open items
1. Stage 2 items: boot pin polarity not on file; AHT20 pad size unverified (land pattern drawn by me: pads 0.9 x 0.45 mm at 1.0 mm pitch, columns 2.3 mm apart, from the package drawing in AHT20.pdf p1); 10 uF capacitor part number not in the catalogue on file.
2. USB-C CC resistor value and shell grounding are assumptions (above).
3. D2 (KT-0603R): the maker numbers its terminals the other way round from KiCad. The cathode is on pad 1 here; check the fab's placement preview.
4. The schematic was drawn with tools and checked by netlist, not looked at on screen. Net labels are used instead of drawn wires, so it reads as labelled blocks. Open it in KiCad and look it over.

## Gate
ERC 0 errors and `sch_check.py` 0 errors: **PASSED** (with the stage 2 gate still open).
