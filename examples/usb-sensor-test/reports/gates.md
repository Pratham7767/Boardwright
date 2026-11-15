# Gate results

| Gate | Status | Detail |
| --- | --- | --- |
| Rule guard | pass | 2 classes used by rules; 3 classes, 5 patterns |
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 17 warnings, 0 unconnected, 0 parity |
| DRC after zone refill | pass | 0 errors, 17 warnings, 0 unconnected, 0 parity |
| Gerbers | pass | 10 files in fab/gerbers |
| Drill | pass | 12 files in fab/gerbers |
| Gerber zip | pass | usb-sensor-test-gerbers.zip, 62890 bytes |
| Placement | pass | usb-sensor-test-pos.csv, 1995 bytes |
| BOM | pass | usb-sensor-test-bom.csv, 1646 bytes |
| Schematic PDF | pass | usb-sensor-test-schematic.pdf, 123420 bytes |
| JLCPCB assembly files | note | usb-sensor-test-jlc-bom.csv (20 lines, 0 without an LCSC number), usb-sensor-test-jlc-cpl.csv (27 parts). Rotations are KiCad's, unchanged: check every polarised and multi-pin part in JLCPCB's placement preview before confirming |
| Other files in fab/ | note | none |

ERC warnings: none
DRC warnings: lib_footprint_mismatch x14, silk_edge_clearance x2, silk_over_copper x1
DRC after zone refill warnings: lib_footprint_mismatch x14, silk_edge_clearance x2, silk_over_copper x1

Power budget, EMC, SI and BOM-stock gates are run by Claude; see the boardwright skill.
