# Placement engine research for Boardwright

Status: research notes, written 2026-11-17. Every claim carries a URL. Anything I could not confirm is marked "unverified". Web search credits ran out partway through, so thermal, connector orientation, mounting-hole and two-sided reflow rules have no fetched source. They are listed in section 1.9 as unverified.

Goal: a deterministic placement engine that proposes a placement for the designer to approve before routing. Boards range from 2-layer to 6+ layer high-speed and mains boards.

## 1. Placement rules from authoritative sources

Each rule is written so a program can check it. "Source number" means the source states a number. "Derived" means I turned a source's wording into a threshold, and the threshold is a Boardwright choice to confirm with the designer.

### 1.1 Decoupling capacitors

- Mount the capacitor on the same side of the board as the IC, very close to the power pins. Source: Sierra Circuits, https://www.protoexpress.com/blog/decoupling-capacitor-placement-guidelines-pcb-design/
- Do not put a via between the capacitor and the IC when the capacitor is on the opposite side. Same source.
- Put vias inside or immediately next to the capacitor pad. Do not run a trace between the capacitor pad and its via. Same source.
- Connect the IC pin to the capacitor first, then to the via. Same source.
- Smallest value nearest: on boards without power planes, when several same-value capacitors are not possible, the lowest-value capacitor goes closest to the supply pin. Same source (the page states this for the multi-capacitor case).
- Typical value sets the same page gives: 0.01 uF to 0.1 uF for high-speed digital ICs, 1 uF to 10 uF for analog or mixed-signal ICs, 0402 or 0603 ceramics for low ESL. Same source.
- Bulk capacitor: place near the voltage entry point. Source number: bulk capacitance 2 to 10 times the local decoupling on that rail, and at least one 10 uF per voltage distribution on boards without planes. Same source.
- Distance: the Sierra page gives a time-of-flight argument (a 1 ns switching edge gives about half an inch) rather than a hard limit. Treat that as an upper bound for the check and make the default much tighter. Same source. A hard "within X mm of the pin" figure from TI, ADI or ST was not fetched. Unverified; I would ship a configurable default of 3 mm centre-to-pin (derived) and let the datasheet override it.
- MIT's course notes say the positive side of each bypass capacitor should be as close as possible to each VDD pin, one set per power pin. https://pcb.mit.edu/archive/IAP2023/lectures/lecture_03/
- BGA: capacitors under the part or on the opposite side below the fanout vias, sharing at most two balls per via. Sierra source above.

Checkable form: for each power pin P of IC U on rail R, there is a capacitor C on R with the nearest pad of C within D mm of P, on the same side as U; the capacitors on R are ordered so the smallest value has the shortest distance.

### 1.2 Crystals and oscillators

- Mount the crystal and load capacitors as close as possible to the MCU oscillator pins, keeping tracks short. ST AN2867: https://www.st.com/resource/en/application_note/an2867-guidelines-for-oscillator-design-on-stm8afals-and-stm32-mcusmpus-stmicroelectronics.pdf
- A grounded guard ring around the oscillator connections. Same source.
- Route high-frequency signals away from the oscillator paths and parts. Same source.
- ST recommends a dedicated local ground plane under the oscillator, connected to the nearest MCU ground; do not ground a metal-can crystal to that ground. Same source. This is contested: see the forum thread where a designer found the isolated plane confusing, https://community.st.com/stm32-mcus-boards-and-hardware-tools-26/pcb-layout-for-oscillator-separated-gnd-plane-confusion-162241
- ECS gives the opposite advice on the crystal itself: no ground pattern under the crystal unit, and no digital, RF or power lines under it on multilayer boards. https://ecsxtal.com/crystal-and-oscillator-printed-circuit-board-design-considerations/ Because the two vendors disagree, the engine should keep out signal copper under the crystal and leave the ground-under-crystal choice to the designer.
- Load capacitors: symmetric, with a common ground, and ground connections kept short. ECS source above.
- Source number for load capacitance: CL = (CL1 x CL2) / (CL1 + CL2) + Cs, with an example of CL 15 pF, stray Cs 5 pF, giving CL1 = CL2 = 20 pF. ST AN2867 above. This matters for placement only because longer traces raise Cs.
- A JLCPCB post says keep the crystal at least 1 cm from the board edge and away from inductors and antennas. It is a social-media post, so treat it as a weak source. https://www.facebook.com/jlcpcb/posts/crystal-layout-rules-in-4-pointsplace-the-crystal-as-close-to-the-mcu-as-possibl/1438102531814129/

