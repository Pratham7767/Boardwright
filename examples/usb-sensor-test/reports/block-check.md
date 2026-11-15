# Block check

Rule sources: TI SLVA689 (I2C), TI AN-1229 (track width), RP2040 hardware design guide (crystal), plugin EMC guide values (protection distance). Defaults marked 'default' are engineering estimates; the part's datasheet takes priority.

| id | sev | item | measured | limit | note |
|---|---|---|---|---|---|
| B1 | INFO | U1 pins 1,17,5 (/+3V3) | 1.5 mm | <= 5 mm (default) | nearest cap C7 10nF at pin 5, same layer; default, engineering estimate: use the IC's datasheet |
| B1 | INFO | U2 pin 1 (/VBUS_F) | 1.2 mm | <= 5 mm (default) | nearest cap C1 1uF at pin 1, same layer; default, engineering estimate: use the IC's datasheet |
| B1 | INFO | U3 pin 2 (/3V3_SENS) | 3.0 mm | <= 5 mm (default) | nearest cap C9 10uF at pin 2, same layer; default, engineering estimate: use the IC's datasheet |
| B2 | INFO | U4.3 -> connector (/USB_DM) | 7.5 mm to J1.B7 | <= 10 mm (default) | 2 via(s) of this net in the box between the pads (+1 mm); pad centre to pad centre |
| B2 | INFO | U4.4 -> connector (/USB_DM) | 5.3 mm to J1.B7 | <= 10 mm (default) | 2 via(s) of this net in the box between the pads (+1 mm); pad centre to pad centre |
| B2 | INFO | U4.1 -> connector (/USB_DP) | 7.5 mm to J1.B6 | <= 10 mm (default) | 0 via(s) of this net in the box between the pads (+1 mm); pad centre to pad centre |
| B2 | INFO | U4.6 -> connector (/USB_DP) | 5.3 mm to J1.B6 | <= 10 mm (default) | 0 via(s) of this net in the box between the pads (+1 mm); pad centre to pad centre |
| B2 | INFO | U4.5 -> connector (/VBUS) | 5.8 mm to J1.A4 | <= 10 mm (default) | 1 via(s) of this net in the box between the pads (+1 mm); pad centre to pad centre |
| B4 | INFO | /I2C_SCL | 4700 ohm | 967..11802 ohm (standard, tr 1000 ns) | R4 to /+3V3; Vcc 3.3 V; Cb 100 pF default (assumed bus capacitance; formulas from TI SLVA689) |
| B4 | INFO | /I2C_SDA | 4700 ohm | 967..11802 ohm (standard, tr 1000 ns) | R5 to /+3V3; Vcc 3.3 V; Cb 100 pF default (assumed bus capacitance; formulas from TI SLVA689) |
| B5 | INFO | /VBUS | min 0.400 mm | >= 0.017 mm = 0.0561 A x 0.305 mm/A (default) | TI AN-1229 s6.1, valid for the conditions stated there; default |
| B5 | INFO | /VBUS_F | min 0.300 mm | >= 0.017 mm = 0.0561 A x 0.305 mm/A (default) | TI AN-1229 s6.1, valid for the conditions stated there; default |
| B5 | INFO | /+3V3 | min 0.300 mm | >= 0.017 mm = 0.056 A x 0.305 mm/A (default) | TI AN-1229 s6.1, valid for the conditions stated there; default |
| B5 | INFO | /3V3_SENS | min 0.400 mm | >= 0.000 mm = 0.0006 A x 0.305 mm/A (default) | TI AN-1229 s6.1, valid for the conditions stated there; default |
| B5 | INFO | /GND | min 0.300 mm | >= 0.017 mm = 0.0561 A x 0.305 mm/A (default) | TI AN-1229 s6.1, valid for the conditions stated there; default |
| B6 | INFO | usb-sensor-test-bom.csv vs usb-sensor-test-pos.csv | BOM 27 refs, pos 27 refs | - | BOM and placement references match (case-sensitive) |
| B7 | INFO | F_Paste (top) | 113 flashes in usb-sensor-test-F_Paste.gtp; 113 SMD pads with paste | - | flashes are counted from lines ending D03*; regions (G36) and stencil-only apertures are not counted |
| B7 | INFO | B_Paste (bottom) | 0 flashes in usb-sensor-test-B_Paste.gbp; 0 SMD pads with paste | - | flashes are counted from lines ending D03*; regions (G36) and stencil-only apertures are not counted |

rows 18: errors 0, warnings 0, info 18; not placed: 0 parts
