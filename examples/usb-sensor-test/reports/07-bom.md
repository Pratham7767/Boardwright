# Stage 7 - BOM

Date: 2026-11-15. Unattended run. Build quantity 5.
**Gate: NOT PASSED.** Two lines fail: R3 is out of stock at LCSC, and U1 has 3 pieces in LCSC's own stock against 5 needed. JLCPCB's own assembly stock could not be checked for any line. The unattended run stopped here. **Later on 2026-11-15 the user chose in chat ("Yes, release") to go on with this gate open**; see `08-release.md`. The stage 2 gate is also still open.

Stock and prices are a snapshot of lcsc.com on 2026-11-15. "Own stock" is LCSC's own warehouse; "other" is the "Other Suppliers on LCSC" offers, a separate number with a lead time.

## Totals
| | |
|---|---|
| BOM lines | 22 (20 with an LCSC number; J2 and J3 are bare pads, not fitted by the fab) |
| Different purchased parts | 19 |
| Lines read at LCSC | 19 of 19 |
| ok | 17 |
| out of stock | 1 (R3) |
| stock below the build quantity | 1 (U1) |
| end-of-life or not-recommended notes shown | 0 |
| Parts cost per board at the price breaks read, without R3 | USD 5.57 (U1 is USD 4.09 of it). Not converted to INR: no exchange rate on file. Shipping, duty and tax not included. |

