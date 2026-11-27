# tscircuit capacity autorouter: how it works, and what we can take from it

Target: `@tscircuit/capacity-autorouter` 0.0.1167 (MIT), npm package at
`scratchpad\rea\targets\tscircuit\package`. Read-only static analysis. The target's code was never run.

Paths below are relative to the recovered source tree
`scratchpad\rea\out\mapsrc\` (1697 original files rebuilt from `dist/index.js.map`;
407 under `lib/`, the rest are bundled `node_modules` packages, several of them tscircuit's own solver packages).

## 0. How the analysis was done (REA commands)

All run in PowerShell from `scratchpad\rea` after `$env:Path = "C:\Program Files\nodejs;" + $env:Path`.

| Command | Result |
|---|---|
| `npx -y rea-agents@latest --help` | Worked (rea 6.10.1). |
| `npx -y rea-agents@latest recover-javascript-sources --help` | First try ran OOM ("Zone Allocation failed") when started in parallel with another npx; a rerun on its own worked. |
| `npx -y rea-agents@latest analyze-javascript-application --help` | Worked. |
| `npx -y rea-agents@latest recover-javascript-sources <pkg>\dist\index.js <rea>\out\recovered --json` | **Failed**: `capability_unavailable`. It needs `REA_WAKARU_COMMAND` pointing to a Wakaru Linux x64 binary. REA installs no tools, and this task forbids installing any. |
| `npx -y rea-agents@latest analyze-javascript-application <pkg> --detail summary --evidence_output <rea>\out\app-evidence.json --max-heap-mb 3072 --json` | **Worked, but only partly.** It found 12 files and parsed 7, and wrote the evidence bundle (7.2 MB). For `dist/index.js` it stopped with "Resource constraint ... member-mutation analysis scheduled more than 524288 alias states for one source". It reported 0 modules for the bundle and 231 semantic unknowns. It did process the `.map` file's metadata. |
| `npx -y rea-agents@latest inspect-analysis-view --help` | Worked. It was not used further: the evidence for the main bundle was incomplete, so the source map was the better path. |

Fallback (allowed by the brief): a 20-line Python script (`scratchpad\rea\scripts\extract_map.py`, run with `python -I`, outside the target folder) read `dist/index.js.map` as JSON data and wrote each `sourcesContent` entry to `out\mapsrc\`. All findings below come from reading those TypeScript sources.

## 1. The pipeline (the default solver)

`dist/index.d.ts` exports `AutoroutingPipelineSolver9_PreloadedTraceGraph as AutoroutingPipelineSolver`, so **Pipeline 9 is the default**. It is defined in
`lib/autorouter-pipelines/AutoroutingPipeline9_PreloadedTraceGraph/AutoroutingPipelineSolver9_PreloadedTraceGraph.ts` (`pipelineDef`), with stage lists in `pipeline9TopologySteps.ts`, `pipeline9HighDensitySteps.ts`, `pipeline9TraceRefinementSteps.ts` and `pipeline9PostProcessingSteps.ts`.
Every stage is a `BaseSolver` subclass with `_step()`. The pipeline builds stage N+1 from stage N's output (`getConstructorParams` / `onSolved`).

| # | solverName | Class | Takes | Produces |
|---|---|---|---|---|
| 1 | preprocessSimpleRouteJsonSolver | `PreprocessSimpleRouteJsonWithoutTraceObstaclesSolver` | input SRJ (obstacles = pads/keepouts as rects, connections, layerCount, rules) | cleaned SRJ, connectivity map |
| 2 | componentDetectionSolver | `ComponentDetectionSolver` (detectors `bga`, `qfp`, `qfpThermalPad`, `soic`) | SRJ | detected component regions |
| 3 | escapeViaLocationSolver | `EscapeViaLocationSolver` | SRJ, via size, margin | SRJ with extra "escape-via:" points (scored candidates; metadata includes `targetPourKey`, meaning a via down to a pour/plane) |
| 4 | netToPointPairsSolver | `NetToPointPairsSolver2_OffBoardConnection` | SRJ | each multi-pin net split into 2-point connections (MST-like; exact method unverified) |
| 5 | topologyPlanningSolver | `MultiGraphTopologyPlannerSolver` | point pairs and components | **global free-space rectangles** from `@tscircuit/rectdiff` `RectDiffPipeline` (seed, expand, gap-fill), plus **per-component topologies** from `BgaTopologyGeneratorSolver`, `QfpTopologyGeneratorSolver`, `SoicTopologyGeneratorSolver` and `QfpThermalPadTopologyGeneratorSolver`, so regions under and around packages are pre-patterned |
| 6 | topologyMergingSolver | `TopologyMergingSolver` | global and component node groups | one list of capacity nodes (rects with `availableZ` layers) |
| 7 | nodeDimensionSubdivisionSolver | `NodeDimensionSubdivisionSolver` | nodes; `maxNodeDimension`=15 (mm), `maxNodeRatio`=6, `minNodeArea`=0.01 | nodes split so none is too long or thin |
| 8 | edgeSolver | `CapacityMeshEdgeSolver2_NodeTreeOptimization` | nodes | adjacency edges (nodes that share a border) |
| 9 | availableSegmentPointSolver | `AvailableSegmentPointSolver` | nodes, edges, trace width | **port points** on each shared edge, one copy per common layer z |
| 10 | necessaryCrampedPortPointSolver | `MultiTargetNecessaryCrampedPortPointSolver` | segments | drops cramped ports unless one is needed to reach a target |
| 11 | preloadedTraceGraphSolver | `PreloadedTraceGraphSolver` | segments, SRJ (may hold pre-routed traces) | routable ports; existing copper reserves ports |
| 12 | **portPointPathingSolver** (global routing) | `TinyHypergraphPortPointPathingSolver`, which wraps `tiny-hypergraph` (`PreparedPortPointRoutingSolver`, `SelectiveReripTinyHyperGraphSolverWithStableInitialAssignments`, `TinyHyperGraphSectionPipelineSolver`, `DuplicateCongestedPortSolver`) | ports and regions as a hypergraph | for each connection, a sequence of (port, region) hops, i.e. a **corridor with entry and exit points and layers for every node**. Output: `nodesWithPortPoints`, plus a per-node failure probability (`computeNodePfMap`) |
| 12b | (feedback) | `refinePortPointPlan()` | the global plan | if a planned layer change lands in a node with no physical via site (`splitNodesWithoutThroughViaSite`), that node is split and the pipeline **jumps back to edgeSolver**; conflicting clearance gaps are excluded and stage 12 runs again |
| 13 | uniformPortDistributionSolver | `UniformPortDistributionSolver` | node port points | port points spread evenly along each shared edge |
| 14 | **highDensityRouteSolver** (detailed routing) | `Pipeline9HighDensitySolver`, which uses `HighDensitySolver` with `PortfolioSingleIntraNodeSolver` per node; `BgaEscapeRoutingSolver` for BGA boards; `Pipeline9RegionalFallbackSolver` / `HighDensitySolverB01` as fallbacks | one node plus its port pairs | copper (trace segments and vias) **inside each node**, with vias chosen there |
| 15 | highDensityForceImproveSolver | `Pipeline9HighDensityForceImproveSolver` | HD routes | routes nudged inside nodes (`totalStepsPerNode` = max(12, 20 x effort)) |
| 16 | highDensityRepairSolver | `Pipeline4HighDensityRepairSolver` | HD routes, obstacles | local clearance repairs |
| 17 | highDensityStitchSolver | `MultipleHighDensityRouteStitchSolver3` | per-node fragments | each connection joined into one continuous route |
| 18-20 | traceSimplificationSolver, mutatedPreloadedTraceSimplificationSolver, traceWidthSolver | `TraceSimplificationSolver`, `TraceWidthSolver` | routes | simplified (fewer points; 45-degree handling is in `trace-simplification-solver`) and widened where room allows |
| 21 | globalDrcForceImproveSolver | `GlobalDrcForceImproveSolver` (package high-density-repair03) | routes and the DRC evaluator | a candidate local move (waypoint offsets of ±0.17 mm, detours, layer moves) is kept only if the DRC issue count goes down |
| 22 | pipeline9JointDrcRepairSolver | `Pipeline9JointDrcRepairSolver` | routes and DRC errors | bounded regional rip-up and repair around each remaining DRC error |
| 23 | effortCleanupSolver | `Pipeline9EffortCleanupSolver` | routes | final cleanup |
| 24 | lengthMatchingPostProcessingSolver | `LengthMatchingPostProcessingSolver` (package `@tscircuit/length-matching-solver`) | routes, `differentialPairs`, `buses` | diff pairs re-routed as coupled pairs; bus skew tuned |
| 25 | powerTraceExpansionSolver | `PowerTraceExpansionSolver` | power-net traces | wider power traces; `allowNewVias: false`, `widenInPlaceAtSearchLimit: true` |

The older pipeline is `AutoroutingPipeline1_OriginalUnravel` (the "CapacityMeshSolver" the README describes). It shows the original idea more plainly: quadtree nodes (`CapacityMeshNodeSolver2_NodeUnderObstacle`), then `SingleLayerNodeMergerSolver`, `StrawSolver`, `CapacityMeshEdgeSolver2`, `DeadEndSolver`, `CapacityPathingGreedySolver` (global A*), `CapacityPathingMultiSectionSolver` (section re-solves), `CapacityEdgeToPortSegmentSolver`, `CapacitySegmentToPointSolver`, `UnravelMultiSectionSolver` (local moves that cut crossings), `HighDensitySolver`, `NoOffBoardMultipleHighDensityRouteStitchSolver` and `TraceSimplificationSolver`.

## 2. Capacity mesh, global negotiation, and how work is bounded

**Mesh and capacity**
- Pipeline 1: a quadtree. `CapacityMeshNodeSolver1.shouldNodeBeXYSubdivided` splits a node only if it holds a target or partly overlaps an obstacle, down to `MAX_DEPTH`. `calculateOptimalCapacityDepth` (in `lib/utils/getTunedTotalCapacity1.ts`) halves the board width until a node's capacity is 0.5 or less.
- Pipeline 9: free-space rectangles (rectdiff), then a subdivision cap (15 mm, aspect ratio 6).
- **Capacity formula** (`getTunedTotalCapacity1`): `((sqrt(w*h) * clamp(minSide/(via+margin))^0.05) / (via/2 + margin) / 2)^1.1`. In words, roughly how many vias fit across the node, tuned for 2 layers. A node with only one layer has capacity 1.
- **Edge (port) capacity** (`AvailableSegmentPointSolver`): `floor(edgeLength / (traceWidth + obstacleMargin)) + 1` ports per layer. Above 5 it is compressed to `5 + floor(n/4)`. A port is held by **one net at a time** (`state.portAssignment` in `tiny-hypergraph/lib/core.ts`), so edge capacity is a hard limit.
- **Node congestion is a crossing count, not a trace count.** In `tiny-hypergraph/lib/computeRegionCost.ts`, `estViasRequired = 2*sameLayerCrossings + crossLayerCrossings + entryExitLayerChanges`, and `cost = estVias * (viaPad+0.15)^2 * (1 + traces/5) / area`. A same-layer crossing in a single-layer region costs +10, and `computeG` returns infinity for it. Crossings are found by comparing **the angles of the entry and exit ports around the region's edge** (`countNewIntersections.ts`): two chords cross if their end points interleave. This is a cheap topological test that needs no geometry.
- The node failure probability (`UnravelSolver/calculateCrossingProbabilityOfFailure.ts`) is `((0.82*sameLayerX + 0.41*layerChanges + 0.2*transitionX)/2)^1.1 / capacity`. Stage 14 uses it to decide which nodes are hard.

**Global negotiation: PathFinder-like, confirmed** (`tiny-hypergraph/lib/core.ts`, `TinyHyperGraphSolver`)
- Each connection gets an A* over (port, region) "hops": `g` += change in region cost + `regionCongestionCost[region]` (history) + port penalty; `h` = distance-based.
- After all routes are placed, `onAllRoutesRouted()` computes every region's cost. Regions above `currentRipThreshold` are "hot". The threshold **ramps from `RIP_THRESHOLD_START`=0.05 to `RIP_THRESHOLD_END`=0.8** over `RIP_THRESHOLD_RAMP_ATTEMPTS`, so it gets more tolerant over time.
- If any region is hot, **every region's history cost grows**: `regionCongestionCost += regionCost * RIP_CONGESTION_REGION_COST_FACTOR (0.1)`. Then all routes are ripped up and rerouted in a new order, `shuffle(routeIds, ripCount)`, a seeded shuffle.
- `onOutOfCandidates()` (a route cannot be found) does the same.
- The best solved state so far is kept (`captureBestSolvedState`, compared by max region cost, then total). With `ACCEPT_BEST_SOLUTION_ON_TIMEOUT` = true, the solver returns that best state when it runs out of iterations.
- Then `GREEDY_FINAL_ROUTE_ITERS` = 4 greedy re-solves from the best snapshot.
- Partial rip-up: in Pipeline 9 config (`TinyHypergraphPortPointPathingSolver.ts`), `PARTIAL_RIP_MIN_ROUTE_COUNT` 100, `PARTIAL_RIP_MAX_ROUTE_COUNT` 350, `PARTIAL_RIP_MAX_ATTEMPTS` 7, `PARTIAL_RIP_MAX_DISTANCE` 12. When more than about 100 routes exist, only routes near hot regions are ripped, with guards on cost growth (`..._MAX_REGION_COST_GROWTH_RATIO` 0.05 and `..._TOTAL_...` 0.1).
- `TinyHyperGraphSectionPipelineSolver` then takes the hottest regions (`MAX_HOT_REGIONS`) and re-solves a small **section** around each one. A section result is accepted only if max region cost improves.
- `DuplicateCongestedPortSolver` duplicates heavily used ports (within 0.05 mm) and records search iterations per connection to find badly placed parts.
- `STATIC_REACHABILITY_PRECHECK` (16 hops) reports connections that cannot be routed at all before any search starts.

**Bounds and determinism**
- All budgets count **iterations, not wall time**:
  - `BaseSolver.step()` fails a solver when `iterations > MAX_ITERATIONS`.
  - Pipeline `MAX_ITERATIONS = 100e6 * effort`.
  - Global routing `MAX_ITERATIONS = ceil(2,000,000 * effort * max(1, floor(portCount/125,000)))`; the budget scales with graph size. `RIP_THRESHOLD_RAMP_ATTEMPTS = ceil(10 * effort)`.
  - Sections: `1,000,000 * effort`, 16 ramp attempts.
  - Single HD route A*: `MAX_ITERATIONS = 10e3`.
- `performance.now()` and `Date.now()` appear only in timing stats (`timeSpentOnPhase`, `...TimeMs`) and in UI yields. I found no wall-clock deadline in the stages I read. I did not read every one of the 1697 files, so "no time limit anywhere" is unverified.
- No `Math.random` anywhere in `lib/`. Shuffles use `seededRandom` (xorshift128+) in `lib/utils/cloneAndShuffleArray.ts`, plus fixed pre-shuffled orders for arrays of 4 or fewer items, with the seed = rip count or the portfolio `SHUFFLE_SEED`.
- With `solveAsync(runtime)`, high-density nodes run in parallel batches (`Pipeline9HighDensityBatchSolver`: "Evaluate an independent serial batch; the parent owns ordered outcome acceptance"), so **results are committed in a fixed order** whatever finishes first.
- **effort** is the single knob that scales every budget.

## 3. Detailed routing inside a node ("high density")

- `HighDensitySolver` takes nodes one at a time (`unsolvedNodePortPoints.pop()`). For each one it builds a `PortfolioSingleIntraNodeSolver` (`lib/solvers/HyperHighDensitySolver/`), or `GrowShrinkHighDensityIntraNodeSolver` when that option is on.
- **The portfolio is a "best-first search over solvers"** (`HyperParameterSupervisorSolver`). Candidate solvers are hyper-parameter combinations:
  - `singleLayerNoDifferentRootIntersections`
  - `majorCombinations` (FUTURE_CONNECTION_PROX_TRACE/VIA_PENALTY_FACTOR, PROXIMITY_VD)
  - `orderings6` and `orderings50` (SHUFFLE_SEED 0..5 and 100+)
  - `cellSizeFactor`, `flipTraceAlignmentDirection`, `noVias`, `throughObstacle`
  - `closedFormSingleTrace`
  - `multiHeadPolyLine` (force-based poly-line solver with via possibilities)
  - `highDensityA01/A03/A13` (separate packages)

  Each step advances the candidate with the lowest `f = iterations/MAX_ITERATIONS + GREEDY_MULTIPLIER * (1 - progress)`. The first solved candidate that passes `candidateValidator` (DRC check) wins.
- The base unit, `SingleHighDensityRouteSolver`, is a **grid A* inside the node**:
  - `cellStep` = 0.05 mm, doubled while the grid is too big, then times `CELL_SIZE_FACTOR`.
  - A **layer change is a via move**, with `viaPenaltyDistance = cellStep + straightLineDistance * VIA_PENALTY_FACTOR (0.3)`.
  - Clearance checks: `isNodeTooCloseToObstacle` uses `traceThickness + margin` for traces and `viaDiameter/2 + traceThickness/2 + margin` for vias, and `isNodeTooCloseToEdge` checks the node's edge.
  - Connections in a node are routed one after another. Routes still to come add a "future connection" proximity penalty, so early routes stay away from later terminals.
- **Layers**: the global stage already fixes the entry and exit layer for every node, because ports are per layer. Inside a node, A* only decides where the via goes. `refinePortPointPlan` goes back and splits nodes when a planned via has no room. `EscapeViaLocationSolver` pre-places pad escape vias, including to pours. Blind and buried vias are passed through as `allowBlindAndBuriedVias`.
- **Caching**: `CachedIntraNodeRouteSolver` and `serializeIntraNodeCacheKey` cache node solutions in memory under a normalized key. Pipeline 5 (`HdCache`) and Pipeline 9 Networked (`HdCache2Client`, `DEFAULT_HD_CACHE2_SERVER_URL`) can fetch solutions from a remote server. The default Pipeline 9 uses only the in-memory cache, as far as I read.
- **BGA**: when board BGA input exists, `Pipeline9HighDensitySolver.initializeBgaEscapeRouting` runs `BgaEscapeRoutingSolver` (`@tscircuit/bga-escape-routing-solver`: `BgaRoutingGrid`, `BgaTrackSearch`, `findTerminalEscape`). If that returns complete board routes (`completedBoardRoutes`), the pipeline skips straight to power-trace expansion. There is also a separate `AutoroutingPipeline10_BgaFanout` and a `@tscircuit/fanout-solver` package.
- **Differential pairs**: there is no coupled routing in the global stage. Pairs are routed as two separate nets and then re-routed as a pair **after** routing, in `LengthMatchingPostProcessingSolver`, via `@tscircuit/length-matching-solver`'s `DifferentialPairRoutingSession`:
  - `IncrementalCoupledPathSearch` with edge-gap samples [0.75, 0.5, 1, 0.25, 1.25] x gap, both sides tried.
  - Centerline distance penalty of 100 per mm.
  - `simplifyDifferentialPairTo45Degrees`.
  - Input: `DifferentialPair {connectionNames, lengthTolerance, traceGap, maxUncoupledLength}`.
- **Buses**: `SimpleRouteBus {connectionNames, maxLengthSkew, traceWidth, allowedLayers}`, used for length matching. The README says bus metadata "is preserved in the output so routing implementations can apply the constraint", which suggests buses are only partly enforced. That reading is unverified. `tiny-hypergraph/lib/bus-solver/TinyHyperGraphBusSolver.ts` exists, but I did not confirm it is in the default path.
- **Widths and clearances**: routing uses one `minTraceWidth`, plus `defaultObstacleMargin` (0.15), `minTraceToPadEdgeClearance`, `minViaEdgeToPadEdgeClearance`, `minPadEdgeToPadEdgeClearance` and `minViaHoleEdgeToViaHoleEdgeClearance`. Width per net happens only afterwards (`TraceWidthSolver`, `PowerTraceExpansionSolver`). There are no net classes during search.

## 4. Scale tested, and known limits

- Datasets in `package.json` devDependencies (git pins), contents not read:
  - dataset-srj05, srj11-45-degree, srj12-bus-routing, srj13, srj16-bga-breakouts, srj18, srj19-bga-passive-overlays, srj20-partial-bga-breakouts, srj23-partially-routed-subcircuits, srj24, srj27-power-traces, srj28-partially-prerouted, srj29-ddr3-bga-pairs, srj33-drc-failures
  - autorouting-dataset-01, high-density-dataset-z04, multi-component-dataset-srj01, zdwiel-dataset
- README: a benchmark dashboard, and SRJ33 = 37 inputs that still had DRC issues under Pipeline 9.
- Scale hints in code: the global budget grows per **125,000 ports** (`graphScale`). Partial rip-up starts at 100 or more routes. `enableLargeBoardBroadFallback` exists in `GlobalDrcForceImproveSolver`.
- **No evidence of tests at our scale** (2946 connections, 10 layers). Board sizes and connection counts in the datasets are unverified. The DDR3 BGA dataset is the closest match to a dense board.

Known limits, from the code:
1. Region cost assumes about 2 layers (`countAvailableLayers` defaults to 2; capacity is "tuned for two layers").
2. Diff pairs are coupled only in post-processing.
3. Routing uses one trace width.
4. Rip-up is all-or-nothing below 100 routes.
5. Many stages exist only to repair DRC errors after the fact (stages 15, 16, 21, 22), which suggests the detailed router often breaks clearance.
6. The HD solver fails the whole stage if any node fails (`Failed to solve N nodes`), unless the Pipeline 9 regional fallback catches it.
7. TODOs say `TwoCrossingRoutesHighDensitySolver` needs to "support more layers".

## 5. Ideas for KiCadRoutingTools (A* grid) + Freerouting

The work estimates are my own judgment, not measured.

1. **Global corridor assignment before detailed A*** (the biggest win for the 2946- and 1345-connection boards).
   - Build a coarse region graph: free-space rectangles from pads and keepouts per layer, or start simply with a quadtree or fixed tiles. Put "ports" on shared edges with capacity `floor(len/(w+clr))+1` per layer.
   - Run negotiated A* on it: per-region cost from crossing counts (chord-interleave test), a history cost that grows by 0.1 x cost each round, seeded order shuffles, a rip threshold that ramps up, and keep the best state.
   - Then limit the KiCadRoutingTools A* for each net to its corridor (the cells of its regions plus a margin) and its fixed entry and exit layers.
   - This turns one huge search into many small, bounded ones, and lets us find "impossible" connections early (static reachability).
   - Work: about 2-4 weeks for a first version in Python with NumPy; a native or numba core is advisable above about 100k ports.
2. **Iteration budgets plus seeded randomness instead of wall-clock limits** (fixes run-to-run variance).
   - One `effort` scalar sets every limit: A* node expansions, rip rounds, per-node attempts.
   - Seed every shuffle from (round, net index). Commit parallel results in a fixed order.
   - For Freerouting, use a fixed pass count where its CLI allows; how far Freerouting can be made deterministic is unverified.
   - Work: about 3-5 days.
3. **Parallel detailed routing per region with a portfolio of settings.** Once corridors fix entry and exit points, regions are independent. Route each region in a worker with a few settings (orderings 0..5, via penalty, cell size) and run the most promising first. Cache solutions by a normalized region key. Work: about 1-2 weeks on top of idea 1.
4. **Component-aware escape templates (BGA, QFP, SOIC) before global routing.** Detect grids of pads, pre-pattern escape regions (dog-bone vias placed by template, channel per row), and pre-place escape vias to planes for power pins (`EscapeViaLocationSolver` with `targetPourKey`). These become fixed inputs for global routing. Work: about 1-2 weeks for BGA dog-bone plus via-to-plane; more for fine-pitch QFP.
5. **DRC-guided local repair loop instead of a full rerun.** Run KiCad DRC, rip up only the nets within a small region around each violation, reroute them with history costs, and keep the change only if the DRC count drops (the Pipeline 9 joint DRC repair and force-improve pattern). Do the same for the ~145 and ~1400 open connections: reroute inside a growing window around each one instead of a full Freerouting pass. Work: about 1-2 weeks.

Do **not** copy their diff-pair approach (coupling only after routing). For our boards, route the pair as one wide "virtual trace" (width = 2w + gap) in the global and detailed stages, then split it. That is our own design, and nothing in the tscircuit code confirms it.
