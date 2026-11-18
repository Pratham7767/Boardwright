# Routing, EMI and high-speed rules as a machine-checkable catalogue

Research note for Boardwright, written 2026-11-17. Goal: turn routing practice into rules that a deterministic router can obey while it routes and a checker can verify afterwards. This note adds to `references/high-speed.md`, `design-practice.md`, `block-guides.md` and `high-voltage.md`, and to the checks in `emc_rules.py`, `hs_rules.py`, `impedance_check.py` and `pdn_check.py`. It does not repeat them.

## How to read this

Each rule has an id, one sentence, numbers with the condition they hold under, a type, the data it needs, and a source.

- **Type H** = hard constraint the router can enforce while it places copper. **Type C** = check afterwards on finished geometry. **H+C** = both (route to it, then prove it). **Manual** = geometry cannot decide it; a person or a simulator must.
- **Data** abbreviations: STK = stackup (layer order, dielectric heights, Er); NC = net class; IF = interface type; tr = rise time; FAB = fab capability profile; NETLIST = schematic connectivity.
- Imperial numbers are kept as the source gave them, with mm added. 1 mil = 0.0254 mm.
- "unverified" means I did not open a primary document for that number. Fully read as text: TI SPRAAR7J, SNLA387, SPRABI1D, and the KiCad 10 manual. Read as web pages: the AMD UG863 DDR4 rules page, the LearnEMC myths page, the Altium stackup and Bob Smith articles. Everything labelled "snippet" (PCIe, HDMI, MIPI, BGA, IPC-2152, Intel EMIF) is from search-result summaries only.
- A number from a vendor guide holds for that vendor's chip. The chip's own guide always overrides this catalogue.

### Source key
- [TI-HS] TI SPRAAR7J, High-Speed Interface Layout Guidelines, 2023. https://www.ti.com/lit/an/spraar7/spraar7.pdf
- [TI-ETH] TI SNLA387, Ethernet PHY PCB Design Layout Checklist, 2021. https://www.ti.com/lit/pdf/snla387
- [TI-DDR3] TI SPRABI1D, DDR3 Design Requirements for KeyStone Devices, 2022. https://www.ti.com/lit/pdf/sprabi1
- [AMD-863] AMD UG863 Versal PCB Design, Physical Design Rules for DDR4 Signals. https://docs.amd.com/r/en-US/ug863-versal-pcb-design/Physical-Design-Rules-for-DDR4-Signals
- [AMD-583] AMD UG583 UltraScale PCB Design, DDR4 chapter (only its contents page was readable; rule pages not opened). https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/PCB-Guidelines-for-DDR4-SDRAM
- [KiCad] KiCad 10 Pcbnew manual, custom design rules and constraint list. https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- [LearnEMC] Bogatin, EMC Design Myths (3W and 20H). https://www.learnemc.com/emc-design-myths
- [Altium-stk] Altium, PCB Stackup Basics. https://resources.altium.com/p/pcb-stackup-basics
- [Altium-BS] Altium, Bob Smith termination. https://resources.altium.com/p/bob-smith-termination-it-correct-ethernet
- [Altium-PCIe] https://resources.altium.com/p/pcie-layout-and-routing-guidelines (snippet)
- [Altium-XT] https://resources.altium.com/p/crosstalk-elimination-techniques-in-altium-designer (snippet)
- [TI-SNLA426] TI SNLA426, PCIe Gen3-Gen5 repeater layout, 2023. https://ti.com/lit/pdf/snla426 (snippet)
- [Intel-EMIF] Intel Agilex EMIF IP guide, 1DPC UDIMM. https://www.intel.com/content/www/us/en/docs/programmable/683216/22-2-2-6-1/one-dimm-per-channel-1dpc-for-udimm.html (snippet)
- [Intel-MIPI] https://www.intel.com/content/www/us/en/docs/programmable/817561/24-1-2-2-0/mipi-interface-layout-design-guidelines.html (snippet)
- [Intel-HDMI] Intel AN 837. https://www.intel.com/content/www/us/en/docs/programmable/683677/current/ip-board-design-tips.html (snippet)
- [ADI-HDMI] https://ez.analog.com/video/a/documents/c/hdmi-faq/DO9240/hdmi-layout-guideline (snippet)
- [JLC-BGA] https://jlcpcb.com/blog/bga-pcb-design-complete-guide-layout-and-routing-guidelines and the IPC slide deck https://www.ipc.org/system/files/technical_resource/E14%26S03-04.pdf (snippet)
- [PX-2152] Sierra Circuits, IPC-2152 article. https://www.protoexpress.com/blog/how-to-optimize-your-pcb-trace-using-ipc-2152-standard/ (snippet)
- [Cadence-MIPI] https://resources.pcb.cadence.com/blog/2024-mipi-pcb-design-guidelines-for-high-speed-interfaces-cadence (snippet)
- Plus the sources already cited in the four Boardwright references (SLYT614, AN-1229, SLVA680, SLYT512, SPRAAR7, AN2867).

### Gaps in what Boardwright already checks (from reading the scripts)
- `emc_rules.py` R1 (track over ground gap), R2 (return via), R3 (filter on cable port), R4 (fast track near edge), R5 (ground cover) are geometric and sound. Missing: reference-plane identity per layer pair, power-plane reference detection, parallel run length, spacing in multiples of H, via stubs, plane-edge setback, slot detection, stitching pitch.
- `hs_rules.py` has skew, length, gap, uncoupled, via count, return via. Missing: per-interface rule templates, stub length, AC-capacitor symmetry, test points on pairs, delay-based (ps) budgets per layer.
- `impedance_check.py` is a closed-form estimate. Missing: tolerance bands per interface and a reference-layer lookup from the stackup.
- `pdn_check.py` models the capacitor bank only; mounting loop inductance and plane pairs are not modelled.
- `high-speed.md` uses `max_return_via_mm` 1.5, a working default. TI gives 200 mil (5.08 mm) maximum, centre to centre, "closer is better" [TI-HS 2.5]. 1.5 mm is stricter than the source; keep it, labelled as a Boardwright default.

---

## 1. Stackups (ST)