## Lines
| Refs | MPN on the page | LCSC | Own stock | Other | Unit price (USD) at the break read | Min / multiple | Tag on the LCSC page | Result | Read by |
|---|---|---|---|---|---|---|---|---|---|
| U1 | STM32F042K6T6 | C69216 | **3** | 102,000 (pack of 250, 9-11 days); 25; 500 | 4.0945 (1+), 3.5382 (10+) | 1 / 1 | SMT Extended | **FAIL: 3 < 5** | Claude |
| U2 | AP2112K-3.3TRG1 | C51118 | 30,280 | 52,918 | 0.1683 (5+) | 5 / 5 | SMT Extended | ok | Claude |
| U3 | AHT20 | C2757850 | 28,454 | 5,182; 31,764; 1,474 | 0.7491 (1+, reduced from 0.8054) | 1 / 1 | SMT Extended | ok | Claude |
| U4 | USBLC6-2SC6 | C7519 | 37,365 | 9,000; 119,730 | 0.1584 (5+) | 5 / 5 | SMT Extended | ok | Claude |
| J1 | TYPE-C-31-M-12 | C165948 | 514,155 | 200,000 | 0.1737 (5+, reduced from 0.1888) | 5 / 5 | SMT Extended | ok | Claude |
| F1 | SMD0805P050TF/12 | C90129 | 12,515 | none shown | 0.0941 (5+, reduced from 0.1022) | 5 / 5 | SMT Extended | ok | Claude |
| SW1, SW2 | TS-1187A-B-A-B | C318884 | 544,800 | none shown | 0.0216 (20+) | 20 / 20 | SMT Basic | ok | Claude |
| D1 | XL-1608UGC-04 | C965804 | 3,901,300 | none shown | 0.0051 (100+) | 100 / 100 | SMT Extended | ok | Claude |
| D2 | KT-0603R | C2286 | 3,223,100 | 735,138 | 0.0077 (100+) | 100 / 100 | SMT Basic | ok | Claude |
| C9 | CL10A106KP8NNNC | C19702 | 2,255,360 | 520,000; 1,200,000 | 0.0235 (20+) | 20 / 20 | SMT Basic | ok | Claude |
| C1, C2, C6 | CL05A105KA5NQNC | C52923 | 1,396,400 | 1,800,000; 2,400,000 | 0.0057 (100+) | 100 / 100 | not read | ok | helper |
| C3, C4, C8 | CL05B104KO5NNNC | C1525 | 7,002,100 | 1,800,000 | 0.0024 (100+) | 100 / 100 | SMT Basic | ok | helper; re-read by Claude, same numbers |
| C5 | CL10A475KO8NNNC | C19666 | 515,480 | 720,000; 720,000 | 0.0151 (10+) | 10 / 10 | not read | ok | helper |
| C7 | CL05B103KB5NNNC | C15195 | 1,810,200 | none shown | 0.0038 (100+) | 100 / 100 | not read | ok | helper (the page's FAQ text says 166,500; the stock box says 1,810,200) |
| R1, R2 | 0402WGF5101TCE | C25905 | 706,600 | none shown | 0.0014 (100+) | 100 / 100 | not read | ok | helper |
| R3 | 0402WGF1002TCE | C25744 | **0, "Out of Stock"** | none shown | no price shown | 100 / 100 | SMT Basic | **FAIL: out** | helper; re-read by Claude, same |
| R4, R5 | 0402WGF4701TCE | C25900 | 6,161,800 | none shown | 0.0017 (100+) | 100 / 100 | not read | ok | helper |
| R6, R7 | 0402WGF1001TCE | C11702 | 18,238,400 | none shown | 0.0013 (100+) | 100 / 100 | SMT Basic | ok | helper; re-read by Claude, same numbers |
| R8 | 0402WGF3300TCE | C25104 | 583,600 | none shown | 0.0011 (100+) | 100 / 100 | not read | ok | helper |
| J2, J3 | pin headers, no part number | - | - | - | - | - | - | not fitted by the fab; `07-hand-check.md` | - |

No page showed a part number different from the one searched for. No lifecycle warning was shown on any page. (The C19702 page has a sentence "not recommended for precision timing or resonant circuits": that is an application note about the X5R material, not a lifecycle status.)

## Problem lines
| Line | Problem | What it means | Options (the user decides) |
|---|---|---|---|
| R3, 10 k 1 % 0402, C25744 | LCSC own stock 0. It was 8,400 on 2026-11-14. | The boot pull-down cannot be bought from LCSC today. | (a) Wait for restock. (b) Another 10 k 1 % 0402 resistor: same footprint, no layout change, but it goes back through stage 2 (datasheet and rating). I checked one candidate, YAGEO RC0402FR-0710KL (C60490): also out of stock. I did not find a substitute with stock and propose none. (c) Check JLCPCB's assembly library itself: its stock is separate from LCSC's and was not readable in this run. |
| U1, STM32F042K6T6, C69216 | LCSC own stock 3; 5 needed. It was 16 on 2026-11-14. | Only 3 boards can be built from LCSC's own stock. | (a) Build 3 boards. (b) Use an "Other Suppliers on LCSC" offer: 500 or 102,000 pieces listed, but the 102,000 offer sells in packs of 250 and both have 9 to 16 business days lead time. (c) Check JLCPCB's assembly stock or a hand-checked distributor (`07-hand-check.md`). (d) The stage 2 fallback STM32F042C6T6 is a 48-pin package and would need a new layout. |

## Machine assembly (JLCPCB)
- **JLCPCB's parts library was not read.** A helper reached two pages (C69216 and C51118, both shown as "Extended", no stock figure in the page text) and lost the rest because three helpers were sharing one browser tab (my mistake in setting them up, not a block by the site). I did not repeat it. **All 19 lines: could not check at JLCPCB.**
- LCSC's own product pages carry a tag "SMT Basic" or "SMT Extended" (column above). Read on 14 lines: 6 Basic (SW1/SW2, D2, C9, C3/C4/C8, R3, R6/R7), 8 Extended (U1, U2, U3, U4, J1, F1, D1 and none of the passives). 5 lines not read. Extended parts usually carry a per-part set-up fee at JLCPCB; the fee was not read. Treat this tag as a hint, not as JLCPCB's answer.
- J2 and J3 are marked "do not populate" and are absent from the assembly files.

## Hand checks
`reports/07-hand-check.md` lists the header lines and a second-source line for U1 with search links for Robu and element14 India. Nothing in it is filled in; a line the user did not check stays open.

## Swaps made
None.

## Lines still open
1. R3: out of stock (gate).
2. U1: 3 of 5 (gate).
3. JLCPCB assembly stock and library type: all 19 lines not checked.
4. J2, J3: hand check not done.
5. INR cost: no rate given.

## Decision taken by Claude on 2026-11-15 under the user's standing instruction; NOT reviewed by the user
- Hand checks of local suppliers were **not** done and no number was filled in for the user. The list is written; the step stays open.

## Gate
No end-of-life part, but one out-of-stock part and one part below the build quantity: **NOT PASSED (open)**, carried forward by the user's decision of 2026-11-15.
