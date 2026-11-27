# Open-source routers for large dense KiCad boards: findings (research date 2026-11-27)

Method: web search and page reads only (nothing installed or run). "unverified" = not confirmed from a page I read. Numbers are quoted from the cited pages; some page text was summarised by the scraper's extraction step, so re-check any number before relying on it.

## 0. Headline findings

1. Freerouting 2.6.0 was released 25 Nov 2026 (two days ago); the project runs 2.5.1. Release notes claim large gains on the PCBench corpus (see 1.2). Cheapest experiment available. The same notes say total corpus time went UP (6,457 s to 13,463 s), so it does more work per board.
2. The only independent head-to-head of routers on real KiCad boards is PCBWorld (arXiv 2607.05915, KDD 2026 workshop, GitHub LGAI-Research/PCBWorld). Freerouting beat KiCadRoutingTools and OrthoRoute on every split I saw; the large-board split (D3-C, 26-451 nets) had no router rows in the table I read. It is small and medium board evidence only.
3. No open-source router I found has been shown on a 10-layer, ~3000-connection BGA board. Nothing off the shelf will fix jetson. The realistic path is (a) newer Freerouting, (b) borrowing PathFinder / global-routing ideas into our own orchestration, (c) a deterministic benchmark harness so we can measure instead of guessing at 30-50% run noise.
4. KiCad's PNS router is not exposed through the IPC API as a routing call that I could confirm. PCBWorld wraps it via a separate GPLv3 "PCBWorld-Engine" submodule (details unverified).
5. Dense small boards (royalblue) are a fanout/escape problem more than a general router problem. KiCadRoutingTools has a BGA/QFN fanout package we may be underusing (section 1.1).

## 1. Candidates

