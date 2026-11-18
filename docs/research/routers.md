# Routing engines for Boardwright: research notes

Date of research: 17 November 2026. Everything below is sourced to a URL. Where I could not confirm a claim I say "unverified". Vendor numbers (Quilter, DeepPCB) are marketing, not independent tests; I say so each time.

## 1. Freerouting

### Version, activity, licence

- Latest release found: v2.5.0, published 5 October 2026. Earlier ones: v2.4.1 (3 September), v2.3.0 (7 August). Cadence is roughly one release every four to five weeks recently. Source: https://github.com/freerouting/freerouting/releases
- The repository shows about 3,760 commits, 30 open issues, 20 open pull requests. The maintainer says he spends about 4 hours a week on it and that individual support is for paid sponsors only. Source: https://github.com/freerouting/freerouting
- Licence: GPL-3.0. Source: https://github.com/freerouting/freerouting

**What GPL-3 means for an MIT project.** I am not a lawyer; this is the common reading and is unverified against legal advice. Running a GPL program as a separate process (command line, or its REST API) does not make the caller a derivative work, as long as Boardwright does not copy, link or bundle Freerouting code. The safe pattern is: the user downloads Freerouting themselves (or a script downloads it on their machine, with the licence text shown), and Boardwright talks to it only through files, command-line flags or HTTP. Do not ship the JAR or the native binaries inside the Boardwright repository or package. If we ever fork Freerouting to add features, the fork must be GPL-3 and live in its own repository.

### Running it headless

Source for all flags: https://raw.githubusercontent.com/freerouting/freerouting/master/docs/command_line_arguments.md

- `-de board.dsn` loads the design. Optional extras can be joined with `+` (`board.dsn+board.rules`; `.ses`, `.kicad_dru` and `.kicad_pro` are accepted). An adjacent `<board>.rules` file loads automatically.
- `-do out.ses` saves the result when routing ends. The format follows the extension (`.dsn`, `.ses`, `.scr`).
- `-drc report.json` writes a design rule check report in KiCad JSON DRC format. This is useful: it gives us a router-side check we can compare against KiCad's own DRC.
- `--router.autorouter.max_passes=N` caps passes. `-mp N` still works but is deprecated.
- `--router.max_threads=N` is the global thread cap (default cores minus one). `-mt N` is deprecated. The autorouter itself currently runs single-threaded; only the optimiser uses more threads.
- `--router.optimizer.enabled=true|false` (default true), `--router.optimizer.improvement_threshold=%` (default 2.5; lower is slower and removes more vias), `--router.optimizer.item_selection_strategy=sequential|prioritized`.
- `-inc A,B` skips routing for the named net classes. This is how we keep critical nets out of the autorouter.
- Any internal setting can be given as `--name=value`, for example `--router.via_costs=150` or per-layer lists such as `--router.layers.routable=false,true`.
- No dedicated headless flag is documented. Use `--gui.enabled=false` (shown in the doc). For a server: `--gui.enabled=false --api_server.enabled=true --api_server.authentication.enabled=false --api_server.endpoints=http://0.0.0.0:37864`. The default endpoint is `http://127.0.0.1:37864` and authentication is on by default.
- The README calls the REST API beta and subject to change. Source: https://github.com/freerouting/freerouting
- Docker: image `ghcr.io/freerouting/freerouting` (tags `latest`, `nightly`; linux/amd64, arm64, arm/v7). Source: https://github.com/freerouting/freerouting
- Java: README recommends JRE 25 (Eclipse Adoptium). Since v2.5.0 there are GraalVM-compiled native CLI binaries for Windows x64, Linux x64 and macOS that need no Java and start in under a second. Sources: README above and https://github.com/freerouting/freerouting/releases/tag/v2.5.0
- v2.3.0 added an MCP and A2A server for AI agents. Source: https://github.com/freerouting/freerouting/releases (I did not test it; relevance to Boardwright is unverified).

Many flags were renamed between v2.x releases (`-mp`, `-mt`, `-oit` are deprecated; `-hr`, `-us`, `-im` removed; some optimiser strategies removed in 2.5.0). Boardwright must pin a Freerouting version and test the flags it uses at start-up.

### Input and output, and the KiCad side