The law behind all of them: each signal layer needs a solid reference plane next to it, power and ground planes sit adjacent so they couple, and fast signals prefer a ground reference over a power reference [Altium-stk; TI-HS 2.4].

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| ST-01 | Every signal layer has an adjacent plane layer of mostly solid copper. | Boardwright's R5 floor (50 percent cover) is a floor only; fast nets need solid copper along their whole length (RP-01). | C | STK | [Altium-stk]; TI-HS 2.4 |
| ST-02 | 2 layers: top for parts and signals, bottom a near-solid ground; bottom routing only in short jumps. | Suits clocks below about 50 MHz or edges slower than about 1 ns. Controlled-impedance pairs only for short USB full-speed runs. | H+C | NC, tr | design-practice.md |
| ST-03 | 4 layers: SIG-GND-GND-SIG (power as wide traces/pours on the outer layers), or SIG-GND-PWR-SIG when one rail needs a plane. | In SIG-GND-PWR-SIG the bottom layer references a power plane, so no fast nets there. L1-L2 dielectric is thin, so 50 ohm lines are narrow. | H (layer choice) | STK, NC | [Altium-stk]; TI-HS 2.4 |
| ST-04 | 6 layers: SIG-GND-SIG-PWR-GND-SIG. | L1 and L6 carry the fast pairs against L2 and L5. L3 sits between GND and PWR: use it for ground-referenced mid-speed nets only, and route L3 against L2 first. | H | STK | [Altium-stk]; reading of the order is mine |
| ST-05 | 8 layers: SIG-GND-SIG-PWR-GND-SIG-GND-SIG. | L6 sits between two grounds (L5, L7), so it is the clean stripline layer for the most critical buried pair. L3 sits between GND and PWR like L3 in ST-04. | H | STK | [Altium-stk] (order); L3/L6 analysis is mine |
| ST-06 | 10+ layers: keep the same pattern. Each signal layer has a ground on at least one side, buried fast layers have ground on both sides, power planes sit next to ground. | The article has no 10-layer order; any 10-layer template here is unverified and should be confirmed with a solver and the fab. | Manual | STK | unverified |
| ST-07 | Planes that do not reference each other must not overlap over large areas. | Overlapping analog and digital power planes form capacitance that passes RF between them (TI Figure 2-10). | C | STK, zones | TI-HS 2.4 |
| ST-08 | Use the fab's own stackup and calculator for impedance. | Record stackup name, dielectric heights, Er, date (already in high-speed.md). | C | STK, FAB | high-speed.md |
| ST-09 | DDR boards: at least 4 routing layers (two address/command, two data); likely 8 total; data on layers near the memory side; long runs on stripline. | TI KeyStone DDR3 guide: 8 layers if area allows, 12 or more for high-performance boards. | Manual / H (layers) | STK, IF | TI-DDR3 6.3 |
| ST-10 | USB 3 / PCIe / HDMI boards: TI recommends at least 6 layers, and microstrip with an adjacent GND (no stripline) for the fast pairs. | Reason: no vias, no stubs. Contradicts the DDR3 advice (stripline for long runs): the interface vendor decides. | H | STK, IF | TI-HS 3.x |

Engine rule: the stackup is a required input. Without it, STK-dependent rules return "cannot evaluate", never "pass".

---

## 2. Return paths (RP)

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| RP-01 | A fast trace stays over solid reference copper along its whole length: no splits, voids or slots under it. | Applies to differential pairs of listed interfaces, clocks, and nets with edge under about 1 ns. Same as R1 in `emc_rules.py`. | H+C | STK, NC | TI-HS 2.4; emc_rules.py |
| RP-02 | Keep a fast trace at least 1.5 x its width away from any void in the reference plane. | Not applied at the deliberate void under an SMD pad on the pair. | H+C | NC width | TI-HS 3.x |
| RP-03 | Keep high-speed pairs at least 90 mil (2.3 mm) from the edge of the reference plane. | "Plane edge" = boundary of the reference copper, not the board edge. | H+C | zone outline | TI-HS 3.x |
| RP-04 | A layer change that keeps the same ground reference gets a ground via beside the signal via. | TI: stitching vias symmetric, within 200 mil (5.08 mm) centre to centre, closer is better. Boardwright default 1.5 mm. | H+C | NC | TI-HS 2.5; hs_rules.py |
| RP-05 | A change between two ground planes ties both grounds with vias next to the signal via. | Same 200 mil limit; one via at least, one each side for a pair. | H+C | STK | TI-HS 2.5 |
| RP-06 | Avoid a reference change from GND to a power plane. If unavoidable, put a stitching capacitor at the crossing. | Capacitor 1 uF or lower, as close as possible. TI does not recommend power-plane references for high-speed signals. | C (flag) | STK | TI-HS 2.4 |
| RP-07 | Crossing a plane split is a last resort; stitch with capacitors at the crossing. | Forbid in the router; allow only by an explicit waiver listed for the user. | H | zones | TI-HS 2.4 |
| RP-08 | No test points, stubs or probe pads on high-speed pairs. | USB test points allowed: 0; stubs allowed: 0. | H+C | NC, NETLIST | TI-HS 3.x, Table A-1 |
| RP-09 | Guard traces help only when tied to ground by closely spaced vias, and are an opt-in, not a default. | One vendor guide claims 10-20 dB extra isolation if stitched at lambda/20 or closer, and that an unstitched guard can raise coupling. An Altium author warns that stitching vias between coupled traces can create a resonant cavity, and that moving ground closer (thinner dielectric) does the same job. | Manual | tr, STK | [Altium-XT] snippet; lambda/20 claim unverified |
| RP-10 | Do not run fast traces across a gap between two ground pours that connect only far away. | Check that the reference zone is connected within a set radius of the trace. | C | zones | new check (emc_rules R1 covers voids only) |

Engine note: RP-01 to RP-03 need the filled zone polygon of the reference layer. `emc_rules.py` already refills zones in memory. KiCad's DRC does not know about reference planes.

---

## 3. Crosstalk and spacing (XT)