### 1.1 KiCadRoutingTools (KRT): already used; features we may not use
- URL: https://github.com/drandyhaas/KiCadRoutingTools  License: MIT  Language: Python + Rust core (prebuilt binaries for Linux/macOS/Windows)
- Last activity: very active (README references issue numbers above #1700; exact last commit date unverified). KiCad 9 and 10.
- Headless on KiCad file: yes, native .kicad_pcb in and out (`py_router/autoroute.py in.kicad_pcb out.kicad_pcb`, `--dry-run` prints the plan).
- Scale shown: README performance table is old (Jan 2026; e.g. 47/47 nets in 8.6 s, 28 LVDS pairs in ~30 s) and says to read it as orders of magnitude. Maintainer says a corpus of real open-source boards is replayed on rented cores (Modal) for A/B tests. No published jetson-class number found (unverified).
- DRC-awareness: strong. Design rules resolved in KiCad's own order (pad overrides, net classes, .kicad_dru rules, board setup); keep-outs, Edge.Cuts, BGA exclusion zones; checkers check_drc.py / check_connected.py; writes routed floors into .kicad_pro.
- Diff pairs: yes. Pose-based A* with Dubins heuristic, polarity swap, impedance widths, length/time matching.
- Features we may not be using (from its README; check against our wrapper):
  - `autoroute.py` one-shot planner (plans plane pours, fanouts, decap clearance, diff pairs, route passes from the board's own rules). Our ">30 min setup" may be one stage of this; worth profiling which stage dominates.
  - `bga_fanout.py` / `qfn_fanout.py`: escape methods auto / channel / under-pad / dog-bone, "under-pad for dense fully-populated BGAs (issue #122)", diff-pair aware, plane-net ball drops. Directly relevant to royalblue (fine-pitch BGA/WLCSP) and the jetson module connector.
  - `route_planes.py`, `repair_planes.py` and in-run plane finalize (pours planes, welds pads, region joins).
  - `kicad_oracle.py`: "routes the exact links KiCad's own connectivity reports as unconnected": a closing pass on leftovers.
  - `net_rescue.py` (retry failed nets at finer parameters) and `finer_grid_rung.py` (re-route boxed-in nets at half grid with rip authority, under a cell budget).
  - Net ordering strategies: MPS (crossing-aware), inside-out, bus-first; MPS layer swaps. `target_swap.py` (Hungarian target assignment), `polarity_swap.py`.
  - `improvement_gate.py`: never ships a board that regressed connectivity (same philosophy as our DRC-clean-only rule).
  - `route_diff.py`, `--via-span` (blind/buried, one span per step), guide corridors and keep-out zones drawn on a User layer (a way to inject a global-routing plan), `make_plan.py` / `run_plan.py` (routing chains as JSON), `KICAD_ROUTE_TRACE=1` + `route_movie.py` for debugging runs.
- Documented limitations (README): no push-and-shove; no coarse grid assignment / global routing before detailed routing; micro/blind/buried vias only one span per step.
- PCBWorld result (small boards, default settings): D3-A clean-pass 0.74 / routability 0.94; D3-B (31-100 pads) clean-pass 0.20 / routability 0.86, versus Freerouting 0.78 / 1.00. So KRT leaves more DRC problems on medium boards in that test (how well tuned is unverified).
- Verdict: KEEP and use more of it (fanout, kicad_oracle, net_rescue, finer_grid_rung, guide corridors). Its missing global-routing stage is the gap we could fill ourselves.

### 1.2 Freerouting (upstream): 2.6.0 available
- URL: https://github.com/freerouting/freerouting  License: GPL-3.0 (not confirmed on a page I read; commonly known)  Language: Java
- Last activity: v2.6.0 on 25 Nov 2026; v2.5.0 on 5 Oct 2026 (releases page).
- Headless: yes (DSN in, SES out; CLI flags; also an API mode; a "KiCad IPC extension mode" is being worked on per discussion #932).
- Release-note numbers (PCBench corpus; 1,157 real boards for 2.5.0, 1,142 for 2.6.0, so the sets differ):
  - 2.5.0 vs 2.4.1: clean boards 30.9% to 75.0%; Tier B (560 routine boards) clean 3.4% to 61.6%; Tier C (122 complex / multilayer) clean 14.8% to 49.2%; Tier D (22 large stress boards) clean 0/22 to 11/22, fully routed 4/22 to 11/22.
  - 2.6.0 vs 2.5.0: clean 63.5% to 90.0% (725 to 1,028 of 1,142); Tier C clean 26.2% to 80.9%; Tier D clean 0% to 31.8%, ten Tier D boards still time out; timeouts 3 to 14 of 1,142; total corpus time 6,457 s to 13,463 s.
  - The 2.5.0 baseline in the 2.6.0 notes (63.5% clean) differs from the 2.5.0 notes (75.0% clean), so the two runs used different setups or limits. Treat the gain as directional.
- Tier D "large stress boards" is the closest public thing to our jetson case; even 2.6.0 times out on 10 of 22.
- Multi-threading: single-threaded router and optimizer by default (determinism); multithreading listed as a later focus. Issues #936 "Multiple routing solutions at once" and #1131 "GPU/iGPU accelerated BGA escape fanout" are feature requests (status unverified).
- Known quirk (release notes): KiCad DSN export omits board-edge clearance; pass `--router.copperToEdgeClearanceUm=500` or match your design rules.
- Verdict: ADOPT 2.6.0 as a drop-in trial on video, royalblue and jetson with the same time budget and DRC gate. Low effort, real upside. Caveat: slower per board.
- Forks: https://github.com/32bitmicro/Freerouting appeared in search (an older community fork of the original by Alfons Wirtz; activity unverified, probably stale). No actively maintained fork with large-board gains found; upstream is the active line. Verdict on forks: skip.

### 1.3 OrthoRoute
- URL: https://github.com/bbenchoff/OrthoRoute  License: MIT  Language: Python (99.1%), CUDA via CuPy or Apple Metal. KiCad 10 IPC plugin.
- Last activity: repo commit around 21 Oct 2026 (merged PR #27); release v1.0.0 on 30 Jul 2026.
- Headless: partly. KiCad must be running to export an .ORP file from the plugin; `python main.py headless board.ORP` then runs without KiCad (GPU or `--cpu-only`) and writes an .ORS to import via the plugin. A recent commit shows an outside user driving headless mode (env-settable cost knobs). A fully KiCad-free .kicad_pcb in/out flow is unverified.
- Scale shown: its own golden regression is a 512-net backplane, 512/512 routed, zero overuse, 18.4 min (10 Apr 2026). README targets backplanes with thousands of nets; no jetson-like numbers.
- Algorithm: PathFinder negotiated congestion on a Manhattan lattice (horizontal-only on one layer, vertical-only on the next), blind/buried vias, CUDA parallel Dijkstra per net; nets still routed one after another.
- DRC-awareness: weak/partial (keep-out support added in a merged PR; net classes and per-net widths unverified). Diff pairs: not found.
- Author's own caution: "not a general-purpose PCB autorouter". PCBWorld: clean-pass 1-2% on D2/D3-A and 0% on D3-B, routability 0.34-0.53 (the README says that used small boards and defaults, not its intended workload).
- Needs an NVIDIA CUDA 12 GPU or Apple Silicon (user's hardware unknown).
- Verdict: BORROW IDEAS (PathFinder history-cost negotiation, ROI batching). Do not adopt as is: lattice routing will not be DRC-clean around fine-pitch parts without a cleanup stage.

### 1.4 Topola
- URL: https://codeberg.org/topola/topola (site https://topola.dev)  License: open source, REUSE-licensed (exact SPDX unverified)  Language: Rust (91%)
- Last activity: README commit 2 Jul 2026; code commits to Mar 2026 visible (1,365 commits, no tags, "work in progress"). NLnet funded.
- Headless: yes, "GUI application and headless command-line tool". Imports Specctra DSN (repo has docs on exporting DSN from KiCad and LibrePCB, Mar 2026). Output format unverified.
- Scale: no large-board results found (unverified).
- Algorithm: topological (rubber-band) router, not tied to a grid or 45 degrees. Multilayer maturity unverified (a Nov 2025 commit renames "single_layer" to "unilayer").
- DRC-awareness, net classes, vias, keep-outs, diff pairs: unverified.
- Verdict: SKIP for production, WATCH. Revisit when it publishes multilayer results.

### 1.5 tscircuit autorouter
- URL: https://github.com/tscircuit/tscircuit-autorouter (plus tscircuit/autorouting dataset and tscircuit/autorouter-benchmark-dashboard)  License: MIT  Language: TypeScript
- Last activity: 26 Nov 2026.
- Headless: yes as a Node library; input is its own SimpleRouteJson (layerCount, allowedLayers, obstacles, connections). No KiCad importer found; we would write converters both ways.
- Algorithm: capacity mesh, hypergraphs, successive approximation, multi-phase pipeline (global then high-density detail).
- Scale/benchmark: public dataset and dashboard exist; pass rates not read (unverified). Large dense boards unverified.
- DRC, net classes, diff pairs, keep-outs: unverified.
- Verdict: BORROW IDEAS (capacity-mesh global routing, benchmark dashboard). Skip as engine: integration cost, no dense-board evidence.

### 1.6 KiCad PNS (push and shove) and driving it headlessly
- Source: KiCad (GPL-3.0), C++ (pcbnew router).
- Not exposed as a batch autorouter. The IPC API documentation page I read showed no routing/PNS call (the page was thin; unverified for KiCad 10).
- PCBWorld shows it can be driven programmatically: "agent reaches KiCad's PNS router through a thin Python wrapper exposing 58 step-level methods" (move head, fix_route, finish, push_n_shove mode). The engine ships as the separate PCBWorld-Engine submodule (GPLv3). How it runs (patched KiCad build? headless?) is unverified. It routes one trace session at a time.
- A r/KiCad post (1v984s6) describes an open-source MCP server that lets agents route in a live KiCad session over the IPC API using Push and Shove; the scraper could not read it (mechanism unverified). Another hit, "openkonnect" (MIT, drives a running KiCad 10), details unverified. The boardwright kicad-live tools already have kicad_run_action, which may fire router actions in a live GUI session; this needs a running KiCad and is not a bulk router.
- Scale: PNS is for one net at a time; 2,946 connections one by one would be slow, but it is the only tool that pushes existing copper aside (KRT cannot; Freerouting shoves internally).
- Verdict: BORROW IDEAS for a "last mile" repair of leftover connections (PNS finish with shove on each open ratsnest line), only after a stable headless driving path is confirmed. PCBWorld-Engine is the lead to read next.

### 1.7 Horizon EDA
- URL: https://github.com/horizon-eda/horizon  License: GPL-3.0  Language: C++.
- Its interactive router is derived from KiCad's PNS (LibrePCB forum thread names the lineage). Not a batch autorouter; own file format; no routing import of .kicad_pcb confirmed. Verdict: SKIP.

### 1.8 pcb-rnd / gEDA toporouter
- pcb-rnd (GPL) carries a topological autorouter descended from gEDA/PCB's toporouter. My search returned nothing on it, so no evidence gathered this session; from general knowledge it handled small boards only. Unverified. Verdict: SKIP.

### 1.9 LibrePCB
- https://github.com/LibrePCB/LibrePCB  License: GPL-3.0  Language: C++/Qt. No autorouter. Issue #1537 proposes extracting KiCad's push-and-shove router as a standalone library; status unverified. Verdict: SKIP.

### 1.10 ML and commercial routers
- DeepPCB (deeppcb.ai) and Quilter (quilter.ai): closed commercial cloud services. SKIP.
- PCBWorld (LGAI-Research): open RL / LLM environment on KiCad PNS (engine GPLv3). PPO trained on synthetic 2-layer boards: D3-A clean-pass 0.86 / routability 0.95; D3-B 0.45 / 0.85, versus Freerouting 0.80 / 0.91 on D3-A and 0.78 / 1.00 on D3-B. No evidence on large boards. LLM agents (GPT-5.4 family, Qwen3.5-397B): D3-B clean-pass 0.00. SKIP as engine; USE as benchmark; read for PNS driving.
- kicad-tools (PyPI, LLM reasoning agent + MCP): details unverified. SKIP.
- A Quilter blog says an LLM agent that operated KiCad handed routing to Freerouting in public tests; no learned router currently beats Freerouting on real boards in anything I read.

## 2. Academic approaches that scale (ideas to borrow)

- PathFinder / negotiated congestion (McMurchie and Ebeling, FPGA routing; OrthoRoute is the PCB instance; ASPDAC 2023 FPGA router confirms the modern two-phase form): route every net ignoring conflicts, then iterate with rising present-congestion cost and a history cost, ripping up only congested nets. Why relevant: Freerouting and KRT are sequential rip-up and reroute under wall-clock limits, which fits our 30-50% variance; negotiation converges more deterministically if bounded by iterations instead of seconds. Cost: needs a shared-resource routing graph, so it is a build, not a wrapper.
- Global routing then detailed routing (standard VLSI flow; course chapter at cc.ee.ntu.edu.tw/~ywchang/Courses/PD_Source/EDA_routing.pdf; the FPGA paper restricts detailed search to global-route corridors and grows them when stuck): partition into tiles, assign each net a tile path under capacity, route in detail inside corridors. This is exactly KRT's stated gap ("no coarse grid assignment"). KRT accepts guide corridors drawn on a User layer, so a global planner of ours could feed per-net corridors without patching KRT. Corridors also shrink the search space, a plausible cause of the >30 min jetson setup (cause unverified).
- BGA escape routing via network flow / ordered escape: "A network flow approach for simultaneous escape routing in PCB" (ResearchGate 320971533), multi-terminal escape with negotiated congestion (UC Riverside, VLSI-SoC 2014), and a 2026 genetic-algorithm ordered-escape paper (MDPI Applied Sciences 16(4):2010). Apply to jetson's BGA-style module connector and the royalblue BGAs: solve pin-to-layer and exit assignment as a flow problem, emit fanout stubs and vias, then route the rest. Gain unverified; no open implementation found (KRT bga_fanout is nearest).
- Net ordering and rip-up heuristics (textbook; MPS crossing-aware ordering already in KRT).
- Reproducibility: count work in passes or expansions, not wall seconds (KRT max_iterations counts A* expansions; Freerouting -mp counts passes); log CPU load; run several seeds per board.

## 3. Benchmark suites of real boards

| Suite | What | Size | Notes |
|---|---|---|---|
| PCBench (He et al. 2024, https://github.com/PCBench/PCBench) | open-source real KiCad boards, raw/processed .kicad_pcb, routing descriptions, RL env | 1,157 fixtures used by Freerouting's harness | Freerouting tiers A-D (A 453 easy, B 560 routine, C 122 complex multilayer, D 22 large stress) |
| Freerouting PCBench report | https://freerouting.org/benchmarks ; repo scripts/benchmark/results/benchmarks.md | per-board logs | ready regression harness and tier definitions |
| PCBWorld-Bench (arXiv 2607.05915) | 679 DRC-clean KiCad 9 boards derived from PCBench, plus synthetic D1/D2 | D3-A 99 boards (2-13 nets), D3-B 287 (5-42 nets), D3-C 292 (26-451 nets, 101-2,103 pads, 2-8 layers) | scored by KiCad DRC: routability and clean-pass |
| OmniRouting (arXiv 2608.04434) | 1,681 real schematic-coupled boards with human reference routing, for LLM evaluation | 77.24K placement instances | not designed for classic routers |
| CADET (arXiv 2611.16913) | PCB routing instance construction | unverified | seen in search hit only |
| tscircuit autorouting dataset | small routing problems | unverified | different input format |
| KRT stress harness (tests/stress/run_queue.sh) | replays real boards, grades DRC and unconnected nets | unverified | in its repo, may be reusable |

Gap: none of these has a board in the jetson class (10 layers, 2,946 connections, BGA connector). Our own boards (jetson, video, royalblue) are the realistic regression set; add PCBench Tier D (22 boards) as an external check.

## 4. Verdict table

| Candidate | Verdict | Reason |
|---|---|---|
| Freerouting 2.6.0 | ADOPT (trial) | new release claims big gains on complex/stress tiers; drop-in |
| KiCadRoutingTools (more features) | ADOPT more | fanout, kicad_oracle, net_rescue, finer_grid_rung, guide corridors unused |
| OrthoRoute | BORROW IDEAS | PathFinder idea is right; lattice and GPU wrong for fine pitch |
| tscircuit autorouter | BORROW IDEAS | capacity-mesh global routing; no KiCad path |
| Topola | SKIP / WATCH | WIP, small-board scale |
| KiCad PNS | BORROW IDEAS (cleanup) | only true push-and-shove; headless path unconfirmed |
| PCBWorld engine and bench | USE as benchmark; read for PNS driving | GPLv3 engine; learned agents not competitive on large |
| Horizon EDA | SKIP | router is KiCad PNS in another app |
| pcb-rnd toporouter | SKIP | unverified |
| LibrePCB | SKIP | no autorouter |
| DeepPCB, Quilter | SKIP | closed |
| Freerouting forks | SKIP | upstream is active |

## 5. Suggested experiments, cheapest first
1. Run Freerouting 2.6.0 on royalblue, video, jetson with the same flags and time budget as 2.5.1 and the same DRC gate; record open nets, passes, time per pass.
2. Make runs reproducible: bound by passes/expansions, log CPU load, 3 repeats per board to quantify the spread.
3. Profile KRT's >30 min jetson setup by stage (parse, obstacle map, planning, fanout). If it is the obstacle map, route by region/tile.
4. Run KRT bga_fanout (auto / under-pad) before general routing on royalblue and the jetson connector.
5. Prototype a coarse global router (tile graph, negotiated congestion) that emits guide corridors for KRT.
6. Read PCBWorld-Engine to learn how it drives PNS; prototype a PNS finish pass on leftover ratsnest lines of video.

## 6. Unverified items
- Exact licenses of Topola, Freerouting (GPL-3 assumed), pcb-rnd, kicad-tools.
- Whether KiCad 10's IPC API exposes any routing/PNS call; how PCBWorld-Engine drives PNS and whether it needs a GUI.
- Topola multilayer support, SES output, diff pairs, net classes.
- OrthoRoute net-class and diff-pair support; whether a fully KiCad-free flow exists.
- tscircuit benchmark pass rates and board scale.
- pcb-rnd toporouter state; any open implementation of BGA network-flow escape.
- Freerouting release-note numbers were read through an extraction step; confirm at https://github.com/freerouting/freerouting/releases before quoting.
- KRT last commit date and any jetson-scale measurement.