- Input is Specctra DSN, output is Specctra SES (session) or SCR.
- KiCad 6 and later: the Freerouting plugin from the Plugin and Content Manager exports, runs, imports, and then runs KiCad's zone filler so pours are re-cut around the new copper. Source: https://github.com/freerouting/freerouting/blob/master/docs/integrations.md (as summarised by the fetch tool).
- v2.5.0 adds a KiCad 10+ IPC mode that falls back to DSN/SES if IPC is not available. Source: https://github.com/freerouting/freerouting/releases/tag/v2.5.0. Details of its stability: unverified.
- Python: `pcbnew.ExportSpecctraDSN(board, path)` and `pcbnew.ImportSpecctraSES(board, path)` exist, but they only work inside KiCad's own Python (scripting console or plugin), not from a plain Python interpreter. A forum thread reports `ExportSpecctraDSN` returning false in a nightly and failing outside pcbnew. Source: https://forum.kicad.info/t/python-apis-exportspecctradsn-broken-in-nightly/24011
- Headless SES import: the KiCad feature request (GitLab issue 14339, tagged KiCad 7) says import "requires an active window of pcbnew"; the workaround is running pcbnew under a virtual display, called "extremely brittle". Whether it has been fixed in KiCad 9/10: unverified. Source: https://forum.kicad.info/t/gui-agnostic-import-for-specctra-session-to-allow-headless-scripted-auto-routing/41063
- `kicad-cli` support for Specctra: I found none. Unverified, but I saw no mention anywhere.
- Consequence for Boardwright: either (a) write our own SES parser and add the tracks and vias through the KiCad IPC API or a file-level writer (SES is a simple text format with wires and vias in board coordinates), which avoids the pcbnew GUI dependency, or (b) use pcbnew's Python from the KiCad install. Option (a) is more robust and also lets us validate before touching the board. DSN export from KiCad's own Python is the pragmatic first step; a DSN writer of our own is a bigger job.

### Algorithm

- Freerouting is a maze router with rip-up and reroute, followed by an optimiser that tries to shorten traces and remove vias. One reader of the source describes the search as A* with via costs for layer changes and passes that grow more aggressive about ripping up. This is a secondhand blog reading, not official documentation. A third-party Python port says Freerouting uses "free-space expansion rooms". Source: https://git.supported.systems/warehack.ing/freeroute/raw/branch/main/README.md. Treat details as unverified.
- v2.5.0 introduced a deterministic batch optimiser (fixed tie-breaking, restores best-known board). Source: https://github.com/freerouting/freerouting/releases/tag/v2.5.0
- 45/90-degree: the exact mode set is not stated in the pages I read. Unverified.

### Strengths and known weaknesses

Strengths: free, scriptable, handles 2 to 4 layer boards with ordinary rules, improved a lot in 2.5.0.

Weaknesses:
- Quilter's comparison article (competitor, illustrative figures only) lists Freerouting at 60 to 80 percent completion, "fail to partial" high-speed rule adherence, "limited" dense BGA handling, and says autorouters produce "dropped spaghetti" and broken-up buses. Source: https://www.quilter.ai/blog/pcb-autorouting-in-2026-a-review-of-traditional-tools-vs-quilters-ai-approach
- Differential pairs: the only Freerouting issue I found is #358 "Differential pair routing", closed with no activity (source: https://issues.ecosyste.ms/hosts/GitHub/repositories/freerouting%2Ffreerouting/issues). A KiCad forum user routes pairs last because Freerouting may break them up. Source: https://forum.kicad.info/t/complex-pads-and-freerouting/9517. I could not read the issue tracker directly (GitHub returned a timeout), so whether pairs and length matching are supported at all is unverified; I assume not.
- BGA escape routing is on the maintainer's "What's Next" list, so it is not solved. Multi-threaded routing is also still a plan. Source: https://github.com/freerouting/freerouting/releases/tag/v2.5.0
- Planes and pours: handling was only added in 2.5.0 ("copper pour and power plane awareness"). Source: same.
- Speed and quality on large boards: see the benchmark section.

## 2. Other routers and ideas

| Tool | What is better than Freerouting | Licence / maturity | Can we add it on top? |
|---|---|---|---|
| Topola (Rust, topological) | Traces not tied to a grid or 45 degrees; can pack denser | MIT; "work in progress", no releases, failing CI on latest commit | Different engine; reads DSN reportedly (unverified). Watch only. |
| OrthoRoute (GPU, KiCad plugin) | PathFinder negotiated congestion on a Manhattan lattice; 512 of 512 nets on a test backplane | MIT; author says not a general router; Hackaday doubts general use | Only for very large regular backplanes. Idea reusable. |
| KiCadRoutingTools (atomic14 fork of drandyhaas) | Rust-core A*; diff pairs, trombone length matching, BGA/QFN fanout, plane-via tools | MIT; about 1,600 commits, 3 stars; self-reported tests only | Closest ready-made source of ideas and maybe code for our MIT side |
| tscircuit capacity autorouter | Capacity-node decomposition, benchmark of 105 scenarios in CI | MIT; TypeScript; aimed at tscircuit's own generated boards | Idea only |
| KiCad PNS | Interactive push-and-shove, diff pairs, length tuning | GPL; part of KiCad | Not drivable headless as far as I found |
| DeepPCB / Quilter | Learned or physics-driven routing, constraint aware | Commercial cloud | Out of scope for an offline MIT tool; useful as a yardstick |