The 3W rule says "edge-to-edge spacing of three trace widths". Its basis is weak. Bogatin: none of the three coupling mechanisms depends strongly on trace width, coupling depends on spacing relative to the height above the plane, so a rule in H is more defensible, and acceptable crosstalk depends on the application [LearnEMC]. Vendor guides still use width multiples. The catalogue stores spacing as a number plus its basis (W or H), and the engine takes the larger of the width-based and height-based results.

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| XT-01 | Pair to pair: at least 5W spacing. | TI's example: 6 mil width gives 30 mil spacing. For USB 3 / SATA / PCIe / HDMI / SGMII / CSI pairs. | H+C | NC width, IF | TI-HS 3.1 |
| XT-02 | Other signals stay 30 mil (0.76 mm) from a fast pair along its whole length; 50 mil (1.27 mm) from clocks or periodic signals. | Same document; the default fast-pair keep-out. | H+C | NC | TI-HS 3.1, Table A-1 |
| XT-03 | DDR3: centre-to-centre spacing at least 5W including serpentines; 4W only at or below 1066 MT/s; foreign signals in the DDR channel at least 6W away. | Foreign nets there must not reference the DDR I/O power plane. | H+C | NC width, IF | TI-DDR3 6.3.1.3 |
| XT-04 | DDR4 spacing in H (distance to nearest ground plane). CAC to CAC: 2H general, 1H under the SoC, 1.5H under the DRAM. CAC to clock and CAC to data: 5H general, 2H in breakout. Data/strobe in one byte: 2H general. Data to other bytes: 5H. Between memory interfaces: 5H. | AMD Versal. The relaxed values apply only inside the BGA breakout; the engine needs a breakout polygon (BGA courtyard plus margin). | H+C | STK (H), IF | [AMD-863] |
| XT-05 | Default for unclassified fast nets: spacing at least 3 x H. | design-practice.md example: 0.11 mm dielectric gives at least 0.33 mm. Replace by an interface rule when one exists. | H+C | STK | design-practice.md; basis [LearnEMC] |
| XT-06 | Parallel run limit. I found no vendor mm limit. Use a budget: limit the parallel run so the estimated crosstalk stays under the receiver margin. | Backward crosstalk saturates once the coupled length exceeds about half the rise-time length (tr x v / 2), so the budget matters for long coupled runs on clocks and forward crosstalk. Needs tr and the stackup. | C | tr, STK | physics; unverified |
| XT-07 | Aggressor / victim classes: AGGRESSOR (clocks, switch nodes, fast edges), VICTIM (analog inputs, references, crystals, feedback, ADC), NEUTRAL. AGGRESSOR-VICTIM spacing is larger than within a class. | Suggested defaults: AGGRESSOR-VICTIM at least 5H or the interface rule, whichever is larger; NEUTRAL 3H. Boardwright defaults, not from a standard. | H+C | NC | proposal; consistent with TI-HS 3.1 |
| XT-08 | Adjacent signal layers with no plane between them route at 90 degrees to each other. | | H | STK | TI-HS (stackup figure note) |
| XT-09 | Fast pairs stay clear of crystals, oscillators, clock generators, switching regulators, mounting holes and magnetics. | TI gives no distance. A Boardwright default (3 mm) is unverified. | H+C | placement | TI-HS 3.x |

---

## 4. Impedance and widths (IM)

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| IM-01 | Single-ended controlled traces: 50 ohm. DDR3: +/-5%. DDR4 Versal: +/-10%, up to 60 ohm allowed under the SoC or DRAM. | Point-to-point and fly-by address, command and data. | C | STK, NC | TI-DDR3 6.3; [AMD-863] |
| IM-02 | USB 2.0 pair: 90 ohm differential, 81-99 ohm; common mode 40.5-49.5 ohm. | TI Table A-1 (AM335x). The USB spec tolerance itself was not opened. | C | STK, NC | TI-HS Table A-1 |
| IM-03 | USB 3: 90 ohm. PCIe: 85 ohm typical. SATA, HDMI, SGMII, MIPI: 100 ohm. | Take the chip guide. PCIe 85 vs 100 differs by generation and guide (snippet, unverified). | C | IF, STK | TI-HS Appendix A; [Altium-PCIe] |
| IM-04 | Ethernet MDI: 100 ohm differential +/-10%. RGMII / MII single-ended 50 ohm +/-10%. | | C | IF | TI-ETH |
| IM-05 | DDR clock and strobe pairs: DDR3 TI 100 ohm +/-5%; DDR4 Versal 90 ohm +/-10%. | Different vendors, different numbers: use the SoC guide. | C | IF | TI-DDR3; [AMD-863] |
| IM-06 | MIPI D-PHY: 100 ohm differential; tolerance +/-10 to 20% depending on source. | Snippets only. | C | IF | [Cadence-MIPI]; [Intel-MIPI] |
| IM-07 | Width comes from the stackup. Closed forms (Hammerstad-Jensen microstrip, IPC-2141A stripline and coupled pairs) are in `impedance_check.py`; typical error 5-10% against a solver. The fab's calculator sets production width. | | C | STK | impedance_check.py |
| IM-08 | Constant width after the BGA escape. Width steps only inside a neck-down zone. | KiCad's "BGA neckdown" example relaxes track width and clearance inside a courtyard. | H+C | NC | TI-HS 3.x; [KiCad] |
| IM-09 | Same-layer ground pour next to a controlled trace stays at least 3 x w away, preferably 5 x w. | TI Ethernet note. For coplanar-waveguide designs the gap is part of the impedance calculation instead. | H+C | NC width | TI-ETH |
| IM-10 | Tolerance chain: ordered impedance control from the fab typically gives about +/-10%. Without it expect worse. | Unverified; fab dependent. Put it in the release checklist. | Manual | FAB | high-speed.md |
| IM-11 | Gap constant along the coupled length; uncoupled length short. | No universal number. KiCad `diff_pair_uncoupled` enforces a maximum. | H+C | NC | [KiCad]; hs_rules.py |

---

## 5. Interface rules (IF)

Numbers are for the named vendor chips or families. Mil values are given with the source; convert to mm for the DRC file.