Checkable form: crystal and both load capacitors within a configurable distance of the oscillator pins (derived default 10 mm); no foreign-net copper in the keep-out under and around the crystal; no switching or clock parts within a configurable radius.

### 1.3 Regulators and switching converters

- Place the input capacitor first after the IC, as close as manufacturing rules allow, and route it before anything else. TI SLYT614: https://www.ti.com/lit/pdf/slyt614
- Second: the inductor and any SW-node snubber. Keep SW-node copper small because it is a noise-coupling plate. Third: the output capacitor and the sense pin. Same source.
- ROHM buck guide: put the input capacitor and the free-wheel diode on the same layer as the IC terminal and as close as possible. The inductor should be close but not as close as the input capacitor. https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/converter_pcb_layout_appli-e.pdf
- ROHM numbers: a small bypass capacitor of 0.1 uF to 0.47 uF (X5R or X7R) goes at the IC; a larger input capacitor can sit about 2 cm away; keep the ground points of the input and output capacitors 1 cm to 2 cm apart; do not put the input capacitor and bypass on opposite sides through a via. Same source.
- ROHM: no ground-plane copper or traces directly under the inductor (eddy current lowers inductance), unless it is a closed-magnetic-circuit type. Same source.
- Hot loop: keep the input-capacitor, high-side switch and low-side switch loop small, on one side, with short wide traces. ADI AN-136: https://www.analog.com/en/resources/app-notes/an-136.html
- ADI checklist: place the power components first; keep the control circuitry in a quiet place near the output or input capacitors. Same source.
- Feedback divider: keep it next to the IC and do not route the feedback trace under the inductor or diode. ROHM source above.

Checkable form: for each converter U, input capacitor pad within a few mm of the VIN and PGND pins (derived, 2 mm to 3 mm), inductor within a configurable distance of SW, SW-net copper area under a limit, feedback resistors closer to the FB pin than the inductor, no feedback trace within the inductor courtyard.

### 1.4 Connectors, ESD and TVS parts

- Place the TVS as near to the connector as design rules allow, and place the protected IC much further from the TVS than the TVS is from the connector. TI SLVA680: https://www.ti.com/lit/pdf/slva680
- Route straight from the connector pad to the TVS pin, with no stub and, if possible, no via. Do not route unprotected signals between the connector and the TVS. Same source.
- Connect the TVS ground directly to a same-layer ground plane with nearby stitching vias; a chassis screw near the TVS and connector helps. Same source.
- Altium and Littelfuse say the same: close to the connector, shortest path. https://resources.altium.com/p/pcb-design-guidelines-using-tvs-diode-transient-protection and https://www.littelfuse.cn/assetdocs/pcb-design-guidelines-that-maximize-the-performance-of-tvs-diodes?assetguid=081efb7b-3e52-4c85-9819-1ce1c822a691
- External connectors on a board edge, and orientation so the mating side faces outward: not fetched. Unverified, though universally standard practice; the engine should take the edge and orientation from the designer's mechanical input.

### 1.5 Analog, digital and power partitioning

- Henry Ott prefers one ground plane, with the board partitioned into analog and digital sections, and no digital traces over the analog section or analog traces over the digital section. https://hott.shielddigitaldesign.com/pdf_files/june2001pcd_mixedsignal.pdf
- Ott: it is usually desirable to separate analog and digital power. Same source.
- If a split is used, join the grounds at one point, under the converter. Same source.
- TI's two-part grounding series covers the same ground (single-board mixed-signal partitioning). https://www.ti.com/lit/pdf/slyt512

