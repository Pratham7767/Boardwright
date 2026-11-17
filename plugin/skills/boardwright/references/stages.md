# Stage details

Each stage: what to do, what to hand to helpers, the gate, and what the report must contain. Reports are short markdown with numbers and tables.

## 1 Spec
- Guided mode: interview the user in plain language, one topic at a time: what the board does, what powers it, what it connects to, size limits, where it will be used (temperature, enclosure), who assembles it, budget, quantity. Offer a sensible default for each and mark it `ASSUMPTION - confirm`.
- Express mode: read `PROJECT.md`; ask only for what is missing and cannot be assumed safely (input voltage, output currents, connectors).
- Always ask, in both modes: how the board will be assembled (hand soldering, or machine assembly by the fab), the user's country and currency, and which suppliers they buy from. Part choice follows the assembly answer: hand soldering means 0805 and larger and leaded or gull-wing packages wherever a suitable part exists; machine assembly means parts the assembler stocks.
- Classify the board: fast signals or four or more layers yes/no (then read `high-speed.md`). Highest voltage present, mains-connected yes/no, isolation needed yes/no. If hazardous voltage is present, read `high-voltage.md` now and tell the user what it means for them.
- Report: requirements table (item, value, source), block diagram (text), interface list (connector, pins, signal levels), target standard or "none", open assumptions.
- Hazardous voltage or mains: fill the `safety` section of `boardwright.json` now (`high-voltage.md`): the standard and product class (the user's decisions), mains, pollution degree, altitude, laminate CTI, domains, barriers and supplies. Low-voltage board: record the supply's rated power under `safety.supplies` so its PS class is on file.
- Gate: every requirement has a value and a source.

## 2 Parts
- A part whose datasheet has no land-pattern drawing needs a footprint drawn from the package drawing. Say so, record the pad sizes you chose and why, and put it on the release checklist as unverified.
- You choose the parts. Prefer parts in stock at the project's suppliers, in packages the user can assemble (`PROJECT.md`: hand or machine assembly).
- Download each datasheet into `datasheets/` (manufacturer site first). If a download is blocked, ask the user to save the PDF there; do not work from memory.
- Run `uv run scripts/datasheet_index.py . --all` once, then start one `datasheet-reader` per part that has no `datasheets/<MPN>.facts.md` yet, in parallel, for every IC, transistor, diode, connector, transformer, and any part with a custom footprint. Passives from a standard series need the series datasheet once.
- Check each returned pin table against the KiCad symbol you intend to use. A symbol whose pin numbers differ from the datasheet package is wrong for that part even if the name matches. Same for the footprint: compare pad pitch and size with the datasheet land pattern.
- Run one quick `part-scout` pass over the non-passive parts now, so an unobtainable part is found before layout.
- Put `MPN`, the supplier field (`LCSC`, and `DigiKey` if used) and `Datasheet` into every symbol.
- Report: one row per part: ref, MPN, why chosen, key ratings with page cites, symbol and footprint with page cites, anything unverified.
- Gate: every part has a datasheet file and a cited pin table. Parts without one are listed as unverified and block the gate.

## 3 Power budget
- Power tree from input to every rail. Worst-case current per rail (sum of datasheet maximums, not typicals). Regulator headroom, dissipation and junction temperature rise at the stated ambient, with the thermal resistance and its page.
- Gate: every rail has at least 20% current headroom; no part above its rated junction temperature.

## 4 Schematic
- If the folder has no KiCad project yet, create one in the folder root with the project tool, named after the folder. Keep exactly one `.kicad_pro`, root `.kicad_sch` and `.kicad_pcb` there.
- Tell the user what you are about to draw. Use the schematic tools; never hand-edit the file.
- One function per area of the sheet, power flowing left to right, net labels with meaningful names. Hazardous nets get their own names from the start (the layout rules key on them).
- Before drawing, go through `design-practice.md` §5-7 for the blocks this board has (crystal load-capacitor arithmetic, USB protection ratings, inrush) and write the numbers into the report.
- Run `python scripts/sch_check.py .`: fields, footprint pads against symbol pins, single-pin nets, power pins, decoupling. Fix every error. Explain each warning in the report or fix it.
- Run `python scripts/run_gates.py . --sch-only` (the board is still empty, so DRC is listed as not run). Read every ERC warning: an "isolated label" or "pin not driven" warning is often a real wiring mistake.
- Report: ERC counts, each remaining warning with the reason it is acceptable, changes from the reference design.
- Mains boards: run `python scripts/mains_check.py .` and fix every FAIL (fuse first, X/Y classes, varistor after fuse, discharge path, earth). Give safety parts a `safety_class` field where the value text does not say X2/Y1.
- Gate: ERC 0 errors and `sch_check.py` 0 errors; on mains boards also `mains_check.py` PASS.

## 5 Layout
Order: stackup and rules, placement, review, power routing, signal routing, pours, cleanup.
1. Stackup and rules: pick the layer count and stackup from `design-practice.md` §1, and write the choice and the reason into the report. Board setup from `fab-jlcpcb.md`. Net classes for every power and hazardous net, stored as **patterns**, never per-net assignments (see `lessons.md`). Custom rules in the `.kicad_dru` for anything DRC must enforce: isolation, hole keep-outs. Write the pattern count into `boardwright.json` as `expect_netclass_patterns`. Hazardous boards: run `python scripts/creepage_rules.py . --write` to add the barrier rules, then `python scripts/safety_class.py .`. Boards with fast pairs: fill `high_speed` (`high-speed.md`) and run `python scripts/hs_rules.py . --write`.
2. Placement: write the floorplan first (blocks in current-flow order, critical loops per block), then place. Measure the critical loops on the placement with `emc_geometry.py` and read the unrouted list from `board_digest.py` before any routing. Connectors and mounting holes first, then the power path in current-flow order, then each IC with its decoupling. Stop and show the placement before routing. In guided mode, explain the three or four choices that matter.
3. Routing: you decide every route for mains, switch nodes, high-current paths and feedback lines, as coordinates. `pcb-mechanic` may push them and run the DRC loop. Low-risk signal nets may be autorouted only if the user asks.
4. Pours last, refilled under the full rule set. No pour inside a hazardous-voltage area.
5. Run the gate. Then run `barrier_check.py` if the board has an isolation barrier, and `block_check.py`. Put the rail currents from the power budget into `boardwright.json` under `block.currents` first, so track widths are checked against them. Explain or fix every warning in the report.
- Proof the rules fire: once per project, check on a scratch copy that a deliberate violation (a track moved across the barrier, a class removed) produces an error. Record it in the report.
- Report: board size and layers, rule table, key measured distances, routing method per net group, DRC counts, open items.
- Gate: rule guard pass; DRC with schematic parity 0 errors; 0 unconnected. Hazardous boards: `safety_class.py`, `barrier_check.py` and then `creepage_rules.py` PASS (the last one needs fresh DRC and barrier results). Fast pairs: `hs_rules.py` (KiCad python) PASS, and `impedance_check.py` within tolerance for every class in `high_speed.impedance`. Rails in `pdn`: run `pdn_check.py` and fix a rail that is over its target.

## 6 EMC and signal integrity
- Fill the `emc` section of `boardwright.json` for this board: the switching loops (pads in current order), switch-node copper, noisy-to-quiet distances, protection parts to connector pins, track-to-edge clearance. Choosing what to measure and the limits is your job; say where each limit comes from or mark it as an engineering estimate.
- List every clock and switcher in `emc.clocks` (frequency and source) and run `python scripts/emc_harmonics.py .`: it shows which harmonics fall in each emission band, which coincide, and the cable ports to probe first. Put that plan in the report.
- Run `python scripts/emc_rules.py .` (track over pour gaps, layer changes without a return via, unfiltered cable ports, edge, ground cover). Rate its findings with the others.
- Optional, for a person with HyperLynx, CST or SIwave: `python scripts/sim_export.py .` writes IPC-2581, ODB++ and STEP to `sim/`.
- Run `emc_geometry.py`. Rate each finding CRITICAL, HIGH, MEDIUM or LOW. CRITICAL means the board is likely to fail to work or to be unsafe as laid out.
- Controlled-impedance or fast nets (USB, Ethernet, DDR, RF): follow `high-speed.md`. State the target impedance, the fab stackup it was calculated for, and the measured length matching. If none, say "none".
- Fixes that change the schematic need the user's approval first.
- Report: findings table (id, severity, item, measured, guide), passing checks, fixes applied, limits.
- Gate: no CRITICAL finding.

## 7 BOM
- Export the BOM (reference, value, footprint, MPN, supplier number). Split it into batches of about 15 lines and run one `part-scout` per batch in parallel.
- Lines LCSC does not cover go through the hand-check flow in `suppliers.md`: you write the list with links, the user reads the numbers. Report cost in the user's currency as that file describes.
- A line passes only with stock above the build quantity and a lifecycle status that is not end-of-life, obsolete or not-recommended-for-new-designs. "Could not check" is not a pass.
- `python scripts/lifecycle_check.py .` looks up every part that has an LCSC number on LCSC's public product data (no key, one request a second, answers cached for 7 days). A discontinued part fails. A part LCSC flags but does not list as discontinued is reported as "nrnd (check)": confirm it on the manufacturer's page. Parts with no LCSC number are "unverified" with links to check by hand. This is the distributor's status, not the manufacturer's: say so in the report.
- The stock and lifecycle lines come from cheap helpers and LCSC; `gate-reviewer` checks them before the gate counts.
- You propose substitutes; the user approves them. Every substitute goes back through stage 2 (datasheet, pin table, footprint) before it is placed.
- Report: totals, table of problem lines, swaps made, lines still open.
- Gate: no end-of-life and no out-of-stock part.

- Boards with safety parts: `python scripts/parts_register.py .` lists every safety-critical part with its certificate, standard and rating. Fill the `cert`, `cert_standard` and `rating` symbol fields from the certificates; leave "unverified" where you have none.

## 8 Release
- Check that no KiCad process is rewriting the project, then run `python scripts/run_gates.py .`, then `block_check.py` again: its rows B6 and B7 compare the BOM with the placement file and check that the paste layers are not empty. It refills the zones on a copy, reruns DRC and exports from that copy.
- `08-release.md`: gate summary for all eight stages; list of files in `fab/`; **every assumption and unverified item from every stage**, as a checklist the user ticks off; proposed waivers and their approval dates; first power-up steps; the limits from the skill. If any gate is open, say so in the first line.
- Stop. Do not upload or order.
- Run `python scripts/precompliance_pack.py .` last: it collects every report into `reports/precompliance.md` for the responsible person and the test lab.
