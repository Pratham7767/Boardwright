# Stage 2 - Parts

Date: 2026-11-14. Stock is LCSC's own stock as read on lcsc.com on 2026-11-14 (a snapshot; stage 7 rechecks it).
Page numbers are PDF pages of the files in `datasheets/`.

How each fact was checked: "seen" = I looked at the rendered page myself. "helper" = read by a datasheet-reader helper from the PDF, not re-opened by me.

## Parts

| Ref | Role | MPN | LCSC | Stock | Datasheet file | Why chosen |
|---|---|---|---|---|---|---|
| U1 | Microcontroller | STM32F042K6T6 (ST), LQFP32, tray | C69216 | 16 | STM32F042x4-x6.pdf | STM32 as requested; USB device with internal 48 MHz oscillator, so no crystal (p10, p27, helper); 32-pin package has dedicated USB pins PA11/PA12 (Fig 6 p29, seen). Replaces the 20-pin STM32F042F6P6TR by user decision 2026-11-14 |
| U2 | 3.3 V regulator | AP2112K-3.3TRG1 (Diodes) | C51118 | 30,565 | AP2112.pdf | Input up to 6.0 V covers USB 5.5 V (p3, seen); 600 mA; needs only two 1 uF capacitors (p2, seen) |
| U3 | Temp + humidity sensor | AHT20 (Aosong) | C2757850 | 29,678 | AHT20.pdf | From the original maker and in stock; Sensirion SHT40/SHTC3 have no Sensirion stock at LCSC |
| U4 | USB ESD protection | USBLC6-2SC6 (ST) | C7519 | 39,070 | USBLC6-2.pdf | Made for USB 2.0 data lines plus VBUS (p1, seen) |
| J1 | USB-C receptacle | TYPE-C-31-M-12 (HRO) | C165948 | 517,615 | TYPE-C-31-M-12.pdf | 16-pin USB 2.0 type; KiCad has a footprint for this exact part |
| F1 | Resettable fuse | SMD0805P050TF/12 (RUILON) | C90129 | 12,515 | SMD0805P050TF-12.pdf | 12 V rating gives margin over 5.5 V; 0.33 A hold at 60 C (p3, helper) is above the 0.1 A budget |
| SW1, SW2 | Reset, boot buttons | TS-1187A-B-A-B (XKB) | C318884 | 506,080 | TS-1187A-B-A-B.pdf | KiCad has a footprint for this exact part |
| D1 | Power LED, green | XL-1608UGC-04 (XINGLIGHT) | C965804 | 3,911,400 | XL-1608UGC-04.pdf | In stock (first choice C72043 was out of stock) |
| D2 | Status LED, red | KT-0603R (KENTO) | C2286 | 3,359,200 | KT-0603R.pdf | In stock, cheap |
| C (100 nF) | Decoupling | CL05B104KO5NNNC, 16 V X7R 0402 (Samsung) | C1525 | 7,500,200 | Samsung-MLCC-catalogue.pdf (listed p25) | Standard |
| C (10 nF) | VDDA decoupling | CL05B103KB5NNNC, 50 V X7R 0402 (Samsung) | C15195 | 1,844,000 | Samsung-MLCC-catalogue.pdf (listed p25) | STM32 supply scheme (p43, helper) |
| C (1 uF) | Regulator in/out, VDDA | CL05A105KA5NQNC, 25 V X5R 0402 (Samsung) | C52923 | 1,536,500 | Samsung-MLCC-catalogue.pdf (listed p19) | AP2112 asks for 1 uF X5R/X7R (p2, seen) |
| C (4.7 uF) | STM32 VDD bulk | CL10A475KO8NNNC, 16 V X5R 0603 (Samsung) | C19666 | 585,630 | Samsung-MLCC-catalogue.pdf (listed p20) | STM32 supply scheme (p43, helper) |
| C (10 uF) | Sensor supply | CL10A106KP8NNNC, 10 V X5R 0603 (Samsung) | C19702 | 2,119,480 | Samsung-MLCC-catalogue.pdf (2015 edition; this exact part number is not listed in it) - unverified | AHT20 application circuit (p8, seen) |
| R (10 k, 5.1 k, 4.7 k, 1 k, 330 R) | Pull-downs, CC, I2C pull-ups, LEDs, sensor filter | 0402WGF1002TCE, ...5101..., ...4701..., ...1001..., ...3300TCE, 1 % 0402 (UNI-ROYAL) | C25744, C25905, C25900, C11702, C25104 | 8,400; 745,600; 6,440,300; 18,453,000; 589,200 | UNI-ROYAL-0402WGF.pdf | Standard; 4.7 k and 330 R are the AHT20 circuit values (p8, seen) |
| J2, J3 | SWD and I2C headers | generic 2.54 mm pin header, not fitted by the fab | - | - | none needed (bare holes) | Spec R25 |

## Pin tables and symbol check