Checkable form: assign each part a domain (analog, digital, power, RF, mains) from net roles; require domain regions not to overlap; require converters straddling the boundary to be at the boundary.

### 1.6 High-speed parts

I did not fetch a dedicated high-speed placement source. These are the placement implications of rules that appear elsewhere in the sources above and are otherwise unverified:

- Keep the controller close to the part it talks to so interface traces stay short.
- Leave fanout room around BGA and QFN parts for vias and decoupling (the Sierra BGA advice in 1.1 implies this).
- Series termination resistors go at the driver. ECS says to put the series resistor as close to the output pin of the oscillator as possible. https://ecsxtal.com/crystal-and-oscillator-printed-circuit-board-design-considerations/

### 1.7 Mains and isolation

- Spacing is a function of the working voltage between conductors. IPC-2221 Table 6-1 values (peak voltage between conductors, external uncoated conductors, column B2 on the Sierra table): 51 V to 100 V 0.6 mm; 101 V to 150 V 0.6 mm; 151 V to 170 V 1.25 mm; 171 V to 250 V 1.25 mm; 251 V to 300 V 1.25 mm; above 500 V add 0.005 mm per volt. https://www.protoexpress.com/blog/importance-pcb-line-spacing-creepage-clearance/ (I have not checked these against the standard itself. Unverified against the primary text.)
- The Sierra table has several columns for different conductor locations and coatings (for example one series runs 0.6 / 1.5 / 3.2 / 6.4 / 12.5 mm). The column labels were garbled in my extract, so I could not map each series to its condition. Do not hard-code the table from this page; get the standard or a licensed copy.
- TI SLUP419 compares IPC-2221B, IPC-9592B and IEC 60664-1 at several voltages, for example 300 V peak: IPC-2221B uncoated 2.5 mm, IPC-9592B 2.05 mm, IEC 60664-1 1.4 mm. https://www.ti.com/lit/pdf/slup419
- Safety isolation is governed by the product standard (for example IEC 62368-1) and not by IPC-2221. TI says basic isolation of a 265 VAC input is tested at 2 x 265 + 1000 = 1530 V. Same source.
- Slots cut in the board can increase creepage; they do not change clearance. Minimum slot width depends on pollution degree and material group. Same source (table not extracted).
- Pollution degree, overvoltage category and material group are inputs the designer must give. The engine cannot infer them.

Checkable form: every net gets a voltage class and an isolation domain (primary, secondary, protective earth); the engine keeps domains in separate board regions and reports the required creepage and clearance for each pair from a table the designer approves. The numbers above are for orientation only.

### 1.8 Manufacturing and assembly