### 5.1 USB 2.0
| Id | Rule | Numbers | Type | Source |
|---|---|---|---|---|
| IF-USB2-1 | Pair routed together, symmetric, same layer, over unbroken ground. | 90 ohm differential. | H+C | TI-HS 3.3, Table A-1 |
| IF-USB2-2 | Intra-pair skew at most 50 mil (1.27 mm). | TI AM335x / AM57xx tables: typical 45, max 50. Other chips differ; Boardwright's example in high-speed.md uses a tighter 0.15 mm. | C | TI-HS Table A-1 |
| IF-USB2-3 | Total length 4000-12000 mil (102-305 mm) per TI; chip specific. | | C | TI-HS Table A-1 |
| IF-USB2-4 | Stubs 0; test points 0; vias at most 4 per line (TI). Boardwright's default of 2 is stricter. | | H+C | TI-HS Table A-1 |
| IF-USB2-5 | Spacing 50 mil to clocks, 30 mil to any other signal. | | H+C | TI-HS Table A-1 |
| IF-USB2-6 | ESD diode between connector and everything else; use a flow-through footprint so the pair stays straight. | TI draws an 8 mm dimension in Figure 3-11; no hard limit stated. | H+C | TI-HS 3.13 |
| IF-USB2-7 | Through-hole Type A receptacle: bring the pair in on the top layer so the pin is not a stub. | | H | TI-HS 3.x |

### 5.2 USB 3.x
| Id | Rule | Numbers | Type | Source |
|---|---|---|---|---|
| IF-USB3-1 | 90 ohm differential; intra-pair skew 5 mil (0.127 mm); microstrip over ground. | | C | TI-HS Appendix A |
| IF-USB3-2 | At most 2 vias per differential line (TI tables); equal count in both members. | | H+C | TI-HS Appendix A, 3.9 |
| IF-USB3-3 | Via stub under 15 mil (0.38 mm); back-drill longer stubs. | Applies equally to PCIe, SATA, HDMI. A congatec note for USB 3.2 Gen 2 says under 10 mil (snippet, unverified). | C | TI-HS 3.6, 3.7 |
| IF-USB3-4 | AC capacitors on TX: 0603 at most, 0402 or smaller preferred; symmetric; void the plane under the pads 100%, at least two layers deep. | | H+C | TI-HS 3.10 |
| IF-USB3-5 | Via anti-pad as large as possible (30 mil example) on every layer; no unused via pads. | Needs fab check. | H | TI-HS 3.8 |
| IF-USB3-6 | Pair to pair 5W (30 mil minimum); 50 mil from USB 2.0 and clocks. | | H+C | TI-HS 3.1 |
| IF-USB3-7 | Common-mode filter no-stuff option: 0402 zero-ohm resistors, with any layer-transition via next to the filter. | | H | TI-HS 3.x |

### 5.3 Ethernet
| Id | Rule | Numbers | Type | Source |
|---|---|---|---|---|
| IF-ETH-1 | MDI pairs 100 ohm +/-10%; PHY to magnetics under 2 in (50.8 mm); intra-pair match 20 mil for 1G, 50 mil for 10/100. | | C | TI-ETH |
| IF-ETH-2 | MII / RMII / RGMII: 50 ohm single-ended; under 6 in (152 mm); matched 20 mil (1G), 50 mil (10/100). | | C | TI-ETH |
| IF-ETH-3 | Ground continuous under the MDI traces; void only under magnetics, chokes, AC-coupling capacitors and ESD diodes. Two-layer void for standard designs, all-layer for automotive; void edge about 20 mil from the part edge. | | C | TI-ETH |
| IF-ETH-4 | Pairs at least 30 mil apart; ground vias beside signal vias. | | H+C | TI-ETH |
| IF-ETH-5 | Earth / chassis ground at least 20 mil from board ground on all layers; join with a capacitor and a resistor of 1 Mohm or more. | Mains products: the isolation distance (section 9) replaces 20 mil. | H+C | TI-ETH |
| IF-ETH-6 | ESD part position: one TI note puts it at the connector side, the Ethernet note puts it on the PHY side of the magnetics (to survive common-mode swings). TI itself reports the contradiction. Follow the PHY vendor's reference design. | | Manual | TI-ETH |
| IF-ETH-7 | Bob Smith termination: four 75 ohm resistors (two for RX, two for TX) and a capacitor of 1-4.7 nF to a ground point; one proposal uses 52.3 ohm. Ground point (chassis to analog ground) and whether to use it are debated. | Rated voltage of the capacitor was not found. Take network from the PHY and magnetics datasheets. | Manual | [Altium-BS] |
| IF-ETH-8 | Magnetics close to the RJ45 with the connector-side copper kept clear of PHY-side copper. | Distance numbers found (5 mm, 25 mm) came from non-primary pages: unverified. | H+C | unverified |

### 5.4 PCIe Gen 1-5
All snippet-level, so unverified at the primary document. The PCIe Base and CEM specs are PCI-SIG member documents (gated). Use the chipset or retimer vendor's public guide.

| Id | Rule | Numbers | Type | Source |
|---|---|---|---|---|
| IF-PCIE-1 | 85 ohm differential, +/-10-15% by generation and guide. | | C | [Altium-PCIe] |
| IF-PCIE-2 | Intra-pair skew at most 5 mil (a Gen4 mux note). Lane-to-lane matching is not required as the clock is embedded; adding meanders costs margin. | | C | [TI-SNLA426] |
| IF-PCIE-3 | TX AC capacitors 75-220 nF (spec range 176-265 nF cited by one source), 0402 or smaller, symmetric, plane void under the pads. Placement (near the transmitter or the receiver) differs by source: follow the device guide. | | H+C | [TI-SNLA426]; TI-HS 3.10 |
| IF-PCIE-4 | Vias: 2 per trace (TI example); stub under 15 mil; back-drill longer stubs; Gen5 on thick boards typically needs back-drill or blind/buried vias. | | H+C | TI-HS 3.6, 3.7; [TI-SNLA426] |
| IF-PCIE-5 | Insertion-loss budget in dB at Nyquist, chip specific. Needs a channel model, not geometry. | | Manual | [TI-SNLA426] |
| IF-PCIE-6 | Total length 4000-5500 mil on TI Sitara tables; chip specific. | | C | TI-HS Appendix A |