| Part | Datasheet pins (page) | KiCad symbol | Match |
|---|---|---|---|
| U1 LQFP32 | 1 VDD, 2 PF0, 3 PF1, 4 NRST, 5 VDDA, 6-13 PA0-PA7, 14 PB0, 15 PB1, 16 VSS, 17 VDDIO2, 18-25 PA8-PA15, 26 PB3, 27 PB4, 28 PB5, 29 PB6, 30 PB7, 31 PB8-BOOT0, 32 VSS (Fig 6 p29, seen) | MCU_ST_STM32F0:STM32F042K6Tx | all 32 pins match (symbol names pin 32 VSSA) |
| U2 SOT25 | 1 VIN, 2 GND, 3 EN, 4 NC, 5 VOUT (p2, seen) | Regulator_Linear:AP2112K-3.3 | match |
| U3 | 1 NC, 2 VDD, 3 SCL, 4 SDA, 5 GND, 6 NC; NC pins left floating (Table 5 p8, seen) | none in KiCad - to be created in stage 4 | open |
| U4 SOT23-6L | 1 I/O1, 2 GND, 3 I/O2, 4 I/O2, 5 VBUS, 6 I/O1 (Fig 1 p1, seen) | Power_Protection:USBLC6-2SC6 | match |
| J1 | A1/A12/B1/B12 GND, A4/A9/B4/B9 VBUS, A5 CC1, B5 CC2, A6 DP1, A7 DN1, B6 DP2, B7 DN2, A8 SBU1, B8 SBU2 (p1, seen) | Connector:USB_C_Receptacle_USB2.0_16P | match |
| SW1, SW2 | terminals A-B joined, C-D joined, contact between the pairs (p1, seen) | Switch:SW_Push | match (footprint pad 1 = A,B; pad 2 = C,D) |
| D1 | terminal 1 = cathode, green mark at the cathode end (p7, seen) | Device:LED (pin 1 = K) | match |
| D2 | terminal 2 = cathode, green mark at the cathode end (p2, seen) | Device:LED (pin 1 = K) | maker's terminal numbers are reversed against KiCad; cathode mark goes to pad 1. Check the fab's placement preview |

Pins this design will use on U1 (stage 4 input): USB D- on pin 21 (PA11, USB_DM) and D+ on pin 22 (PA12, USB_DP) (Table 13 p34, text read by me); I2C1 SCL on pin 29 (PB6) and SDA on pin 30 (PB7) (Table 13 p35, text read by me); SWDIO pin 23 (PA13), SWCLK pin 24 (PA14) (Table 13 note 6 p36, helper); NRST pin 4; BOOT0 pin 31; VDD pin 1, VDDIO2 pin 17, VDDA pin 5, VSS pins 16 and 32.

## Key ratings

| Part | Rating | Value | Page |
|---|---|---|---|
| U1 | VDD range; USB transceiver supply | 2.0-3.6 V; 3.0-3.6 V | p47, p89 (helper) |
| U1 | Absolute max VDD | 4.0 V | p45 (helper) |
| U1 | Max run current, 48 MHz, all peripherals, 85 C | 23.4 mA | Table 26 p50 (helper) |
| U1 | Ambient, suffix 6; thermal resistance LQFP32 | -40 to 85 C (p47, helper); 57 C/W (p111, text read by me) | p47, p111 |
| U2 | Input: absolute max / recommended | 6.5 V / 2.5-6.0 V | p3 (seen) |
| U2 | Ambient; thermal resistance SOT25 | -40 to 85 C; 184 C/W | p3 (seen) |
| U2 | Output current; dropout at 300 mA | 600 mA min; 200 mV max | p8 (helper; table text was scrambled) |
| U2 | EN pin | active high, internal 3 M pull-down, so it must be tied high | p2 (seen) |
| U3 | Supply; absolute max | 2.2-5.5 V; 5.5 V | p8 (seen), p9 (helper) |
| U3 | Measuring current | 600 uA max | p2 (helper) |
| U3 | Accuracy | +/-2 %RH, +/-0.3 C typical; stated for non-condensing conditions | p2-3 (helper) |
| U4 | Leakage at 5.25 V; clamp at 1 A; line capacitance | 150 nA max; 12 V max; 3.5 pF max | p1 (seen), p2 (helper) |
| J1 | Current, voltage, temperature | 5 A, 20 V, -30 to 80 C | p1 (seen) |
| F1 | Hold / trip / max voltage; resistance | 0.5 A / 1.0 A / 12 V; 0.10-0.85 ohm | p2 (helper) |
| SW1, SW2 | Contact rating; temperature | 50 mA 12 V DC; -30 to 85 C | p1 (seen) |
| D1 | Forward voltage at 20 mA; max current | 2.6-3.4 V; 20 mA | p3 (helper) |
| D2 | Forward voltage at 20 mA; max current | 1.8-2.4 V; 25 mA | p3 (helper) |

## Footprint check