- Courtyard: IPC-7351B nominal-density courtyard excess is 0.25 mm; least density 0.10 mm, most 0.40 mm in the forum summary; parts over 10 mm in any dimension need 0.40 mm. https://www.pcblibraries.com/forum/placement-courtyard-excess_topic3372.html and https://www.linkedin.com/posts/zachariah-peterson_pcb-courtyard-vs-component-clearance-how-activity-7523877182612406273-dqYM (the forum post quotes values that do not agree with each other, and I did not see the standard; verify before relying on them).
- KiCad library convention F5.3: 0.25 mm around pads and body; one third-party library notes 0.5 mm for connectors and switches and 0.15 mm under 2 x 2 mm. https://klc.kicad.org/ and https://github.com/sivakov512/kicad-library/blob/main/CONTRIBUTING.md (the second is a third-party reading of the first; check klc.kicad.org directly).
- Fiducials: three global fiducials on the board, in a non-symmetrical L pattern; clearance to the board edge at least 3.35 mm (JLCPCB) or 118 mil, about 3.0 mm (Sierra); diameter 1 mm to 3 mm; two local fiducials diagonal to fine-pitch parts. https://jlcpcb.com/blog/fiducial-marks , https://www.protoexpress.com/blog/pcb-design-for-assembly-checklist-important-checks-for-layout-engineers/ , https://www.protoexpress.com/blog/design-mistakes-that-lead-to-pcb-assembly-errors/
- Test points: leave at least 5.08 mm between adjacent BGA parts for test probes (Sierra DFA checklist above). Flying-probe test notes are at https://www.protoexpress.com/blog/design-for-testing-guidelines-pcb-manufacturing/
- Board edge: the fiducial rule implies a 3 mm-class edge zone that the assembler's rails use. A general part-to-edge figure was not fetched. Unverified; use the chosen assembler's capability page (https://jlcpcb.com/capabilities/pcb-capabilities) as the input.
- Orientation consistency, both-side reflow rules (heavy parts on the second-reflow side, no tall parts under fine-pitch parts): not fetched. Unverified.

### 1.9 Not sourced in this pass

Thermal (hot-part spacing, airflow, copper area, electrolytic capacitors away from heat), mounting holes and height keep-outs, and connector orientation. Search credits ran out. The ROHM note gives one thermal number (2 A on 35 um copper for a 20 C rise, and 0.7 mm per amp on 1 oz as a rule of thumb) but that is a routing width rule, not a placement rule. https://fscdn.rohm.com/en/products/databook/applinote/ic/power/switching_regulator/converter_pcb_layout_appli-e.pdf Treat thermal placement as designer-supplied zones and keep-outs until sourced.

## 2. Algorithms and what exists open source

### 2.1 Families of method

- Force-directed (spring and charge model): nets act as springs, parts repel each other. Simple and fast, gives a clustered result, needs a separate legalization step. A PCB demonstration applies the net force at the pad rather than the part origin so the part rotates. https://jrainimo.com/build/2023/03/force-directed-circuit-board-footprint-autoplacement/ . Code: https://github.com/JarrettR/FD-Autoplacer (a tech demo by the author's own description; licence unverified).
- Quadratic and analytical placement (minimize a smooth wirelength, then spread): the standard in chip design. RePlAce uses an electrostatics model for density; DREAMPlace recasts it as neural-network training on a GPU. DREAMPlace reports over 30 times speedup over the CPU RePlAce. https://github.com/limbo018/DREAMPlace
- Simulated annealing (swap, move, rotate with a cost that includes wirelength and penalties): robust, easy to add rule penalties, slow to converge on large boards, deterministic if the random seed is fixed.
- Constraint and group based: place by hierarchy and connectivity, then arrange satellites by rule. This is how people place by hand and is what the Boardwright method in section 3 uses.
- Reinforcement learning: see 2.3.

### 2.2 Open-source projects

| Project | What it does | Licence | Maturity | Reusable for Boardwright |
|---|---|---|---|---|
| CadMust-Neo, https://github.com/remiblokker/CadMust-Neo | KiCad plugin, simulated annealing, HPWL plus courtyard, boundary and keep-out penalties; translate, swap, rotate and net-aware median moves; rigid groups; auto-excludes power nets | MIT | Created 2026-03, 29 stars, 44 commits, KiCad 9 | The move set and cost function are a good model. It has no datasheet or role rules, and it is an interactive plugin. Pure Python, so code can be adapted under MIT. |
| kicad-tools, https://github.com/rjwalters/kicad-tools | Python library with force-directed, evolutionary and hybrid placement, plus routing | MIT | 77 stars, 106 open issues, very active (pushed 2026-11-17), 1 GB repository (the size is odd; unverified why) | Possible source of a PCB model and optimizer to study. Heavy dependency; maturity of the placement part is unverified. https://pypi.org/project/kicad-tools/ |
| kicad-auto-designer, https://github.com/nabheet/kicad-auto-designer | Force-directed overlap removal, edge placement for connectors and antennas, component type recognition | GPL-3.0 | 5 stars, pushed 2026-02 | The ideas are reusable. GPL-3.0 code cannot go into an MIT project, so read it and reimplement. |
| kicad-kbplacer, https://github.com/adamws/kicad-kbplacer | Keyboard key placement and routing | GPL-3.0 | 548 stars, active | Not general placement. GPL. |
| Replicate Layout, https://github.com/MitjaNemec/ReplicateLayout | Copies the layout of one hierarchical sheet to the other instances | GPL-2.0 | 138 stars, active | Useful idea: reuse a human-approved sub-layout for repeated blocks. GPL, so call it rather than copy it. |
| KiKit, https://github.com/yaqwsx/KiKit | Panelization and fabrication automation | MIT | 2067 stars, active | Not placement. Useful for panel and fiducial output at release time. |
| DREAMPlace, https://github.com/limbo018/DREAMPlace | GPU analytical placement for chips | BSD-3-Clause | 1070 stars, active | Needs a GPU and chip-style inputs. What transfers is the idea (smooth wirelength plus density penalty), not the code. |
| RePlAce, https://github.com/The-OpenROAD-Project/RePlAce | Chip global placement | BSD-3-Clause | Archived 2020; the work lives on in OpenROAD | Same: ideas only. |

Licence data came from the GitHub repository records, fetched 2026-11-17. I did not read the source of any of these beyond the CadMust-Neo README, so quality claims are from README text and are unverified in practice.

KiCad's own Python action-plugin API is the delivery route for several of these; the Boardwright MCP already drives KiCad directly, so no plugin is needed.

### 2.3 Learning-based and commercial

- Component-centric RL (2026): main part fixed at the centre, passives placed on discrete candidate spots around its pins; evaluated on nine real boards; reward balances Euclidean wirelength and non-overlap. https://arxiv.org/html/2602.23540v1 . The discrete-slot idea is directly useful and needs no learning (see 3.5).
- RL with adaptive rewards (DATE 2024): PCB placement as a Markov decision process; reports an average wirelength reduction of 21.1% for one variant versus a simulated-annealing baseline (as extracted; unverified). https://past.date-conference.com/proceedings-archive/2024/DATA/1040_pdf_upload.pdf
- Google chip-placement RL work is the origin of much of this: https://arxiv.org/html/2602.23540v1 cites it. PCB netlists are smaller, so the DATE paper argues the setting is different.
- Quilter: physics-driven AI doing placement and routing; 100 to 1,000 components per board; pin density under 20%; most boards take 2 to 5 review cycles; supports KiCad and Altium files. https://www.quilter.ai/ . Closed, paid, cloud.
- DeepPCB: placement for up to 1,000 components and 2,200 pins; board file in; electrical and mechanical constraints; free trial of 2 hours for boards up to 100 components, then pay-as-you-go. https://deeppcb.ai/ai-powered-pcb-placement-by-deeppcb/ . Closed, cloud.
- Both commercial claims are vendor marketing and I have no independent test of either. Both send the design to a third party, which conflicts with Boardwright's local-first stance, unverified as a policy choice but worth stating.

### 2.4 What this means

No open-source tool combines schematic roles, datasheet rules and legalization for KiCad. The reusable pieces are: the annealing move set and cost shape (CadMust-Neo, MIT), the discrete-slot satellite idea (RL paper), the pad-level force model (FD-Autoplacer), and the sub-layout reuse idea (Replicate Layout). Everything else, the rule layer, has to be written.

## 3. A concrete deterministic method for Boardwright

Principle: rules first, optimization second, human approval last. The engine never moves a part the designer locked. Given the same inputs and seed, it gives the same output.

### 3.1 Steps

1. **Read.** Netlist, schematic sheets and sheet hierarchy, footprints with pads and courtyards, board outline, keep-outs, layer count, stackup, assembler capability file. Existing Boardwright MCP tools cover most of this (netlist export, footprint pad and bounds listing, board info).
2. **Classify nets and parts.** Give each net a role: ground, power rail (with voltage and current), clock, differential pair, high-speed, analog, reset or enable, mains line, mains neutral, protective earth, protected external signal. Each part gets a role: connector, mounting hole, IC, passive, crystal, inductor, diode, TVS, test point. Roles come from net names, pin names, datasheet facts (stored by the datasheet reader), and designer input. Where the role is unclear, the engine asks; it does not guess.
3. **Group.** Build functional blocks from sheet hierarchy first, then connectivity: for each IC, collect the passives whose only non-power connections go to that IC. Connected components of the graph with power and ground removed give the clusters. Domains (analog, digital, power, mains primary, mains secondary) come from the net roles.
4. **Anchors.** Fix connectors on the edges the designer names, mounting holes, mains entry and its fuse and isolation boundary, mechanical items (switches, LEDs, displays). These are locked and come from the designer's mechanical input. Add the isolation slot or keep-out region before anything else moves.
5. **Block leaders.** Place each block's main IC. Do this with a small analytical or force-directed step on blocks (not parts), with domain regions as constraints, ordering blocks by connectivity weight to the anchors. Orientation: rotate each IC to face the block it talks to most.
6. **Satellites by rule.** Place parts in the priority order the converter guides use (TI SLYT614): for each converter, input capacitor, then inductor and snubber, then output capacitor, then feedback divider; for each IC, decoupling capacitors by value (smallest nearest); crystal and load capacitors; pull-ups and series resistors; TVS at the connector. Use a **discrete candidate slot** list around the leader's pins (the RL paper's idea): for each satellite generate candidate positions and rotations at stated offsets from its target pin, discard those that overlap, take the one with the lowest rule cost. Ties break on reference designator order, which makes the result deterministic.
7. **Legalize.** Remove overlaps using courtyards plus the assembler's clearance (section 1.8). Keep rule-bound pairs rigid (a capacitor and its pin move together). Snap to a grid. Run a pass that checks keep-outs, board edge distance, and both-side height limits. If a rule-bound satellite cannot be legalized, report it instead of moving it far away.
8. **Score.** Compute the score in 3.3. Store the per-term numbers.
9. **Improve.** Simulated annealing over unlocked block leaders and free parts only: moves are swap, shift, rotate and block flip; rule-bound satellites move with their leader. Cooling schedule, seed and iteration count are fixed in config. Reject any move that breaks a hard rule. Keep the best layout seen. This is the CadMust-Neo structure with a different cost function.
10. **Propose.** Write the placement as a KiCad PCB change set (not applied until approved), plus a report: render of the board, rule table with pass or fail per rule, score breakdown, congestion map, list of parts that need a decision.

