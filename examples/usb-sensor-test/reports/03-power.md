# Stage 3 - Power budget

Date: 2026-11-14.
**The stage 2 gate is open** (boot pin polarity not on file, sensor footprint, 10 uF capacitor). The user chose on 2026-11-14 to go on; those items are carried forward.

Page numbers are PDF pages of the files in `datasheets/`. Every datasheet figure in this report was read by me from the rendered page unless marked "helper".

## Power tree
```
USB-C VBUS (4.4 to 5.5 V, ASSUMPTION R3)
  -> F1 resettable fuse (0.5 A hold, 0.85 ohm max)
  -> VBUS_F: U4 ESD part (VBUS pin), U2 input, 1 uF
  -> U2 AP2112K-3.3 linear regulator
  -> 3V3: U1 (VDD, VDDIO2, VDDA), U3 through 330 R, D1, I2C pull-ups, J2, J3
```
One regulated rail (3V3) and one unregulated rail (VBUS).

## Worst-case current on 3V3
Datasheet maximums, not typicals. Resistor loads use 3.35 V (3.3 V + 1.5 %, AP2112.pdf p8).

| Load | Worst case | Basis |
|---|---|---|
| U1 run current, 48 MHz, internal 48 MHz oscillator, all peripherals on, 85 C | 23.4 mA | STM32F042x4-x6.pdf Table 26 p50 (measured at 3.6 V) |
| U1 analog supply | 0.3 mA | 163 uA typical (Table 30 p55, helper); no maximum given, rounded up - ASSUMPTION |
| U3 sensor while measuring | 0.6 mA | AHT20.pdf Table 2 p2 |
| D1 power LED through 1 k | 3.35 mA | upper bound 3.35 V / 1 k, LED voltage ignored |
| D2 status LED through 1 k (from a U1 pin) | 3.35 mA | same bound |
| I2C pull-ups, 2 x 4.7 k, both lines low | 1.43 mA | 2 x 3.35 V / 4.7 k |
| USB D+ pull-up inside U1 | 3.05 mA | upper bound 3.35 V / 1.1 k minimum pull-up (Table 65 p89, helper), host side taken as a short |
| Boot button held (10 k) | 0.34 mA | 3.35 V / 10 k |
| Reset button held (U1 internal pull-up) | 0.13 mA | 3.35 V / 25 k minimum (Table 53 p78, helper) |
| Spare I2C header J3 | 20 mA | allowance for one plugged-in sensor - ASSUMPTION |
| **Total 3V3** | **56.0 mA** | |

## Headroom per rail

| Rail | Worst-case load | Limit | Headroom | Pass (20 % needed) |
|---|---|---|---|---|
| 3V3 against the spec budget (R6) | 56.0 mA | 80 mA | 30 % | yes |
| 3V3 against the regulator | 56.0 mA | 600 mA minimum output (AP2112.pdf p8) | 91 % | yes |
| VBUS against the spec budget (R4) | 56.1 mA (3V3 load + 80 uA regulator quiescent, p8) | 100 mA | 44 % | yes |
| VBUS against the fuse | 56.1 mA | 0.33 A hold at 60 C (SMD0805P050TF-12.pdf p3) | 83 % | yes |

## Voltage margins

| Check | Value | Limit | Result |
|---|---|---|---|
| U2 input, highest | 5.5 V | 6.0 V recommended, 6.5 V absolute (AP2112.pdf p3) | ok |
| U2 input, lowest, after the fuse | 4.4 V - 56.1 mA x 0.85 ohm = 4.35 V | 3.35 V + 0.2 V dropout (maximum at 300 mA, p8) = 3.55 V | 0.80 V margin |
| 3V3 for the USB transceiver | 3.25 to 3.35 V | 3.0 to 3.6 V (STM32 Table 65 p89, helper) | ok |
| 3V3 against U1 absolute maximum | 3.35 V | 4.0 V (p45, helper) | ok |
| U3 supply after the 330 R filter | 3.25 V - 0.6 mA x 330 R = 3.05 V | 2.2 to 5.5 V (AHT20.pdf p2) | ok |
| Fuse voltage rating | 5.5 V | 12 V (p2) | ok |
| Capacitors on VBUS (1 uF, 25 V) | 5.5 V | 25 V | ok |
| Capacitors on 3V3 (lowest rating 10 V) | 3.35 V | 10 V | ok |

## Dissipation and temperature
Ambient 60 C (spec R21).

| Part | Power | Thermal resistance | Rise | Junction at 60 C | Limit | Result |
|---|---|---|---|---|---|---|
| U2 at the 56.0 mA worst case | (5.5 - 3.25) V x 56.0 mA + 5.5 V x 80 uA = 126 mW | 184 C/W, no heatsink (AP2112.pdf p3) | 23 C | 83 C | 150 C absolute (p3); shutdown 160 C typical (p8) | ok |
| U2 at the full 80 mA budget | 180 mW | 184 C/W | 33 C | 93 C | same | ok |
| U1 | below 0.1 W (3.35 V x 23.7 mA = 79 mW plus pin loads) | 57 C/W, LQFP32 (STM32 p111) | below 6 C | below 66 C | 105 C for suffix 6 (p47, helper) | ok |
| F1 | 56.1 mA squared x 0.85 ohm = 2.7 mW | - | negligible | - | - | ok |
| LED resistors (1 k) | 11 mW each | - | - | - | 62.5 mW (LCSC listing; series datasheet not opened) | ok |

The regulator datasheet gives no recommended junction limit, only the 150 C absolute maximum and an ambient range of -40 to 85 C. The result has 57 C of margin to the absolute maximum.

## What this means in plain words
- The board draws about 56 mA in the worst case, a little over half of the 100 mA allowed.
- The regulator wastes about an eighth of a watt as heat and runs about 23 C above the air around it. That heat is why the sensor must sit away from it (spec R23).
- The fuse will not trip in normal use, even on a hot day.

## Assumptions and unverified items
1. Input range 4.4 to 5.5 V (R3) is taken from general USB knowledge; the USB standard is not on file.
2. The 20 mA allowance for the spare header is my choice. A device needing more than about 40 mA there would break the 80 mA budget (not the regulator).
3. U1 analog supply current has no datasheet maximum; 0.3 mA is a rounded-up typical.
4. Thermal resistance figures are for the makers' test boards; a small board with little copper can run hotter. Not measured.
5. Helper-read figures (marked) were not re-opened by me.
6. Open from stage 2: boot pin polarity not on file, sensor footprint, 10 uF capacitor.

## Gate
Every rail has at least 20 % current headroom: **yes** (lowest is 30 %, 3V3 against the spec budget).
No part above its rated junction temperature: **yes**.
Gate status: **PASSED**, with the stage 2 gate still open.