### 5.5 DDR3 / DDR4 / LPDDR
| Id | Rule | Numbers | Type | Source |
|---|---|---|---|---|
| IF-DDR-1 | Fly-by for address, command, control and clock. Stubs on those groups under 80 mil (2.0 mm); clock stubs under 40 mil (1.0 mm). Data is point-to-point, no VTT, no mid-point vias. | DDR3 on TI KeyStone. | H+C | TI-DDR3 6.3 |
| IF-DDR-2 | Address / command / control matched to the clock at each SDRAM within +/-20 mil (0.51 mm); stub skew +/-10 mil; same via count in each matched segment. | | C | TI-DDR3 6.3 |
| IF-DDR-3 | Byte lane: strobe pair to strobe pair +/-1 mil; data bits within a lane +/-10 mil. Data bits may swap within a lane; address lines may not swap. | | C | TI-DDR3 6.3 |
| IF-DDR-4 | All nets of a byte lane on the same layer; at most 2 vias, equal count. | | H+C | TI-DDR3 6.3 |
| IF-DDR-5 | Clock pairs: 100 ohm +/-5%, members matched within 1 mil, same via count per segment. | | C | TI-DDR3 6.3 |
| IF-DDR-6 | Vref: trace at least 30 mil (0.76 mm) wide; 15 mil (0.38 mm) from other nets; decoupled at each SDRAM pin (10 nF and 100 nF); on the top layer. | | H+C | TI-DDR3 6.3.1.8 |
| IF-DDR-7 | No plane splits under DDR routes; no foreign signals in the DDR channel. | | H+C | TI-DDR3 6.3.1.3 |
| IF-DDR-8 | DDR4 (AMD Versal): max length 11000 mil for command/address/control, 5500 mil for data and strobe. Vias: (2 x devices) + 2 for CAC and clock, 2 for data. CAC on at most two internal layers; each data byte on at most one. | | C | [AMD-863] |
| IF-DDR-9 | Intel Agilex EMIF, DDR4 UDIMM: address and command matched to the clock within +/-20 ps per memory component; for a DIMM the clock is matched up to the connector. | Snippet. | C | [Intel-EMIF] |
| IF-DDR-10 | Store matching budgets in ps and convert with per-layer delay (microstrip and stripline differ). TI matches to "equivalent stripline length". | | C | TI-DDR3 6.3 |
| IF-DDR-11 | LPDDR3/4/5 and DDR5: no verified document in this session. Classes (CK, CA, DQ/DQS) are the same; numbers come from the SoC vendor, often under NDA, or a JEDEC member standard. | | Manual | unverified |

KiCad's `skew` constraint measures against the longest net in the matched set. It cannot say "within X of the clock at each SDRAM"; that needs `fromTo()` paths [KiCad].

### 5.6 MIPI CSI-2 / DSI (D-PHY), snippets only
- IF-MIPI-1: 100 ohm differential (+/-10 to 20% by source) [Cadence-MIPI; Intel-MIPI].
- IF-MIPI-2: intra-pair skew at most 5 mil; lane to clock within 50 mil [Cadence-MIPI; Intel-MIPI].
- IF-MIPI-3: no series stubs, group lanes on one layer where possible; ground rules as USB 3. MIPI specs are member-gated.

### 5.7 HDMI / TMDS, snippets only
- IF-HDMI-1: 100 ohm differential; +/-5% [ADI-HDMI] or +/-10% [Intel-HDMI].
- IF-HDMI-2: intra-pair skew about 5 mil for HDMI 2.0 TMDS and 3 mil for FRL; inter-pair about 3 mm. The 200 mil inter-pair figure I was asked to check was not found.
- IF-HDMI-3: ESD array close to the connector (one source: within 10 mm, unverified); remove ground under ESD and pull-up pads; TMDS on the top layer, no vias [Intel-HDMI].
- IF-HDMI-4: low-EMI four-layer order TMDS-GND-PWR-control (TI, snippet).

### 5.8 SPI, I2C, clocks
- IF-SPI-1: no universal routing numbers exist in the documents opened. A trace is electrically long when its delay exceeds roughly one sixth of the rise time (rule of thumb, unverified); then add series termination at the driver. This needs tr and length: a check, not a geometry rule.
- IF-I2C-1: pull-up bounds are already in block-guides.md (SLVA689). Keep SDA and SCL together, away from switching nodes.
- IF-CLK-1: clocks: shortest path, series damping at the source, no vias on crystal nets, ground around (block-guides.md; AN2867).

### 5.9 NDA and gated documents
Gated or NDA: Intel client platform design guides (DDR4/DDR5 UDIMM and SO-DIMM), JEDEC full standards, MIPI specifications, PCI-SIG CEM and base specs, the HDMI spec, USB-IF compliance documents, many SoC hardware design guides (NXP i.MX 8 family guides were found only as community-hosted copies). Public in this session: TI, AMD UG863 and UG583, Intel FPGA user guides. The engine stores `source` and `nda: true` per number.

---