### 3.2 What the designer approves

- Inputs before the run: board outline and edges for connectors, mounting holes, height limits, layer count and stackup, which parts are locked, domain assignments, mains voltage, overvoltage category, pollution degree, and the creepage and clearance table in use.
- Role questions the engine could not answer from data.
- The proposal, as three things: the picture, the rule table, and the list of waived or relaxed rules. Boardwright already forbids silently waiving checks, so any relaxed rule appears as a named waiver the designer accepts.
- Approval is recorded in PROJECT.md. Only after approval are the positions written to the board.

### 3.3 Data each rule needs

| Rule | Data needed | Source of data |
|---|---|---|
| Decoupling | power pin to rail map, pin positions, capacitor values, max distance | netlist, footprints, datasheet |
| Crystal | oscillator pins, load capacitor refs, keep-out radius | netlist, footprint, datasheet |
| Buck or boost | VIN, SW, PGND, FB pins; role of each part (input capacitor, inductor, diode) | datasheet, schematic |
| ESD | connector refs, TVS refs, protected net | netlist, designer |
| Domains | net roles, domain regions | designer plus roles |
| Mains | voltage per net, isolation class, creepage table | designer |
| Courtyard | courtyards, excess | footprints, assembler file |
| Fiducials and edge | edge zones, fiducial positions | assembler file |
| Thermal | power dissipation per part, keep-outs | datasheet, designer (unverified method) |

