# usb-sensor-test

Claude reads this file at the start of every session.

## Idea
A small USB-C powered sensor board. A USB-C cable from a computer supplies 5 V and carries data. A 3.3 V regulator powers a small STM32 microcontroller and one I2C temperature + humidity sensor. The microcontroller reads the sensor and reports the readings to the computer over USB as a serial port. The board is meant for outdoor or humid locations.

## Mode
guided

## Entry point
from an idea

## Must-haves
| Item | Value | Source |
|---|---|---|
| Input power | USB-C, 5 V from the host (default USB power, no Power Delivery negotiation) | user |
| Outputs / loads | 3.3 V rail for the microcontroller, one I2C temperature + humidity sensor, 2 LEDs, spare I2C header | user |
| Data out | USB 2.0 full-speed (12 Mbit/s) device, appears as a serial port | user |
| Microcontroller | STM32 family, with built-in USB; exact part chosen in stage 2 | user |
| Connectors | USB-C receptacle; SWD debug header; 4-pin spare I2C header | user |
| Extras | power LED, status LED, reset button, boot button | user |
| Board size limit | about 30 x 40 mm, four mounting holes, no enclosure | user |
| Ambient and enclosure | outdoors or humid place (user); -20 to +60 C, up to 95 % RH, occasional condensation | ASSUMPTION - confirm |
| Assembly | machine assembly by the fab (JLCPCB) | user |
| Build quantity | 5, low cost | user |
| Fab | JLCPCB | default |
| Country and currency | India, INR | user |
| Suppliers to check | LCSC / JLCPCB automatically; local (Robu, element14 India) by hand | user |
| Fast interfaces (USB, Ethernet, DDR, RF ...) | none. USB full-speed only (12 Mbit/s), below the high-speed threshold; D+/D- still routed as a short pair | ASSUMPTION - confirm |
| Layers | 2 | ASSUMPTION - confirm |
| Target standard | none (personal prototype, not for sale) | ASSUMPTION - confirm |

## Voltage class
Highest voltage on the board: 5 V DC (USB VBUS)
Mains-connected: no
Isolation barrier: no
Hazardous voltage: no. The high-voltage rules do not apply.

## Stage 2 candidate parts (2026-11-14, not yet verified against datasheets)
Stock is LCSC's own stock as read on lcsc.com on 2026-11-14. Nothing here counts until its datasheet is in `datasheets/` and its pins and footprint are checked.

| Role | MPN | Manufacturer | LCSC | Package (per LCSC) | Stock |
|---|---|---|---|---|---|
| Microcontroller | STM32F042K6T6 | ST | C69216 | LQFP-32 (7x7), tray | 16 |
| 3.3 V regulator | AP2112K-3.3TRG1 | Diodes Inc. | C51118 | SOT-25 | 30,565 |
| Temp + humidity sensor | AHT20 | Aosong | C2757850 | SMD | 29,678 |
| USB-C receptacle | TYPE-C-31-M-12 | Korean Hroparts Elec | C165948 | SMD | 517,615 |
| USB ESD protection | USBLC6-2SC6 | ST | C7519 | SOT-23-6L | 39,070 |
| Resettable fuse 500 mA, 12 V | SMD0805P050TF/12 | RUILON | C90129 | 0805 | 12,515 |
| Buttons (reset, boot) | TS-1187A-B-A-B | XKB Connection | C318884 | SMD 5.1x5.1 mm | 506,080 |
| Power LED, green | XL-1608UGC-04 | XINGLIGHT | C965804 | 0603 | 3,911,400 |
| Status LED, red | KT-0603R | Hubei KENTO | C2286 | 0603 | 3,359,200 |
| Capacitor 100 nF 16 V X7R | CL05B104KO5NNNC | Samsung | C1525 | 0402 | 7,500,200 |
| Capacitor 1 uF 25 V X5R | CL05A105KA5NQNC | Samsung | C52923 | 0402 | 1,536,500 |
| Resistor 10 k 1 % | 0402WGF1002TCE | UNI-ROYAL | C25744 | 0402 | 8,400 |
| Resistor 5.1 k 1 % | 0402WGF5101TCE | UNI-ROYAL | C25905 | 0402 | 745,600 |
| Resistor 4.7 k 1 % | 0402WGF4701TCE | UNI-ROYAL | C25900 | 0402 | 6,440,300 |
| Resistor 1 k 1 % | 0402WGF1001TCE | UNI-ROYAL | C11702 | 0402 | 18,453,000 |
| Headers J2 (1x5), J3 (1x4) | generic 2.54 mm pin header, not fitted by the fab | - | - | through-hole | - |

Rejected: Sensirion SHT40-AD1B and SHTC3 (no Sensirion stock at LCSC, only other brands under the same name); Everlight 19-217/GHC-YR1S2/3T green LED C72043 (out of stock).

## Decisions (newest first, with date)
- 2026-11-15: **User chose to go on to the release with the stage 7 gate open** (R3 out of stock, U1 3 of 5 at LCSC; JLCPCB library not checked). Answer given in chat: "Yes, release". The stage 2 gate also stays open. Both are carried into the release checklist.
- 2026-11-15: **Unattended run (stages 5 to 8). Every entry dated 2026-11-15 below was decided by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user.**
- 2026-11-15: Run stopped at the stage 7 gate (R3 out of stock, U1 3 of 5 at LCSC). No release files. Hand checks of local suppliers not done; the list is in reports/07-hand-check.md. Decided by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user.
- 2026-11-15: Board outline 30 x 40 mm, four M3 holes 3.5 mm from the corners (non-plated, not connected), USB-C centred on the bottom edge and overhanging about 1 mm (edge position read from TYPE-C-31-M-12.pdf p1), I2C header top edge, SWD header right edge, reset button left edge, boot button right edge, sensor top right. Decided by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user.
- 2026-11-15: Placement and placement review (reports/05-layout.md). Decided by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user.
- 2026-11-15: I2C design speed 100 kHz (standard mode) - ASSUMPTION, the speed is not on file (spec R9 says "up to 400 kHz"). 4.7 k pull-ups kept; `block.i2c_mode` = `standard`. At 400 kHz with a 100 pF bus they would be above the 3.5 k maximum. Set on the user's instruction for this run; not reviewed.
- 2026-11-15: Vias 0.6 mm pad / 0.3 mm hole (the net class says 0.7 mm). Decided by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user.
- 2026-11-14: User chose to switch the microcontroller from STM32F042F6P6TR (20-pin) to the 32-pin version, STM32F042K6T6, so the USB pins PA11/PA12 are dedicated pins and USB firmware loading does not depend on a pin remap. Fallback if stock runs out: STM32F042C6T6 (LQFP48, C88447). Full stage 2 table, including the extra capacitors and the 330 R resistor: reports/02-parts.md.
- 2026-11-14: User confirmed the stage 1 spec (reports/01-spec.md) as written, all assumptions included. Every "ASSUMPTION - confirm" in the must-haves table above is confirmed.
- 2026-11-14: Interview answers recorded (guided mode, from an idea). Sensor type: temperature + humidity. Data out: USB to a computer. Assembly: machine, by the fab. Suppliers: LCSC/JLCPCB and local Indian distributors. Region: India, INR. Quantity: 5, low cost. Size: about 30 x 40 mm, no enclosure. Environment: outdoors or humid. Microcontroller family: STM32. Extras: power and status LEDs, reset and boot buttons, debug header, spare I2C header.

## Approved waivers (with date)
- none