### Details and sources

**Topola.** Interactive topological ("rubber band") router in Rust, MIT, with traces that bend freely. Latest commit on `develop` shows failing CI, 36 open issues, no tagged release. Funded by NLnet (project 2023-10 to 2025-06) and a follow-on autoplacer from 2026-04. Sources: https://codeberg.org/topola/topola and https://nlnet.nl/project/Topola/. A commit mentions exporting DSN from KiCad and LibrePCB, but full support is not confirmed (unverified). Topological routing is also the idea behind the commercial TopoR and the gEDA Toporouter. Source: https://en.wikipedia.org/wiki/TopoR

**OrthoRoute.** MIT, runs as a KiCad plugin over the IPC API (KiCad 9+), has a headless/cloud mode that exports a board, routes on a GPU machine and imports the result. April 2026 baseline: 512 of 512 nets on a test backplane, with a per-net time bottleneck still open. The README says it is aimed at huge, dense, regular multilayer backplanes and is not a general autorouter; no push-and-shove. Sources: https://github.com/bbenchoff/OrthoRoute, https://hackaday.com/2026/07/01/gpu-accelerated-autorouter-handles-monstrous-pcb-designs/, https://hub.allspice.io/AllSpiceMirrors/OrthoRoute/src/branch/main/docs/optimization/optimization_baseline_2026-04-03.md

**KiCadRoutingTools.** KiCad 9 and 10, plugin or CLI. Grid A* with Rust core, octilinear, rip-up and reroute with several net orderings, pose-based diff-pair routing, trombone length matching with DDR byte-lane grouping, BGA/QFN fanout generators, plane-connection via tools. Stated limits: no push-and-shove, no blind or buried vias, no layer swaps for multipoint nets with 3+ pads, no region-specific rules. Test results on its page are self-reported (for example 47 of 47 nets on an FTDI board in 8.6 s). Source: https://github.com/atomic14/KiCadRoutingTools. Because it is MIT and already does fanout, plane vias and length tuning, it is the first place to look before writing our own. Quality on real boards: unverified.

**tscircuit.** Capacity-based autorouter package (`@tscircuit/capacity-autorouter`, MIT). Its CI benchmark reports completion rate, relaxed DRC pass rate, timeouts and P50/P95 times over 105 scenarios. Source: https://github.com/tscircuit/tscircuit-autorouter/wiki and the PR threads listed there. Board class is small generated boards; fitness for KiCad boards is unverified. The scenario-benchmark-in-CI idea is worth copying.

**KiCad push-and-shove (PNS).** It is the interactive router inside pcbnew (KiRouter). I found no documented way to call it from the IPC API or headless. The IPC API (kicad-python / kipy) can add and edit tracks and vias, but one OrthoRoute user reports routing-related API limits (anecdote, unverified). Source: https://docs.kicad.org/doxygen/pns__line__placer_8cpp_source.html. Conclusion: treat PNS as the human's tool for finishing critical nets by hand.

**DeepPCB / InstaDeep.** Cloud service. Its own analysis of 32,000+ completed jobs: median completion 100 percent, mean 95.6, 86 percent of boards at 95+ percent; median time 4.6 minutes, 90th percentile 153 minutes; large boards (4,000 to 5,000 airwires, 6 to 8 layers) reached 100 percent but took about 14 hours. It measures only connected airwires, not constraint quality, and says to expect 10 to 20 percent manual work above 500 airwires. Source: https://deeppcb.ai/pcb-autorouter-benchmark-2026/

**Quilter.** Physics-driven reinforcement learning, placement and routing. Claims a 7x faster router and 3.5x faster jobs against its own internal benchmark. Sources: https://www.quilter.ai/blog/router-7x-faster (title seen in search results only, page not read) and https://www.quilter.ai/blog/pcb-autorouting-in-2026-a-review-of-traditional-tools-vs-quilters-ai-approach. DeepPCB published a three-board comparison (98 to 414 airwires) claiming 97.3 percent vs Quilter's 87.7 percent completion; neither claim has been independently replicated. Source: https://deeppcb.ai/deeppcb-vs-quilter-open-source-routing-compared-2026/