Datasheet-derived values must carry a page number, as the Boardwright datasheet reader already does. A rule that has no datasheet fact gets the default from section 1 and is labelled "default, not from datasheet".

### 3.4 Scoring a placement for routability before routing

Use a weighted sum of hard-rule violations (must be zero), soft-rule distance penalties, and routing-cost estimates:

- **Wirelength.** Half-perimeter wirelength per net, summed, with power and ground nets excluded or given low weight (CadMust-Neo does this). The RL paper argues total Euclidean wirelength tracks routed length better than HPWL, since HPWL ignores pins inside the bounding box. https://arxiv.org/html/2602.23540v1 Use a minimum spanning tree length for multi-pin nets as a cheap middle ground (derived).
- **Congestion map.** Divide the board into bins (derived default 1 mm to 2 mm). For each net, spread its estimated demand over the bins in its bounding box, as a rectangular uniform wire density (RUDY, a chip-design estimator; I have not fetched a source for the name, unverified). Capacity per bin comes from the track pitch (trace plus space of the chosen class) times the number of signal layers, less area blocked by pads, keep-outs and, on 2-layer boards, the ground pour that wants the second layer. Penalize bins with demand over capacity, and penalize the sum of squares so one hot spot costs more than several mild ones.
- **Pin access.** Count pins that have no free exit direction (blocked by neighbouring courtyards on all sides). A fine-pitch IC with no fanout room is a score killer.
- **Crossing estimate.** Count net bounding-box crossings between blocks as a proxy for layer changes; most useful on 2-layer boards.
- **Return-path hints.** For 4 or more layers with a reference plane: count high-speed nets crossing a domain boundary or isolation slot. Zero is required, not scored.
- **Calibrate against reality.** After the designer routes the approved placement, Boardwright can compare the estimate with the real routed length and actual DRC unconnected count, and store the error. That gives a local check of the weights without any machine learning.