| Part | Datasheet land pattern | KiCad footprint | Result |
|---|---|---|---|
| U1 | pitch 0.80, pads 0.50 x 1.20, 7.30 between rows, 9.70 overall (Fig 43 p100, seen) | Package_QFP:LQFP-32_7x7mm_P0.8mm: pads 0.50 x 1.50, 6.85 between rows, 9.85 overall | fits; pads slightly longer |
| U2 | pitch 0.95, pads 0.55 x 0.80, row centres 2.40 (p14, helper) | Package_TO_SOT_SMD:SOT-23-5: pads 0.60 x 1.325, row centres 2.275 | fits; longer pads cover the leads |
| U4 | pitch 0.95; other numbers could not be assigned from text (p12, helper) | Package_TO_SOT_SMD:SOT-23-6 | pitch matches; rest unverified |
| J1 | pitch 0.50, 8 pads 0.30 wide, 4 pads 0.60 wide, peg holes 0.60 dia 5.78 apart, shell slots 8.65 apart and 4.18 apart (p1, seen) | Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12: same pad order and widths, holes 0.65 dia 5.78 apart, slots 8.64 and 4.18 apart; wide pads at 2.45 and 3.25 from centre against 2.40 from the drawing | matches within 0.05 mm |
| SW1, SW2 | pads span 7.0 outer / 5.0 inner in X, 4.5 outer / 3.0 inner in Y (p1, seen) | Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A: pads 1.0 x 0.75 at X +/-3.0, Y +/-1.875 | exact match |
| F1 | pads 1.0 x 1.5, 1.2 between them (p5, seen) | Fuse:Fuse_0805_2012Metric: pads 0.975 x 1.4, 0.9 between them | fits the 2.0-2.2 mm body; slightly smaller than the maker's pattern |
| D1 | pads 0.7 x 0.8, gap 0.7 (p7, seen) | LED_SMD:LED_0603_1608Metric: pads 0.875 x 0.95, gap 0.7 | fits |
| D2 | pads 0.70 long, gap 0.70 (p2, seen) | same | fits |
| U3 | body 3.0 x 3.0, 6 pads, 1.0 pitch, columns 2.0 apart; pad size small on the drawing, about 0.5 x 0.4 to 0.55 (Fig 1 p1, seen). No land pattern drawing in the datasheet | none in KiCad | **open: custom footprint to be drawn in stage 4; pad size unverified** |
| Passives | standard 0402 and 0603 | Capacitor_SMD / Resistor_SMD 0402 and 0603 | standard |

## Unverified and open items

1. **U1 boot pin polarity.** The datasheet says the built-in loader supports USB DFU (p13, helper) but does not give the BOOT0 polarity. ST application note AN2606 (Rev 71, read through a web fetch on 2026-11-14, not saved as a PDF because st.com does not answer automated downloads) says: BOOT0 pin high selects the loader; an empty chip enters the loader on its own; USB DFU uses PA11/PA12 with the internal oscillator. With the 32-pin package PA11/PA12 are real pins, so the remap doubt is gone. What stays **unverified by a file in datasheets/** is the BOOT0 polarity. The SWD header works regardless.
1a. **U1 stock is thin.** STM32F042K6T6 has 16 at LCSC on trays and 0 on reels, at about 3.54 USD each at 10 pieces against 1.51 USD for the 20-pin part. Verified fallback with the same datasheet and dedicated USB pins: STM32F042C6T6 (LQFP48, C88447, 278 in stock, about 3.92 USD at 10). Not checked: JLCPCB's own assembly stock.
2. **U3 footprint and symbol** do not exist in KiCad and the datasheet has no land pattern. Pad size is unverified.
3. **U3 in humid use.** Accuracy is stated for non-condensing air only; long exposure above 80 %RH gives a temporary +3 %RH drift (p2, p4, helper). The datasheet says nothing on conformal coating.
4. **U4 footprint dimensions** beyond the pitch were not assigned.
5. **10 uF capacitor CL10A106KP8NNNC**: LCSC's datasheet link for it is the Samsung 2015 catalogue, which does not list this exact part number. Voltage and dielectric come from the LCSC listing only.
6. **AN4879 (USB hardware guidelines)** not obtained; not relied on.
7. **U2 electrical table (p8)**: values read by position from scrambled text.
8. **MPN, LCSC and Datasheet fields in the symbols**: not done, because the schematic does not exist yet. They go in when the symbols are placed in stage 4.
9. Helper-read values marked "helper" above were not re-opened by me, except where marked "seen".

## Gate
Every part has a datasheet file in `datasheets/` and a cited pin table: **yes for all 9 active or electromechanical parts, the resistor series and four of the five capacitor values; no for the 10 uF capacitor** (item 5).
Gate status: **NOT PASSED (open)** on items 1 (boot pin polarity not on file), 2 (sensor footprint) and 5 (10 uF capacitor). Items 1a, 3 and 4 are carried to the release checklist.