## 6. Vias (VIA)

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| VIA-01 | Via stub on fast nets under 15 mil (0.38 mm). | Stub = barrel beyond the last connected layer. L1 to L2 has none; L1 to L4 in a 6-layer board leaves L5-L6 as stub. The router picks layer pairs to make the stub zero. | H+C | STK | TI-HS 3.6 |
| VIA-02 | Back-drill longer stubs: use a bit slightly larger than the via drill. | The residual stub the fab leaves is fab specific (unverified). Release checklist item. | Manual | FAB | TI-HS 3.7 |
| VIA-03 | Equal via count in each pair member and each matched segment; evenly spaced; close to the SoC. | | H+C | NC | TI-HS 3.9 |
| VIA-04 | Via limits: USB 2.0 at most 4 (TI table); USB 3 and PCIe at most 2; DDR3 data at most 2; DDR4 CAC (2 x devices) + 2, data 2. | KiCad `via_count`. | H+C | IF | TI-HS App. A; TI-DDR3; [AMD-863] |
| VIA-05 | Anti-pad as large as possible (30 mil example) on every layer the via crosses. | | H | FAB | TI-HS 3.8 |
| VIA-06 | Ground via beside each signal via. | See RP-04. | H+C | NC | TI-HS 2.5 |
| VIA-07 | Default via 0.3 mm drill, 0.7 mm pad unless the fab or a BGA needs smaller. | | H | FAB | design-practice.md |
| VIA-08 | BGA fanout by pitch (examples only). 0.8 mm: dog-bone with through vias (ball pad 0.4, via pad 0.45, hole 0.2 mm, 0.125 mm track, 0.1 mm space). 0.65 mm: dog-bone outer rows, via-in-pad inner rows (some say via-in-pad throughout). 0.5 mm: via-in-pad with laser microvia (example hole 0.15, pad 0.275, 0.075 track/space) or HDI. 0.4 mm: via-in-pad, often stacked microvias. | Sources disagree at 0.65 mm. The fab capability profile decides. | H | FAB, pitch | [JLC-BGA] snippet, unverified |
| VIA-09 | Via-in-pad must be filled and capped, or solder wicks into the barrel. | Adds a fab line item. | Manual | FAB | [JLC-BGA] snippet |
| VIA-10 | Microvia aspect ratio around 0.75-1:1; staggered is more reliable than stacked. | Typical fab statements; unverified. | H | FAB | unverified |
| VIA-11 | Remove non-functional inner pads on fast signal vias. | | H | FAB | TI-HS 3.8 |

---

## 7. Power (PW)

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| PW-01 | Trace width from current. IPC-2221: I = k x dT^0.44 x A^0.725 (A in square mil), k = 0.048 external, 0.024 internal. IPC-2152 replaces it with measured charts. | IPC-2152 found internal traces carry much closer to external values than IPC-2221 predicted; nearby planes raise capacity (one source: about 40%, unverified). Vendor table: about 45 mil for 5 A on 1 oz external copper at 20 C rise (rough). Engine: use IPC-2221 as the safe lower bound and flag final sizing to IPC-2152. | H (min width) + C | copper weight, dT, layer | [PX-2152] snippet; constants from a secondary page; unverified at the standard |
| PW-02 | Minimum width per power net class derived from the budget current. | Example project already has a `power_min_width` DRU rule. | H | NC | [KiCad] |
| PW-03 | Check pad-to-zone connection width as well as track width. | KiCad `connection_width`. | C | NC | [KiCad] |
| PW-04 | About one via per amp where vias are unavoidable in a power path. | | H+C | current | block-guides.md (SLYT614) |
| PW-05 | Do not split planes under fast signals; keep unrelated power planes from overlapping. | | C | zones | TI-HS 2.4 |
| PW-06 | Decoupling loop: capacitor next to the pin; power and ground vias next to each other; short wide connections. | No distance limit in any document opened (block-guides.md lists cap-to-pin mm as not confirmed). The 1 nH per mm trace figure is a common rule of thumb, unverified. Use a computed budget: loop L from length and via drop, tested against the target impedance. | H (placement) + C | NETLIST, STK | block-guides.md; pdn_check.py |
| PW-07 | PDN target impedance Z = V x ripple / I_step up to f_max. | Already in `pdn_check.py`. Add mounting inductance per capacitor (pad trace + via + plane spreading, which depends on the dielectric to the plane). | C | rail data, STK | pdn_check.py |
| PW-08 | Thin dielectric between the power and ground plane pair (about 4 mil or less) lowers plane inductance. | Practice; unverified at a primary source. | H (stackup) | STK | [Altium-stk] |
| PW-09 | Reference and bias nets wide (at least 30 mil in the DDR example), 15 mil from other nets, decoupled at the load. | | H+C | IF | TI-DDR3 6.3.1.8 |

---

## 8. EMI / EMC routing (EM)

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| EM-01 | Minimise loop area between a signal and its return. Signal and return stay on adjacent layers or on the same layer with ground pour. | No numeric limit. Report the estimated area for switching, clock and ESD paths (`emc_geometry.py` has hot-loop rows). | C | NETLIST | block-guides.md |
| EM-02 | Fast clock and edge nets stay away from cables, connectors and enclosure seams; route on inner or ground-adjacent layers; short. | | H+C | NC | TI-HS 3.x |
| EM-03 | Edge rule. The "20H rule" (pull the power plane back 20 x dielectric height from the ground plane edge) is disputed: Bogatin says no data supports it, that it is more likely to cause a problem than prevent one, and that a power plane sandwiched between well-stitched grounds has negligible edge emission. Keeping fast traces and planes away from the edge can still limit near-field coupling. | Boardwright default (R4): fast tracks at least 1.0 mm from the edge, a working value. Prefer ground stitching at the edge over 20H. | C | NC | [LearnEMC] |
| EM-04 | Stitch ground planes around the board edge and across large areas. | Pitch from the highest significant frequency: lambda/20 in the board dielectric (for 1 GHz in FR-4 roughly 7-8 mm; at 100 MHz about 75 mm). Guides give lambda/10 to lambda/20 (snippets, unverified). Default: 5 mm near connectors and the edge, 10-15 mm elsewhere, unless a faster band is declared. | C | tr or f_max | [Altium-XT] snippet; unverified |
| EM-05 | No slots in a reference plane, and no rows of vias or holes whose antipads merge into a slot. | Through-hole connector pins and via fences are the usual cause. | C | zones | design-practice.md; TI-HS 2.4 |
| EM-06 | Every net leaving the board is protected or filtered (R3). Order from the connector: ESD part, filter, chip. TVS ground via at the pad. | | H (order) + C | NC | block-guides.md; emc_rules.py |
| EM-07 | Cable shield and connector shell go to chassis ground by a low-inductance path with several vias, not through a long signal-return trace. A capacitor plus high-value resistor may separate chassis and signal ground (Ethernet). | The USB-C shield tie is listed "not confirmed" in block-guides.md. | Manual | | TI-ETH |
| EM-08 | Switching converter hot loop: input capacitor, switch and diode/low-side form the loop; minimise its area; input capacitor close to the IC with no vias in the path; small switch-node copper; feedback away from the inductor. | Numbers are datasheet specific. | H (placement) + C | NETLIST | block-guides.md (SLYT614, AN-1229) |
| EM-09 | Common-mode choke after the ESD part at the connector; route the pair symmetrically through it; void the plane under its pads per the vendor. | | H+C | NC | TI-ETH; TI-HS |
| EM-10 | ESD path from connector to TVS to ground to chassis is short and wide and crosses no sensitive circuit; no unprotected trace in the connector-to-TVS area. | | H+C | NETLIST | block-guides.md (SLVA680) |
| EM-11 | One continuous ground; partition analog and digital by placement. If a split exists, bridge once and route every crossing over the bridge. | | H+C | zones | block-guides.md (SLYT512) |
| EM-12 | Clock routing: shortest route, series damping at the source, ground around, harmonic budget from the edge rate. | See `emc_harmonics.py`. | H+C | tr, f | block-guides.md |