The ADI and TI guides imply an ordering of weights: hot-loop and ESD rules are hard; decoupling distance is hard above a bound and soft below it; wirelength is the soft term that decides between valid layouts.

### 3.5 Why discrete slots and rules beat pure optimization here

The RL paper states a continuous plane creates "small meaningless shifts" that inflate the search space, and uses discrete positions around the main part instead. https://arxiv.org/html/2602.23540v1 The same logic suggests a deterministic engine: rule-bound parts get a short, enumerated list of positions; only the block level is free-form. It keeps the output reviewable by a human, which is the reason for the design.

## 4. Honest limits: what still needs a person

- Anything with a safety standard behind it: mains creepage and clearance, isolation slots, protective earth, fuse placement. The engine can apply a table the designer chooses and measure against it. It cannot choose overvoltage category, pollution degree or the product standard, and it cannot certify. The IPC-2221 numbers in section 1.7 were not checked against the primary text.
- Mechanical fit: enclosure, connector positions, heights, assembly access. The engine takes these as inputs and does not infer them.
- High-speed and RF: placement for controlled impedance, length-matched groups, antennas and matching networks depends on the stackup and the routing plan. The engine can keep parts close and leave fanout room. It cannot judge a layout.
- Thermal: needs dissipation numbers and judgment about airflow. Not sourced here (section 1.9).
- Conflicting guidance: ST and ECS disagree on ground under a crystal (section 1.2). Datasheet layout examples should win over generic rules, and a person decides when they conflict.
- Role detection: net and part roles read from names are guesses. Wrong roles give confidently wrong placement, so unknown roles must be asked, not defaulted.
- Score is a proxy. The congestion estimate and wirelength do not guarantee a board routes, and the weights are unverified until calibrated on real boards.
- Placement quality of AI vendors (Quilter, DeepPCB) is claimed, not independently measured here.
- Final sign-off of the approved placement, and of the routed result, stays with the designer.

## Source list by topic (for quick review)

Decoupling: Sierra Circuits; MIT 6.S062 layout lecture. Crystals: ST AN2867; ECS. Switching converters: TI SLYT614; ROHM buck layout note; ADI AN-136. ESD: TI SLVA680; Altium; Littelfuse. Partitioning: Ott (Printed Circuit Design, June 2001); TI SLYT512. Mains: Sierra Circuits creepage article; TI SLUP419; Altium IPC-2221 article (https://resources.altium.com/p/using-an-ipc-2221-calculator-for-high-voltage-design). Courtyards and fiducials: PCB Libraries forum; KiCad library conventions; JLCPCB; Sierra DFA. Algorithms: DREAMPlace and RePlAce repositories; CadMust-Neo; kicad-tools; FD-Autoplacer; arXiv 2602.23540; DATE 2024 paper; Quilter; DeepPCB.