**Altium, Allegro, Xpedition.** I only read summaries. Quilter's article says legacy suites offer diff-pair routing and length tuning as human-guided steps, treat constraints as "guardrails, not goals", and that dense BGA escape is a common failure point (source above). Altium Circuitmaker's Situs is a topological autorouter (https://www.altium.com/documentation/altium-circuitmaker/automated-board-layout-situs-topological-autorouter; content not read). Details of Allegro and Xpedition interactive routing: unverified. The useful public idea is the workflow, not the algorithm: constraint sets per net class, then interactive routing of critical groups, then auto-route of the rest, then tuning.

### Academic ideas

- **Negotiated congestion (PathFinder).** Nets compete for scarce resources over repeated iterations, with the cost of overuse rising each round and critical nets getting more say. McMurchie and Ebeling, FPGA 1995. Sources: https://dblp.org/rec/conf/fpga/McMurchieE95.html and https://www.oreilly.com/library/view/reconfigurable-computing/9780123705228/ch18.html. OrthoRoute is a PCB use. It needs changes inside a router's core, so it cannot be a wrapper around Freerouting.
- **Rip-up and reroute, net ordering.** General technique, summarised at https://en.wikipedia.org/wiki/Routing_(electronic_design_automation). Net ordering can be done outside Freerouting only coarsely (run net classes in stages with earlier results kept as fixed wires; whether Freerouting keeps pre-existing tracks fixed cleanly is unverified).
- **Topological / rubber-band routing.** Dayan's 1997 thesis underlies Toporouter. Source: https://en.wikipedia.org/wiki/TopoR. Needs a different engine (Topola).
- **BGA escape routing, length-matching and meander algorithms, differential-pair routing, layer assignment.** I did not fetch papers for these; I rely on general knowledge and the KiCadRoutingTools implementation as a practical example. Treat as unverified literature.

### Where each idea can live

- Before Freerouting, in our MIT code (no change to Freerouting): fanout and escape for BGA and QFN (stubs and vias placed as fixed items), layer assignment hints (`--router.layers.routable`, `-inc` exclusions), keepouts, net-class rules, pre-routing critical nets and keeping them as fixed copper.
- After Freerouting, in our MIT code: length tuning (trombone or accordion), teardrops, via stitching, trace smoothing, zone refill, DRC.
- Inside Freerouting (Java, GPL): negotiated congestion, native diff-pair routing, BGA escape inside the search, true multi-threaded routing. These belong upstream as pull requests, not in our repo.

## 3. Benchmarks

- Freerouting v2.5.0 release notes report on PCBench (1,157 open-source boards): clean boards (zero DRC violations) up from 30.9 percent to 75.0 percent; fully routed boards up from 51.9 to 75.4 percent; corpus runtime 3,251 s to 2,997 s. By tier, clean completion was 99.8 percent (A), 61.6 percent (B), 49.2 percent (C), 50.0 percent (D). The tiers are not defined in what I read (unverified). Maintainer-run, not independent. Source: https://github.com/freerouting/freerouting/releases/tag/v2.5.0
- I could not find an independent paper or repo for PCBench itself (unverified).
- Quilter's table: Freerouting 60 to 80 percent completion, Altium autorouter 55 to 75 percent, no dataset given. Competitor marketing. Source: https://www.quilter.ai/blog/pcb-autorouting-in-2026-a-review-of-traditional-tools-vs-quilters-ai-approach
- A KiCad forum user's three-board test reportedly found Freerouting gave 8 to 12 percent shorter tracks and 70 to 97 percent fewer vias than the user's own router, in about 12 seconds. This came from a search summary of a thread I did not open; unverified. Thread: https://forum.kicad.info/t/two-months-of-testing-llms-on-pcb-autorouting-what-worked-what-didnt-and-whats-left-to-try-open-archive/72250
- DeepPCB: 95.6 percent mean completion over its platform jobs (section 2). No Freerouting numbers on that page. Source: https://deeppcb.ai/pcb-autorouter-benchmark-2026/
- OrthoRoute: one 512-net backplane. tscircuit: 105 internal scenarios. KiCadRoutingTools: a few self-reported boards.
- Takeaway: there is no neutral head-to-head on boards above 4 layers with high-speed rules. We should build our own benchmark from Boardwright projects (completion, DRC count, via count, total length, time) and run it on every Freerouting version bump.

## 4. Recommendation for Boardwright

### Principle

The engine is deterministic: same board, same rules, same pinned Freerouting version, same flags gives the same result. The AI only fixes what is left. Freerouting is a tool inside the pipeline, not a trusted oracle.

### Pipeline

1. **Classify nets (our code).** From PROJECT.md and the schematic, tag each net: power/ground, critical (diff pair, clock, RF, DDR, USB high-speed, sensitive analogue), ordinary. Critical nets are never given to Freerouting.
2. **Write rules (our code).** Net classes with widths, clearances and via sizes from the stack-up and fab limits, set into KiCad and into the DSN. Pin these in `boardwright.json`.
3. **Plan layers.** For 4 layers or more, fix the stack (signal / ground / power / signal). Mark inner planes as pours and let Freerouting use only signal layers (`--router.layers.routable=...`). Wrong layer assignment is a common silent failure, so we decide it, not the router.
4. **Fanout and escape (our code).** Place short stubs and vias for QFN, QFP and BGA pins, decoupling-cap vias and plane vias as locked items. Start with ideas or code from KiCadRoutingTools (MIT) after reviewing quality. Freerouting's own SMD fanout pre-pass came back in v2.3.0 (releases page) and may be enough for coarse parts; BGA escape is not solved there.
5. **Critical nets first.** Route by a deterministic generator for simple cases (point-to-point diff pairs, short clocks) or leave them to the human or AI with the PNS router. Lock them, so Freerouting sees them as obstacles.
6. **Run Freerouting.** Export DSN, call the pinned binary with `--gui.enabled=false`, `-de`, `-do`, `-drc`, `-inc <critical classes>`, `--router.autorouter.max_passes`, optimiser on. Use a timeout and a thread cap. Store the log and flags in `reports/`. Try two or three fixed parameter sets (via cost, passes) and keep the best by score; this stays deterministic.
7. **Import.** Parse SES in our code and write tracks and vias through the KiCad IPC API or a file writer. Do not rely on GUI-bound `ImportSpecctraSES` (section 1). Refill zones.
8. **Check after.** KiCad DRC with schematic parity, unconnected count, plus our own geometry gates (below). Compare Freerouting's `-drc` JSON to KiCad's DRC; any disagreement is a flag. Anything unrouted or violating goes into a short list for the AI, with coordinates.
9. **Add after (MIT code).** Length tuning on matched groups, via stitching around the board edge and plane splits, teardrops, smoothing, silkscreen clean-up, another refill and DRC.
10. **Gate.** Stop and show the report if completion is not 100 percent or any rule check fails. Never relax a rule to pass.

### Checks beyond DRC that the engine should run itself

Reference-plane continuity under critical nets, return vias near layer changes, stub length, diff-pair skew and spacing, length group totals, trace-to-board-edge, acid traps and sharp angles on power. DRC does not cover most of these. This list is my engineering judgment, not from a source (unverified).

### Upstream or in our own code

- Upstream to Freerouting (GPL, Java): BGA escape, native differential-pair support, multi-threaded search, a way to say "keep these items fixed", a documented headless entry that returns a machine-readable result. Benefit: everyone gains; cost: slow review (the maintainer works about four hours a week).
- Our own MIT code: net classification, rule generation, layer plan, fanout, critical-net routing, SES import, post-processing, checks, benchmark harness. These depend on Boardwright's data (PROJECT.md, stack-up), so they do not belong upstream.
- Do not fork Freerouting unless upstream stalls; a fork brings GPL obligations and merge work.

### Honest limits

- No autorouter in this research produces DDR3/DDR4-class, length-matched, timing-closed buses reliably. DeepPCB itself tells users to expect manual work on 500+ airwire boards, and its largest boards took about 14 hours. Treat DDR, dense BGAs (fine pitch), RF and motherboard-class boards as human-routed or semi-manual, with the engine providing fanout and a first attempt only. Sources: https://deeppcb.ai/pcb-autorouter-benchmark-2026/ and https://www.quilter.ai/blog/pcb-autorouting-in-2026-a-review-of-traditional-tools-vs-quilters-ai-approach
- Even a 100 percent routed board may have poor signal integrity or EMC; completion is not correctness. DeepPCB says its benchmark does not assess this either.
- For 2 and 4 layer boards with low-speed signals, Freerouting 2.5.0 is a reasonable first step, but with 75 percent clean boards on a mixed corpus, expect to fix something on roughly one board in four.

### Next steps

1. Pin Freerouting 2.5.0 and check each flag against the real binary.
2. Build the benchmark harness on three Boardwright test boards (2-layer, 4-layer USB, a 6-layer example).
3. Write the SES importer and compare it with `ImportSpecctraSES` output.
4. Try KiCadRoutingTools fanout and length tuning on a copy of a board and judge quality.
5. Open one upstream issue on Freerouting with a minimal reproducible diff-pair or BGA board.