---

## 9. Mains and hazardous voltage (MV)

Clearance and creepage tables, material groups, barrier definitions and DRC generation already exist in `high-voltage.md`, `creepage_rules.py`, `barrier_check.py` and `spacing_tables.json`. Not repeated here. Routing-specific points only:

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| MV-01 | The required distances are hard clearances between domains, in the XY plane and across layers: primary copper over secondary copper on the next layer is a path through the laminate. Forbid XY overlap of barrier domains unless the dielectric rating is documented. | | H+C | safety section | high-voltage.md |
| MV-02 | A routed slot adds creepage only if it is wide enough. IEC 60664-1 uses a minimum groove width of about 0.25 mm (pollution degree 1), 1.0 mm (PD 2), 1.5 mm (PD 3). A narrower slot does not shorten the path. | From memory of IEC 60664-1; not re-opened. Verify before use. | C | safety section, Edge.Cuts | unverified |
| MV-03 | No copper pour on the primary side, none inside the isolation distance. | | H+C | | high-voltage.md |
| MV-04 | Creepage runs along the surface, around pads and mask openings; tracks between pins of a part that straddles a barrier must still meet the distance. | | C | | high-voltage.md |
| MV-05 | Hand-route mains, bus, switch node, clamp, feedback; no autorouter. | | H | | high-voltage.md |
| MV-06 | Barrier-crossing parts (optocoupler, transformer): keep tracks perpendicular to the barrier and away from the gap edge. | | H+C | | creepage_rules.py |
| MV-07 | Mounting holes and standoffs are conductors: keep creepage to them or tie them to one domain. | KiCad `hole_clearance`, `creepage`. | H+C | | high-voltage.md |
| MV-08 | Ethernet and USB on a mains product: the 20 mil earth gap (IF-ETH-5) is not enough; use the barrier distance. | | C | | high-voltage.md; TI-ETH |
| MV-09 | Coating, potting or mask coverage can change the applicable distances: release checklist item. | | Manual | | high-voltage.md |

---

## 10. Manufacturing rules that affect routing (MF)

None of these numbers came from a primary standard in this session. The fab capability profile (`fab_profiles.json`) is the real source and wins.

| Id | Rule | Numbers and condition | Type | Data | Source |
|---|---|---|---|---|---|
| MF-01 | No acute angles. Use 45 degree bends or arcs. | KiCad `track_angle` checks the angle between connected segments. The angle limit (90 degrees) is typical practice, unverified. | H+C | | [KiCad]; limit unverified |
| MF-02 | Acid traps: avoid sharp internal angles where a track meets a pad or track at under 90 degrees. | Same constraint as MF-01. | C | | unverified |
| MF-03 | Teardrops where a track is much narrower than the pad or via, mainly small vias and rigid-flex. | KiCad has a built-in teardrop feature. | H | | unverified |
| MF-04 | Annular ring above the fab minimum after drill tolerance. | Often 0.075-0.15 mm. From the fab profile. | C | FAB | fab_profiles.json |
| MF-05 | Copper to board edge above the fab minimum (often 0.25-0.5 mm; more for V-score). | KiCad `edge_clearance`. | H+C | FAB | [KiCad] |
| MF-06 | Hole to hole minimum between drilled holes (protects the drill). | KiCad `hole_to_hole`. | C | FAB | [KiCad] |
| MF-07 | Minimum track, space, drill and via size from the fab profile; relax only inside BGA courtyards. | | H | FAB | [KiCad] |
| MF-08 | Thermal relief: enough spokes. | KiCad `min_resolved_spokes`. | C | | [KiCad] |
| MF-09 | Silk and mask clearances from the fab profile. | KiCad `silk_clearance`, `solder_mask_expansion`. | C | FAB | [KiCad] |

---

## 11. Encoding as KiCad rules and router constraints

### 11.1 What the KiCad 10 rule language can express
Constraint types listed in the manual [KiCad]: `annular_width`, `assertion`, `bridged_mask`, `clearance`, `connection_width`, `courtyard_clearance`, `creepage`, `diff_pair_gap`, `diff_pair_uncoupled`, `disallow`, `edge_clearance`, `hole_clearance`, `hole_size`, `hole_to_hole`, `length`, `min_resolved_spokes`, `physical_clearance`, `physical_hole_clearance`, `silk_clearance`, `skew` (with `within_diff_pairs`), `solder_mask_expansion`, `solder_paste_*`, `text_height`, `text_thickness`, `thermal_relief_gap`, `thermal_spoke_width`, `track_angle`, `track_segment_length`, `track_width`, `via_count`, `via_dangling`, `via_diameter`, `zone_connection`. Conditions can use `A.hasNetclass('X')`, `A.NetClass`, `A.Type`, `A.Layer`, `A.inDiffPair('/USB*')`, `AB.isCoupledDiffPair()`, `A.intersectsArea('name')`, `A.intersectsCourtyard('U3')`, `A.memberOfFootprint('J*')`, `A.fromTo('U1-A*','U2-B*')`, `A.enclosedByArea()`. A rule may carry `(layer outer)` and `(severity ignore|warning|error)`. Note `physical_clearance` and `enclosedByArea` are slow.

