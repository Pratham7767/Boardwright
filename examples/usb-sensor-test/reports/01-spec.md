# Stage 1 - Spec

Date: 2026-11-14. Mode: guided. Entry point: from an idea.
Status: **confirmed by the user on 2026-11-14**. No parts are chosen in this stage; part numbers come in stage 2 from datasheets.

## What the board does
A USB-C cable from a computer supplies 5 V and carries data. A 3.3 V regulator powers an STM32 microcontroller and one I2C temperature + humidity sensor. The microcontroller reads the sensor and sends the readings to the computer as a USB serial port.

## Requirements
Source is `user` (answered in the interview) or `ASSUMPTION` (my default, please confirm or change).

| # | Item | Value | Source |
|---|---|---|---|
| R1 | Input power | USB-C receptacle, 5 V from the host | user |
| R2 | USB-C role | power sink only, default USB power: 5.1 k pull-down on each CC pin, no Power Delivery | ASSUMPTION |
| R3 | Input voltage range to design for | 4.4 to 5.5 V at the connector | ASSUMPTION (USB limits; to be cited from the standard in stage 3) |
| R4 | Total board current from USB | 100 mA or less | ASSUMPTION |
| R5 | Regulated rail | 3.3 V, single rail, linear regulator | user (3.3 V), ASSUMPTION (linear) |
| R6 | 3.3 V load to budget for | 80 mA or less, checked against datasheet maximums in stage 3 | ASSUMPTION |
| R7 | Microcontroller | STM32 family with built-in USB device; small package the fab can place | user (family), ASSUMPTION (rest) |
| R8 | Sensor | one I2C temperature + humidity sensor | user |
| R9 | I2C bus | 3.3 V levels, up to 400 kHz, pull-up resistors on the board | ASSUMPTION |
| R10 | Data out | USB 2.0 full-speed (12 Mbit/s), serial port (CDC) | user (USB to computer), ASSUMPTION (full-speed CDC) |
| R11 | USB protection | ESD protection on D+/D- and VBUS at the connector; input fuse or current limit | ASSUMPTION |
| R12 | Firmware loading | over USB using the boot button (STM32 built-in bootloader); SWD header as fallback | user (buttons, header), ASSUMPTION (method) |
| R13 | Indicators | power LED on 3.3 V; status LED on a microcontroller pin | user |
| R14 | Buttons | reset, boot | user |
| R15 | Debug header | SWD: 3V3, SWDIO, SWCLK, NRST, GND; 1x5, 2.54 mm pitch | user (header), ASSUMPTION (pinout, pitch) |
| R16 | Spare header | I2C: 3V3, SDA, SCL, GND; 1x4, 2.54 mm pitch | user (header), ASSUMPTION (pinout, pitch) |
| R17 | Board size | about 30 x 40 mm, four mounting holes for M3 screws | user (size), ASSUMPTION (M3) |
| R18 | Layers | 2 | ASSUMPTION |
| R19 | Enclosure | none | user |
| R20 | Environment | outdoors or humid place | user |
| R21 | Ambient range | -20 to +60 C, up to 95 % RH, occasional condensation | ASSUMPTION |
| R22 | Moisture protection | conformal coating applied by you after assembly, sensor opening and connectors left uncoated; ENIG finish | ASSUMPTION |
| R23 | Sensor placement | at a board edge, away from the regulator and microcontroller, so their heat does not shift the reading | ASSUMPTION |
| R24 | Assembly | machine assembly by JLCPCB; parts from the assembler's stock | user |
| R25 | Through-hole headers | pads on the board; pin headers soldered by hand or left unfitted | ASSUMPTION |
| R26 | Quantity and cost | 5 boards, lowest sensible cost | user |
| R27 | Fab | JLCPCB | default |
| R28 | Region | India, costs in INR | user |
| R29 | Suppliers | LCSC / JLCPCB (checked automatically); Robu, element14 India (checked by hand) | user |
| R30 | Target standard | none (personal prototype, not for sale) | ASSUMPTION |

## Classification
| Question | Answer |
|---|---|
| Highest voltage | 5 V DC (USB VBUS) |
| Mains-connected | no |
| Hazardous voltage (above 60 V DC or 30 V AC) | no |
| Isolation barrier | no |
| Fast signals | no. USB full-speed is below the pipeline's high-speed threshold (USB 2.0 high-speed or faster). D+/D- are still routed as a short matched pair. |
| Four or more layers | no |

The high-voltage and high-speed rule sets do not apply.

## Block diagram
```
USB-C receptacle
  |-- VBUS 5 V --> protection (fuse, ESD) --> 3.3 V linear regulator --> 3V3 rail
  |-- CC1, CC2 --> 5.1 k to GND each
  |-- D+ / D-  --> ESD protection --> STM32 USB pins

3V3 rail --> STM32 microcontroller
         --> temperature + humidity sensor
         --> I2C pull-ups, power LED
         --> SWD header, spare I2C header

STM32 <--I2C (SDA, SCL)--> sensor and spare I2C header
STM32 --> status LED
STM32 <-- reset button, boot button
STM32 <--SWD (SWDIO, SWCLK, NRST)--> debug header
```

## Interfaces
| Connector | Pins | Signal levels |
|---|---|---|
| J1 USB-C receptacle (USB 2.0 type) | VBUS, GND, CC1, CC2, D+, D-, shield | VBUS 5 V; D+/D- USB full-speed; CC pulled to GND through 5.1 k |
| J2 SWD header, 1x5, 2.54 mm | 3V3, SWDIO, SWCLK, NRST, GND | 3.3 V logic |
| J3 spare I2C header, 1x4, 2.54 mm | 3V3, SDA, SCL, GND | 3.3 V logic, up to 400 kHz |
| 4 mounting holes | M3 | not connected (decided in stage 5) |

## Target standard
None. Not intended for sale, so no EMC or safety certification is targeted.

## Open assumptions to confirm
1. R21/R22: "outdoors or humid" with no enclosure is the hardest requirement here. I assumed -20 to +60 C, condensation possible, and that you will coat the finished board yourself. Direct rain needs an enclosure; a bare board will not survive it even coated.
2. R4/R6: 100 mA total is plenty for this circuit and keeps the regulator cool; stage 3 checks it with datasheet numbers.
3. R5: a linear regulator (simple, quiet, 2 or 3 parts) instead of a switching one.
4. R11: USB ESD protection and an input fuse are included.
5. R15/R16/R25: header pinouts, 2.54 mm pitch, and that the fab does not fit the through-hole headers.
6. R17/R18: M3 mounting holes, 2-layer board.
7. R2/R10: plain 5 V USB-C sink, USB full-speed serial port.
8. R30: no target standard.

## Gate
Every requirement has a value and a source: **yes, 30 of 30**. 10 are from the user, 1 is the fab default, 19 are fully or partly assumptions (12 fully, 7 partly).
Gate status: **PASSED**. The user confirmed the spec as written, assumptions included, on 2026-11-14.
