# Stage 7 - Hand check (for the user)

Date written: 2026-11-15. **Nothing in this file has been checked.** Robu and element14 India are checked by hand (PROJECT.md); Claude does not browse them. Open each link, read the numbers, fill in the empty columns. Look for: the exact part number including the suffix, stock at the supplier's own warehouse, lifecycle status, minimum order quantity.

## Lines LCSC / JLCPCB do not cover
The two pin headers are not fitted by the fab (spec R25) and carry no part number. Any 2.54 mm single-row male header cut to length fits. Quantities are for 5 boards.

| Refs | Part | Needed | Robu search | element14 India search | Stock | Unit price | Currency | Date |
|---|---|---|---|---|---|---|---|---|
| J2 | pin header 1x5, 2.54 mm, straight | 5 | https://robu.in/?s=2.54mm+male+pin+header+1x40 | https://in.element14.com/search?st=2.54mm%20pin%20header%201%20row | | | | |
| J3 | pin header 1x4, 2.54 mm, straight | 5 | same as J2 (one 1x40 strip covers both) | same as J2 | | | | |

## Optional second source for the parts that are thin at LCSC
Fill this in only if `07-bom.md` flags a line as low or out. The links search by manufacturer part number.

| Refs | MPN | Needed | Robu search | element14 India search | Stock | Unit price | Currency | Date |
|---|---|---|---|---|---|---|---|---|
| U1 | STM32F042K6T6 | 5 | https://robu.in/?s=STM32F042K6T6 | https://in.element14.com/search?st=STM32F042K6T6 | | | | |

## Cost
Landed cost (shipping, import duty, tax) is not estimated. Add it yourself. Prices in `07-bom.md` are in the supplier's own currency; give me a USD to INR rate and its date if you want an INR column.