Examples. Syntax follows the manual's own examples; values are the sourced numbers above, and the composed conditions should be tested with Board Setup's "Check Rule Syntax" before use.

```
(version 1)

# XT-02: other signals 30 mil from a USB 2.0 pair (TI-HS Table A-1)
(rule "usb2_keepout_signals"
  (constraint clearance (min 0.762mm))
  (condition "A.hasNetclass('USB') && !B.hasNetclass('USB') && B.Type == 'Track'"))

# XT-02: 50 mil to clocks
(rule "usb2_keepout_clock"
  (constraint clearance (min 1.27mm))
  (condition "A.hasNetclass('USB') && B.hasNetclass('Clock')"))

# IF-USB2-2: skew inside each pair
(rule "usb2_skew"
  (constraint skew (max 1.27mm) (within_diff_pairs))
  (condition "A.inDiffPair('/USB_D*')"))

# VIA-04: via count per net
(rule "usb2_vias"
  (constraint via_count (max 4))
  (condition "A.hasNetclass('USB')"))

# IF-DDR-6: Vref width
(rule "ddr_vref_width"
  (constraint track_width (min 0.762mm))
  (condition "A.hasNetclass('DDR_VREF')"))

# MF-01: no acute bends
(rule "no_acute_angles"
  (constraint track_angle (min 90deg)))

# EM-03 default: fast tracks away from the edge
(rule "fast_edge_keepout"
  (constraint edge_clearance (min 1.0mm))
  (condition "A.hasNetclass('Fast')"))

# RP-03 / XT-09: a drawn rule area keeps fast nets out
(rule "no_fast_in_keepout"
  (constraint disallow track via)
  (condition "A.hasNetclass('Fast') && A.intersectsArea('fast_keepout')"))

# IM-08: neck-down only inside the BGA courtyard
(rule "bga_neckdown"
  (constraint track_width (min 0.075mm) (opt 0.1mm))
  (constraint clearance (min 0.075mm))
  (condition "A.intersectsCourtyard('U3')"))

# DDR data skew across fromTo paths (from the manual's pattern)
(rule "ddr_dq_skew"
  (condition "A.fromTo('U1-A*', 'U2-B*')")
  (constraint skew (max 0.254mm)))

# Larger clearance from differential pairs to anything else (manual example)
(rule "pair_to_other"
  (condition "A.inDiffPair('*') && !AB.isCoupledDiffPair()")
  (constraint clearance (min 0.762mm)))
```

Practical notes:
- `hs_rules.py --write` already writes skew, length, gap and uncoupled rules between marker lines. Extend that generator with per-interface templates instead of hand-editing the `.kicad_dru`.
- KiCad applies the larger of the net-class clearance and the rule value, so a rule raises a clearance but cannot lower one without an explicit relaxation rule in a courtyard or area.
- Never use `(severity ignore)` to make a check pass; list proposed waivers for the user.

### 11.2 Router constraints (what the engine enforces before DRC)
1. Layer per net class from the stackup (ST-03 to ST-10): fast classes only on layers next to ground.
2. Width and gap per class from the stackup solver (IM-01 to IM-11); width constant; neck-down only inside a BGA courtyard.
3. Clearance matrix by class pair, with a floor in H multiples (XT-04, XT-05) and the aggressor/victim table (XT-07).
4. Forbidden regions: plane voids and plane-edge setback (RP-02, RP-03), board-edge setback (EM-03), keep-outs near crystals, regulators and mounting holes (XT-09).
5. Via policy per class: layer pairs that leave no stub (VIA-01), maximum count (VIA-04), equal count within a pair (VIA-03), a ground via within the return distance (RP-04).
6. Length and skew budgets in ps with per-layer delay (IF-DDR-10). Meanders only in allowed regions, spacing at least 3 x amplitude (a common serpentine rule, unverified).
7. Topology: fly-by order, stub limit (IF-DDR-1), no stubs on pairs (RP-08).
8. Placement order at connectors: connector, ESD, choke, chip (EM-06, EM-09).

### 11.3 What geometry alone cannot decide
- Whether the fab's built stackup (dielectric thickness, Er, etch factor) matches the calculation (IM-07, IM-10). Needs the fab's stackup and ideally a test coupon.
- Insertion loss and return loss of a channel, PCIe Gen 4/5 and DDR4 at speed (IF-PCIE-5). Needs a field solver or channel simulation.
- Whether a guard trace helps (RP-09). Depends on frequency and resonance.
- Crosstalk magnitude from parallel run (XT-06). Needs a coupling model with rise time and termination.
- Radiated emissions and the true return path at frequencies where current does not follow the nearest plane (EM-01, EM-03). Only pre-compliance measurement settles it.
- Whether an ESD part placement, Bob Smith network or shield tie works (IF-ETH-6, IF-ETH-7, EM-07). Depends on cable, enclosure and test standard.
- Whether a plane gap carries real return current (RP-10).
- NDA numbers: LPDDR, DDR5 and many SoC requirements. The tool can only check values the user types in with a source.
- Mains safety (section 9): the distances are checkable; the ratings, the tests and the enclosure are not.
- Any case where two vendor documents disagree (for example TI's two ESD placement notes): a person decides.

---

## 12. Suggested next steps for the engine (proposals, not decisions)
1. Put the rules in a data file (JSON) keyed by the ids above, with fields `value`, `unit`, `basis` (W or H), `applies_to`, `type`, `needs`, `source`, `verified`, `nda`. The engine reads it; this markdown stays the human text.
2. Extend `emc_rules.py` with the new checks: RP-02, RP-03, RP-10, EM-04, EM-05, XT-04/05, VIA-01.
3. Extend `hs_rules.py` with interface templates (USB 2, USB 3, Ethernet, DDR3, DDR4, PCIe, HDMI, MIPI) that refuse to run when a needed STK value is missing.
4. Resolve every "unverified" item before it becomes a gate: the largest are the PCIe, HDMI and MIPI numbers, the BGA fanout pitches, IPC-2152 constants, the IEC 60664-1 groove widths, and the manufacturing minimums.
