# tscircuit capacity autorouter: four ideas as implementation specs for our engine

Follows `tscircuit-rea.md` (same folder). Target: `@tscircuit/capacity-autorouter` 0.0.1167 (MIT).
Static reading only. The target's code was never run, nothing was installed, and no config was changed.

Paths are relative to the recovered source tree `scratchpad\rea\out\mapsrc\`. Short names:
- `THG` = `node_modules/tiny-hypergraph/lib/`
- `P9` = `lib/autorouter-pipelines/AutoroutingPipeline9_PreloadedTraceGraph/`
- `HDR3` = `node_modules/high-density-repair03/lib/solvers/GlobalDrcForceImproveSolver/`
- `BGA` = `node_modules/@tscircuit/bga-escape-routing-solver/lib/bga-escape-routing/`

Anything marked **unverified** was not confirmed in code. Run-time and work estimates are my own judgment, not measured.

## 0. REA commands this session

All runs: PowerShell, `$env:Path = "C:\Program Files\nodejs;" + $env:Path`, working folder `scratchpad\rea`, one command at a time, with a free-memory check before each one.

| # | Free RAM before | Command | Result |
|---|---|---|---|
| 1 | 1.19 GB | (none) | Below the 1.3 GB limit, so I read the sources directly. |
| 2 | 2.54 GB | `npx -y rea-agents@latest trace-javascript-semantics --help` | Worked. The command needs a workflow JSON plus an `--evidence-bundle` from an earlier analysis. |
| 3 | 2.13 GB | `npx -y rea-agents@latest analyze-javascript-application out\slices\detectors --detail summary --evidence_output out\slices\detectors-evidence.json --max-heap-mb 700 --json` (slice = the 8 `.ts` files of `lib/solvers/ComponentDetectionSolver/`, copied as data) | **Worked.** REA parses TypeScript: 8 of 8 files parsed, 0 parse failures, 4304 AST nodes, 97 findings, 0 modules, 1613 semantic unknowns. Evidence bundle: 5.4 MB. The summary covers application structure (imports, Electron, IPC, requests). It did not surface constants or the algorithm, so reading the sources was still needed. |
| 4 | 0.61 GB | planned: same command on `out\slices\hypergraph-core` (`core.ts`, `computeRegionCost.ts`, `countNewIntersections.ts`, `shuffle.ts`) | **Not run**, because free RAM was below 1.3 GB. I read these files directly. |

No REA run hit an out-of-memory error or a resource limit this session. Everything below comes from reading the recovered `.ts` sources.

---

## A. Global corridor routing (tiny-hypergraph)

### A.1 Which solver Pipeline 9 actually runs

`P9/getPipeline9PortPointPathingInput.ts` sets three flags: `USE_SELECTIVE_RERIP_ROUTING: true`, `USE_PREPARED_PORT_POINT_ROUTING: true` and `USE_PARTIAL_RIP_ROUTING_WITH_PRELOADED_TRACES: true`. Because of these, `TinyHypergraphPortPointPathingSolver.ts` (in `lib/solvers/PortPointPathingSolver/tinyhypergraph/`) replaces the `solveGraph` stage with `PreparedPortPointRoutingSolver`.

The class chain, each line extending the one below it:
```
PreparedPortPointRoutingSolver                       (THG/prepared/; dense workspace, a speed path)
 └ SelectiveReripTinyHyperGraphSolverWithStableInitialAssignments (keeps preloaded copper on full rerip)
    └ SelectiveReripTinyHyperGraphSolver             (THG/selective-rerip-tiny-hyper-graph-solver.ts)
       └ OutsideInPartialRipTinyHyperGraphSolver     (THG/outside-in-partial-rip-tiny-hypergraph-solver.ts)
          └ DistanceAwareTinyHyperGraphSolver         (ADD_SEGMENT_DISTANCE_TO_G = true; IndexedCandidateHeap)
             └ TinyHyperGraphSolver                    (THG/core.ts)
```

Three corrections to the earlier report:
1. **Partial rip-up is on only for 100 to 350 routes.** `getTinyHyperGraphPipelineInput` sets `PARTIAL_RIP_ENABLED: false` outside `[PARTIAL_RIP_MIN_ROUTE_COUNT=100, PARTIAL_RIP_MAX_ROUTE_COUNT=350]`. For our 478, 1345 and 2946 connection boards, tscircuit would use full rip-up with history plus selective (blocker) rip-up, not partial rip-up.
2. **The hot-region section search is skipped in Pipeline 9.** The section stage gets `createSectionMask: ({ topology }) => new Int8Array(topology.portCount)`, an all-zero mask, so `findBestAutomaticSectionMask` is never called. What the section solver does with an empty mask is unverified; it probably does nothing.
3. **Port count per edge.** `AvailableSegmentPointSolver.ts` computes `n = max(1, floor((len - 2*edgeMargin)/minPortSpacing) + 1)`, where `minPortSpacing = traceWidth + obstacleMargin` (`obstacleMargin` defaults to 0.15) and `edgeMargin = minPortSpacing*3/4`. If `n > 5`, then `n = 5 + floor(n/4)`. There is one copy per common layer z. A zero-length edge yields a single "cramped" port only if `shouldReturnCrampedPortPoints` is set.

### A.2 Data structures (`THG/core.ts`)

Topology, `TinyHyperGraphTopology`. Everything is a flat typed array:
- `regionIncidentPorts[r]`: the ports on region r's boundary.
- `incidentPortRegion[p]`: the regions on each side of port p, at most 2.
- `regionWidth`, `regionHeight`, `regionCenterX/Y`.
- `regionAvailableZMask[r]`: a bitmask of usable layers. 0 means unknown, which is treated as 2 layers.
- `regionViaAreaFraction[r]`: the share of the region where a via fits. Only the via term of the cost uses it.
- `portX`, `portY`, `portZ`.
- `portAngleForRegion1/2[p]`: the port's position along the region's perimeter as an integer from 0 to 36000. Computed by `computePortAngle` in `THG/compat/loadSerializedHyperGraph.ts`: right side `t*9000`, top `9000 + t*9000`, left `18000 + ...`, bottom `27000 + ...`. It is not a true angle, but it orders the ports around the rectangle.

Problem, `TinyHyperGraphProblem`:
- `routeStartPort`, `routeEndPort`, `routeNet`.
- `regionNetId[r]`: -1 means free; any other value reserves the region for that net.
- `portPenalty[p]`.
- `portReservationNetId[p]`: -1 free, -2 blocked for every net.
- `portSectionMask` (Int8): ports outside the mask cannot be explored.
- `routeIsFixed`, `initialAssignments`.

State, `TinyHyperGraphWorkingState`:
- `portAssignment[p]`: the net id, or -1. **One net per port** is the hard capacity rule.
- `regionSegments[r]`: a list of (routeId, fromPort, toPort).
- `regionIntersectionCaches[r]`: parallel arrays `netIds`, `lesserAngles`, `greaterAngles`, `layerMasks`, plus running totals `existingSameLayerIntersections`, `existingCrossingLayerIntersections`, `existingEntryExitLayerChanges`, `existingSegmentCount` and `existingRegionCost`.
- `regionCongestionCost[r]`: the history cost, a Float64.
- `ripCount`.
- The candidate heap, with best-cost-per-hop arrays sized `portCount * candidateHopSlotStride` (stride = the maximum number of regions on a port, i.e. 2). A **hop** is the pair (port, next region).

### A.3 Constants

From `THG/core.ts` class fields, overridden by `TINY_SOLVE_GRAPH_BASE_OPTIONS` and `getTinyHyperGraphSolveGraphOptions` in `TinyHypergraphPortPointPathingSolver.ts`:

| Constant | Core default | Pipeline 9 value | Meaning |
|---|---|---|---|
| `DISTANCE_TO_COST` | 0.05 | 0.05 | Cost per mm ("50mm = 1 cost unit (1 cost unit ~ 100% chance of failure)"). Used in `h` and, in the DistanceAware class, in `g`. |
| `RIP_THRESHOLD_START` / `_END` | 0.05 / 0.8 | same | Region-cost level above which a region counts as hot. It ramps linearly with `ripCount`. |
| `RIP_THRESHOLD_RAMP_ATTEMPTS` | 50 | `ceil(10*effortScale)` (10 at effort 1) | Rip rounds over which the threshold ramps up; also the hard cap on rip rounds. |
| `RIP_CONGESTION_REGION_COST_FACTOR` | 0.1 | 0.1 | History cost added per round: `hist[r] += cost[r]*0.1`. |
| `MAX_ITERATIONS` | 1e6 | `ceil(2_000_000*effortScale*graphScale)`, `graphScale = max(1, floor(portCount/125_000))` | Budget counted in A* pops. |
| `ACCEPT_BEST_SOLUTION_ON_TIMEOUT` | true | true | On running out of iterations, restore the best snapshot. |
| `GREEDY_FINAL_ROUTE_ITERS` | 4 | 4 | Greedy completion tries (`GREEDY_FINAL_ROUTE_MAX_ITERATIONS = 50e3` each). |
| `STATIC_REACHABILITY_PRECHECK(_MAX_HOPS)` | true, 16 | same | Fail early on connections that cannot be routed at all. The algorithm in `THG/static-reachability.ts` was not read in detail (**unverified**). |
| `PARTIAL_RIP_*` | disabled | 100/350 routes, `MAX_ATTEMPTS 7`, `WARMUP_FULL_RIP_ATTEMPTS 1`, `TARGET_MAX_COST_IMPROVEMENT_RATIO 0.02`, `MAX_REGION_COST_GROWTH_RATIO 0.05`, `MAX_TOTAL_COST_GROWTH_RATIO 0.1`, `MAX_DISTANCE 12` (mm of route each side of the hot segment); the quality window is 2x when `maxHotCost <= RIP_THRESHOLD_END*1.5` | Partial rip-up window. |
| `costAwareFinalReripBudget` | 0 | 8 (SelectiveRerip) | Rerip budget for the congestion-aware final attempt. |
| `MAX_SELECTIVE_RERIP_CONGESTION_UPDATES` | | 1 | Selective rips add history at most once. |
| `DEFAULT_MIN_VIA_PAD_DIAMETER`, `TRACE_VIA_MARGIN` | 0.3, 0.15 | from board | Via term of the region cost. |
| `IMPOSSIBLE_SINGLE_LAYER_INTERSECTION_COST` | 10 | | Cost of a same-layer crossing in a one-layer region. `computeG` returns Infinity for it anyway. |
| `DUPLICATE_PORT_TRAVERSAL_PENALTY`, `DEFAULT_CRAMPED_PORT_TRAVERSAL_PENALTY` | | 150, 150 | `portPenalty` for duplicated and cramped ports. |
| `DuplicateCongestedPortSolver` | | `duplicatePortProximity: 0.05`, own `MAX_ITERATIONS 2_000_000*effortScale`, `RIP_THRESHOLD_RAMP_ATTEMPTS 0` | A pre-pass that adds extra ports where ports are congested. |
| Trace-density alternative | | 30 to 99 routes only, `TRACE_DENSITY_COST_FACTOR: 1` | A second global plan, kept only if downstream pressure (node Pf) improves (`shouldSelectTraceDensityAlternative`). |

### A.4 Algorithm (pseudocode, faithful to the code)

```
# region cost: THG/computeRegionCost.ts computeRegionCostForArea
cost(r; S,X,E,T) = (2S + X + E) * (viaPad + 0.15)^2 * (1 + T/5) / (area_r * viaAreaFraction_r)
                 + (singleLayer(r) ? 10*S : 0)
                 + DENSITY * (T / layers(r))^2 * 0.1^2 / area_r          # DENSITY = 0 by default
   S = same-layer crossings, X = crossings on different layers,
   E = segments whose two ports are on different z (one via each), T = segment count

# crossing test: THG/countNewIntersections.ts setNewIntersectionCounts
for a new chord (a1<a2, mask m, net n) vs every stored chord i of another net:
    in1 = a1 < lesser[i] < a2 ; in2 = a1 < greater[i] < a2
    if in1 != in2:                         # end points interleave, so the chords cross
        if m & mask[i]: S += 1 else X += 1
    (mask = (1<<z_entry)|(1<<z_exit); segments of the same net never count)

# g step: core.ts computeG (and DistanceAware adds distance)
g' = g + [cost(r; S+dS, X+dX, E+dE, T+1) - cost_r_existing]   # marginal region cost
       + hist[r] + portPenalty[p] + dist(p_prev, p) * 0.05
     = Infinity if dS > 0 and r is a single-layer region
h  = euclid(p, goal) * 0.05

# one route: core.ts _step
pop the lowest-f candidate (hop = port, nextRegion); skip if g > best[hop] or nextRegion is reserved for another net
for each port q on nextRegion:
    q == goal  -> accept if free or same net and g finite -> onPathFound
    skip q if: q == current port, outside the section mask, assigned to another net,
               reserved for another net (endpoint of another net, or -2), or its far region is reserved
    q's far region = incidentPortRegion[q] minus nextRegion
    prune with lowerBound = g + hist + penalty (+ distance) >= best[(q, far)]
    push (q, far, g', h)
onPathFound: for each segment, append (route, from, to) to regionSegments, set portAssignment on both
             ports, update the region intersection cache (incremental: the new chord against stored chords)

# round end: core.ts onAllRoutesRouted
thr = START + (END-START) * min(1, ripCount / RAMP)
hot = {r : cost_r > thr}
if hot is empty or ripCount >= RAMP: solved              # core keeps the current state; the partial-rip class restores the best one
else: captureBestSolvedState(by maxRegionCost, then totalRegionCost)
      hist[r] += cost_r * 0.1 for EVERY region          # not only the hot ones
      ripCount += 1; rip everything except fixed routes
      unrouted = shuffle(range(routeCount), seed = ripCount)    # THG/shuffle.ts: mulberry32 + Fisher-Yates

# no path for a route: SelectiveRerip.onOutOfCandidates
relaxed search: a path is allowed to pass through ports owned by other routes; it minimizes the number of
    distinct owner routes (find-distinct-owner-blocker-path.ts). Fixed routes are forbidden owners.
    Expansion limit = max(4096, sum_ports(#regions) * max(4, ceil(log2(routeCount+1))) * 4)
if no path at all (and not a partial-rip span): FAIL "No path for ... after allowing movable routes to be rerouted"
if not found or no owners: full rerip (core.onOutOfCandidates: hist += 0.1*cost for all, ripCount++, reshuffle)
count[(failed, owner)] += 1; repeated = owners with count >= 2
if any owner has itself failed against this route (a cycle): clear the counts, full rerip
if repeated: search again with the repeated owners forbidden; if not found -> full rerip
rip only the owner routes (rebuildCommittedState), add history once per solver,
ripCount += 1, new order = [failed route] + pending + ripped owners

# timeout: core.tryFinalAcceptance
if the best snapshot exists: restore it and mark solved
else tryGreedyFinalRouteAcceptance: from the current snapshot, route the remaining routes with
    GreedyFinalRouteSolver (g never grows except Infinity for crossing fixed copper in single-layer regions);
    attempt -1 = CongestionAwareFinalRouteSolver (budget 8 rerips) when ripCount < 8;
    attempts 0..3 = greedy with shuffle(seed = ripCount + iter); one extra recovery attempt from a partial result
```

Partial rip-up, for reference (only for 100 to 350 routes): `OutsideInPartialRipTinyHyperGraphSolver.preparePartialRip` handles each route that touches a hot region. It finds the route's segment in the hottest hot region, then grows a window along the route until it covers `PARTIAL_RIP_MAX_DISTANCE` mm on each side. It reroutes only that window, with fixed start and end ports. The search runs from both ends ("outside-in"). Best-state selection (`shouldReplaceBestSolvedState`) prefers fewer segments if max cost is within +5% and total cost within +10% of the first round. It stops early once max cost has improved by 2%, total cost has not grown, and the segment count has not grown.

Connection order: `orderConnectionsByNetCardinality` puts nets with the most connections first, with a stable tie-break by input index.

### A.5 Python spec on top of our engine

**Module** `corridor/` (pure Python + NumPy; numba optional). It writes `reports/corridor_<board>.json` and per-net corridor files. It changes no copper.

1. **Read the board** with pcbnew (`LoadBoard`):
   - Copper layers in stackup order.
   - Pads: bounding box per layer, net, and footprint ref.
   - Existing tracks and vias, treated as fixed and reserving ports.
   - Zones: filled polygons per layer and net, plus keepout rule areas.
   - Board outline and the net class clearance and width per net.
2. **Signal and plane layers.** A layer where at least 80% of the board area (a threshold of ours, **unverified** as a good value) is one net's filled zone is a plane. It is left out of `availableZ` and becomes a via target for idea C. All other layers are signal layers z = 0..L-1.
3. **Regions** (2D cells with an `availableZ` mask, as tscircuit does):
   - Start from a quadtree over the board. Split a cell while it holds part of an obstacle edge or a pad, or while it is bigger than `maxNodeDimension = 15` mm or has an aspect ratio above `6`. Stop at `minNodeArea = 0.01` mm² (the `P9` defaults `maxNodeDimension ?? 15`, `maxNodeRatio ?? 6`, `minNodeArea ?? 0.1 ** 2`).
   - For each leaf and signal layer z, rasterize obstacles (pads, other-net zones, keepouts, fixed tracks, each inflated by clearance + w/2) onto a 0.05 mm bitmap of the cell. The layer is in `availableZ` if the free fraction is at least 0.5 (our threshold, **unverified**).
   - `viaAreaFraction` = the fraction of the cell where a via disc fits on all layers at once (a through via).
   - Optionally merge same-mask neighbours (as `SingleLayerNodeMergerSolver` does in Pipeline 1).
4. **Ports.** For each pair of leaves that share an edge, and each z in both masks: `n = max(1, floor((len - 1.5*s)/s) + 1)` with `s = w_min + clearance`; if `n > 5`, `n = 5 + n//4`. Place the ports evenly along the shared overlap, centre first. The angle is the perimeter parameter, from 0 to 36000, on each side.
5. **Terminals.** Each pad becomes a tiny terminal region (`TINY_TERMINAL_REGION_SIZE = 1e-6` in tscircuit) with `regionNetId = pad net`, joined by one port per pad layer to the leaf containing it. A through-hole pad gets one port per layer.
6. **Connections.** For each net, a minimum spanning tree over the pads (our choice; tscircuit's `NetToPointPairsSolver2` method is **unverified**) gives 2-point routes. Order them by net cardinality, largest first.
7. **Solver.** A direct port of A.4: full rip-up with history, threshold ramp, best snapshot, selective blocker rip-up and greedy final pass. All arrays are NumPy (`int32` and `float64`) and the heap is `heapq` keyed by (f, seq), so ties break in a fixed order. The intersection cache per region is a growing NumPy array. The crossing test is vectorized: `in1 = (a1<L)&(L<a2); in2 = (a1<G)&(G<a2); x = in1 ^ in2; mask = x & (net != n)`.
8. **Output per connection:** an ordered list of `(region_id, entry_port(x,y,z), exit_port(x,y,z))`.

**Handing corridors to KiCadRoutingTools.** Our A* grid router: `route.py` with `--nets`, `--layers`, `--layer-costs`, a stop file, and per-net routing. Whether it supports area masks or waypoints is **unverified**; I have not read `route.py`. What it would need:
- `--allowed-area <json>`: for each net, a list of `(layer, minx, miny, maxx, maxy)` rectangles, i.e. the corridor regions inflated by one grid pitch plus clearance. Grid cells outside the mask get infinite cost. That is a single test in the neighbour loop.
- `--waypoints <json>`: for each connection, the ordered port points with layers, used as soft targets (a cost bonus) or hard sub-goals (route port to port).
- Per-segment layers: inside region r, the allowed layers are `{z_entry, z_exit}`. A layer change happens only inside a region where the plan changes z, so a via is allowed only there. This could be expressed in the mask as "layer set per rectangle".
- No KRT changes needed for a first test: pass `--layers` = the union of the corridor's layers and `--layer-costs` that favour them, and route one net at a time with `--nets`. This gives only part of the benefit (no XY restriction).
- KiCad DRC stays the final judge. Keep only clean nets, as now.

**Size and run-time estimate** (my estimates, not measured):
- jetson: 2946 connections, 10 layers, maybe about 6 signal layers (**unverified**). Board area unknown.
- Assume R of about 20k leaves, E of about 2R shared edges, about 6 common layers and about 3 ports each. That gives P of about 720k ports (`graphScale = floor(720k/125k) = 5`, so tscircuit's budget would be 10M pops at effort 1).
- Memory: about 50 bytes per port for the arrays, plus about 16 bytes per hop for best costs: roughly 60 MB. That fits this PC.
- Work per route: about 2k to 5k pops x about 70 incident ports x a crossing test over about 10 to 30 stored chords, i.e. about 5M elementary operations. Per round: about 1.5e10.
- Pure Python: impossible (hours per round). NumPy-vectorized inner loop: still slow. **numba or a small C/Rust core is required for jetson**: about 15 to 60 s per round, and 10 rounds (`RAMP = ceil(10*effort)`) gives about 3 to 10 minutes.
- kit-dev (478 connections, 4 layers) is feasible in pure Python with coarse cells (2 to 5 mm), at about 1 to 5 minutes.

### A.6 Under one week: test on kit-dev

1. Days 1 to 2: region and port builder from pcbnew for kit-dev. Dump the region count, port count, an SVG overlay and static reachability.
2. Days 3 to 4: the solver of A.4, without selective rip-up at first (full rerip plus history only). Produce corridors for all 478 connections and a per-region cost heat map.
3. Day 5: use corridors without changing KRT. Route the 45 currently open nets one at a time with `--nets`, `--layers` and `--layer-costs` taken from each corridor, in the order of the corridor solver's last round. Compare with the current flow.

Measures:
- Open connections after DRC filtering (baseline about 45).
- A* nodes expanded per net (from KRT logs, if KRT reports them; **unverified**).
- Total router time.
- Whether the nets that fail are the ones whose corridors cross the highest-cost regions (Spearman correlation). This tests whether the cost model predicts difficulty, which is worth knowing before the larger work of building KRT masks.

---

## B. Iteration budgets and determinism

**How effort scales limits** (`P9`):
- `effort` defaults to 1 (`AutoroutingPipelineSolver9_PreloadedTraceGraph.ts`: `this.effort = mutableOpts.effort ?? 1`). The pipeline cap is `MAX_ITERATIONS = 100e6 * effort`.
- **Most stages get `Math.min(1, pipeline.effort)`**, so effort above 1 does not raise their budgets. These include port-point pathing (`getPipeline9PortPointPathingInput.ts`), high density (`pipeline9HighDensitySteps.ts`), `globalDrcForceImproveSolver` and `pipeline9JointDrcRepairSolver` (`pipeline9PostProcessingSteps.ts`). Effort below 1 scales budgets down, with a floor of `getEffortScale = max(effort, 1e-2)`.
- Effort above 1 mainly affects `Pipeline9EffortCleanupSolver`: `cleanupPasses = effort <= 1 ? 1 : ceil(2*effort)`, and `MAX_ITERATIONS = 100e6*max(1, passes)`.
- Per-stage formulas:
  - Global: `MAX_ITERATIONS = ceil(2e6*e*max(1, floor(ports/125000)))`, `RIP_THRESHOLD_RAMP_ATTEMPTS = ceil(10*e)`.
  - Section: `ceil(1e6*e)` and `ceil(16*e)`.
  - Tiny pipeline cap = solveGraph + section + 1e6, times 2 when the trace-density alternative runs.
  - High-density force-improve: `totalStepsPerNode = max(12, round(20*min(1,e)))`.
  - `TraceSimplificationSolver.MAX_SIMPLIFICATION_PIPELINE_LOOPS *= min(1, e)`.
  - Repair budgets: see D.
- When a sub-solver runs past the pipeline's cap, the parent raises its own cap (`MAX_ITERATIONS = max(MAX_ITERATIONS, iterations + child.MAX_ITERATIONS + 1)`) for the length-matching, power-trace and cleanup stages, and in `Pipeline9JointDrcRepairSolver._step`. A parent cap never cuts a child off mid-search.
- **All limits count steps** (`BaseSolver.step`: `iterations > MAX_ITERATIONS` calls `tryFinalAcceptance()`, then fails).

**Wall clock:**
- `performance.now()` and `Date.now()` are used for stats in `BaseSolver.solve`, `timeSpentOnPhase` and the section-search timings.
- The only deadline I found is in the non-default `AutoroutingPipeline9_Networked/Pipeline9NetworkedHighDensitySolver.ts` (`deadlineAt`, `requestTimeoutMs`).
- I grepped for `deadline|timeLimit|MAX_TIME|maxTimeMs|timeoutMs` over `lib/`, `THG`, high-density-repair03 and bga-escape-routing-solver. There is no other match.

**Seeds:**
- There is no `Math.random` in `lib/`, `THG`, `high-density-repair03/lib` or the BGA package (grep).
- Global rerip order: `shuffle(range(routeCount), state.ripCount)` (`THG/shuffle.ts`, mulberry32).
- Greedy final: `shuffle(routeIds, ripCount + greedyFinalRouteIter)`.
- High-density portfolio: `SHUFFLE_SEED` 0..5 (`orderings6`) and 100+ (`orderings50`), using `seededRandom` (xorshift128+, `lib/utils/cloneAndShuffleArray.ts`). Arrays of 4 or fewer items use `PRESHUFFLED_CASES`, so seeds 0, 1, 2, ... cover every ordering.

**Tie-breaking:**
- Heap ties in the BGA escape search get an explicit board-position term, `priority = cost + ((x*rows + y)/layerSize)*1e-9`, "independent of heap order" (`BGA/findTerminalEscape.ts`).
- Terminal sort: scarcity, then distance, then `terminalId` string.
- JS `sort` is stable, and the code relies on index tie-breaks (`orderConnectionsByNetCardinality`).

**Parallel work:** `P9/Pipeline9HighDensityBatchSolver.ts` evaluates node batches independently; "the parent owns ordered outcome acceptance". Results are applied in a fixed order, whatever finishes first.

### B.1 Spec for us

- One config value, `effort` (float, default 1). Every budget comes from it:
  - KRT: maximum A* node expansions per net = `ceil(N0*effort)`. N0 is set per board from the grid size, e.g. `4 * cells_in_corridor`.
  - Rip rounds = `ceil(10*effort)`, and repair regions, candidates and nodes as in D.
- Replace every wall-clock stop with these counts. Keep wall-clock time only as a safety stop that marks a run "invalid", never as a normal stop.
- Seeds: `seed = hash(board_sha, stage, round, net_index)`, using `random.Random(seed)`, never the global RNG. Net order for round k = `Random(base_seed + k).shuffle(sorted_by_cardinality)`.
- Ties: heap key `(f, g, cell_index)`, never insertion order alone. Set iteration only over `sorted(...)`.
- Parallelism: workers may run nets or regions in any order. The main process applies results in a fixed order (net index), and drops a result if its region changed since the worker started. This is the Pipeline 9 batch rule.
- Freerouting: use a fixed pass count. Whether its CLI exposes a seed or pass count, and how deterministic it is, is **unverified**. Treat its output as one candidate that the deterministic DRC filter accepts or rejects.
- Record `effort`, seeds, the KRT commit and the KiCad version in `reports/` with every run.

### B.2 Under one week: test on video (about 145 open)

1. Day 1: find every time-based stop in our scripts and in KRT's `route.py` (stop file, timeouts). Add a node-expansion budget.
2. Days 2 to 3: seeded order and the tie-break heap key. Same-order application of results.
3. Days 4 to 5: five identical runs at effort 1, and three runs at effort 0.5, 1 and 2.

Measures:
- The standard deviation of the open count across the five runs (goal: 0).
- A SHA-256 of the sorted track list (goal: identical across runs).
- Open count against effort, to check that effort is monotone and worth its cost.
- Total time per run.

---

## C. Component detection, escape templates and via-to-pour

### C.1 Detection (`lib/solvers/ComponentDetectionSolver/`)

Pads are grouped by `componentId` (`RectBoundsComponentDetectionStage`). Detectors are tried in this order (`detectors/index.ts`): `QfpThermalPad`, `Qfp`, `Soic`, `Bga`. The first match wins.

**BGA** (`detectors/bga/BgaComponentDetector.ts`), `isDirectBgaLikeComponent`:
- Uniform pad width and height: `max/min <= 1 + MAX_BGA_PAD_SIZE_VARIANCE (0.01)`.
- Aspect ratio of every pad `<= MAX_BGA_PAD_ASPECT_RATIO (1.5)`.
- Row and column centres clustered with `AXIS_CLUSTER_EPSILON = 1e-3` mm. At least `MIN_BGA_AXIS_COUNT = 3` rows and 3 columns.
- Occupancy `pads/(rows*cols) >= MIN_BGA_GRID_OCCUPANCY (0.5)`.
- At least `MIN_INTERIOR_PAD_COUNT = 1` pad that is in neither the first nor the last row or column.
- Fallback `getBgaLikeObstacleSubset`: group the pads by geometry key (w, h, layers) and find the largest complete grid with uniform pitch in x and y (`findLargestCompleteGrid`, `hasUniformPitch` with tolerance 1e-3).

**SOIC** (`detectors/soic/SoicComponentDetector.ts`):
- Uniform pads (0.01).
- Exactly `MIN_SOIC_SHORT_AXIS_COUNT = 2` rows with at least `MIN_SOIC_LONG_AXIS_COUNT = 4` columns, or the transpose.
- The inner gap between the two rows must exceed `(viaDiameter + obstacleMargin)*2`, with `obstacleMargin` defaulting to 0.15.

**QFP** (`detectors/qfp/qfpShared.ts`):
- Perimeter pads have aspect ratio `>= MIN_QFP_PAD_ASPECT_RATIO (1.5)`.
- At least `MIN_QFP_PADS_PER_SIDE = 3` on each of the 4 sides, assigned by nearest side with matching orientation.
- `maxNearestSideRatio <= MAX_QFP_CENTER_NEAREST_SIDE_RATIO (0.25)`.
- **Total perimeter pads `<= MAX_QFP_PAD_COUNT (32)`**, so larger QFPs are not detected.
- The thermal variant allows `<= MAX_QFP_THERMAL_PAD_COUNT (4)` central pads, inside the middle 60% of the box (20% margins), each thicker than the thinnest perimeter pad.

**BGA escape template in the region mesh** (`lib/solvers/BgaTopologyGeneratorSolver/InitialBgaTopologySolver.ts`):
- Layers covered by a pour inside the component bounds are removed from `freeLayers`.
- **Diagonal gaps** (between 4 balls) become one multi-layer node (a via site) if the gap is wider and taller than `viaDiameter * BGA_MULTILAYER_REGION_VIA_DIAMETER_FACTOR (1.2)`, or if `hasClearGapViaCenter` certifies that a via disc clears the round pads.
- **Axis gaps** (between 2 balls) become one single-layer node per free layer. These are trace channels.
- **Missing balls** become a multi-layer node if large enough, else single-layer nodes.
- Each ball gets "free" nodes on the layers it does not occupy, plus an obstacle node.
- Then `RemoveMeshNodeOverlappingWithUnmarkedObstacle`, `GapFill`, `MergeMeshNodes` and `RectDiffPipeline` (`BgaTopologyGeneratorSolver.ts`).
- QFP and SOIC generators exist. I did not read their constants (**unverified**).

### C.2 EscapeViaLocationSolver (`lib/solvers/EscapeViaLocationSolver/EscapeViaLocationSolver.ts`)

This solver is the via-to-plane step, i.e. "drop power pins to planes". It runs before the nets are split into 2-point connections.

```
pours = obstacles with isCopperPour
for each merged net group:
    matchingPours = pours of this net; skip the net if there are none
    reps = getConnectedCopperPourRepresentatives(matchingPours)  # pours whose rectangles share an edge form one
                                                                  # piece; a corner-only contact does not join them
    plans = for each pad point: owner connection, sourceObstacle (the smallest pad under the point, own net first),
            candidateCount; sorted by fewest candidates, then smallest pad area, then point index
    for each plan:
        if the point already reaches a pour (a via on the pad centre, or a via on a trace physically joined to it):
            record pourKey -> point; continue
        best = argmax over (pour on another layer, candidate position) of score, subject to:
            inside the board (via radius from the bounds, or inside the outline);
            inside the pour rectangle;
            the straight stub from pad to candidate keeps requiredTraceClearance = w/2 + margin/2 from every
              other obstacle on the source layer, and does not cross the outline;
            via-to-obstacle clearance over the layer span >= requiredViaToPadClearance
              = max(margin, minViaEdgeToPadEdgeClearance), through vias span all layers;
              pours on other layers are ignored;
            clearance to the escape vias already placed >= margin
          score = 100*minClearance - stubLength - 0.5*|z_target - z_source|
                  + 2*min(projectedFreeSpace, MAX_PROJECTED_FREE_SPACE_BONUS=3)
                  + 10*min(clearanceToPlacedVias, viaDiameter + margin)
          candidates (pad known): positions at escapeOffset = viaR + max(w/2, viaToPadClearance) outside each pad
            side, sampled along that side at the preferred coordinate, the ends, the middle, and steps of
            (viaDiameter + margin) out from the preferred one;
            (no pad: 8 compass points at escapeOffset)
          projectedFreeSpace = distance a ray from the pad, in the stub's direction, travels past the
            candidate before it hits an obstacle or the board edge (minimum of the axis and diagonal rays)
        add the point "escape-via:<conn>:<point>:<layer>:<i>" with terminalVia{toLayer, viaDiameter},
            add the via as an obstacle of this net, record pourKey -> point
    for each pourKey with 2 or more points: representative.externallyConnectedPointIds += [points]
        # the pour connects them, so the router does NOT route traces between these points
```

Constants: `GEOMETRIC_TOLERANCE = 1e-4`, `MAX_PROJECTED_FREE_SPACE_BONUS = 3`, `obstacleMargin` defaults to 0.15. Pipeline 9 passes `viaDiameter`, `minTraceWidth` and the board's `defaultObstacleMargin` (`P9/pipeline9TopologySteps.ts`).

### C.3 BgaEscapeRoutingSolver (`BGA/BgaEscapeRoutingSolver.ts`)

**When it runs** (`P9/getBgaEscapeRoutingInput.ts`, `supportsBgaEscapeRouting`). The trigger is narrow; all of these must hold:
- `layerCount >= 3`, no outline polygon, no blind or buried vias, no buses, diff pairs or jumpers.
- Every fixed trace is wire or via only.
- **No copper pours** and no NPTH.
- Every connection is surface pads only.
- At least one inner signal layer exists (`getBgaSignalLayers`: pad layers plus layers that carry fixed wires).
- The BGA has a narrow channel: `freeWidth = pitch - max(padW, padH) - 2*clearance`, and for some net `freeWidth >= w` and `freeWidth - w < pitch/16`.

Our boards have pours, so tscircuit itself would not run this solver on them. The algorithm is still useful.

**Grid** (`BgaRoutingGrid.ts`):
- `step = pitch / cellsPerBallPitch (16)`, 8-connected neighbours.
- The grid covers the terminals plus `routingMargin = 4*pitch`, clipped to the board minus `edgeMargin`.
- Memory budget: `128 * 1024 * 1024` bytes for the wire masks (one per trace width), the via arrays and the search arrays.
- Copper is marked into per-width masks with distance `w/2 + clearance + step/25`, and into via keepouts (`BgaRoutingCopper.mark`).

**Three stages:**
1. `count_escape_sites`: for each ball, `findTerminalEscape` runs a Dijkstra on the surface layer, at most `3*16` cells (3 pitches), and counts free via sites up to 128.
2. Sort the balls by scarcity: fewest sites first, then the longest nearest distance, then `terminalId`. `reserve_escapes`: in that order, take each ball's nearest via site, and mark the stub and via as that net's copper. This is a dog-bone or via-in-channel escape, scarcest first.
3. `route_connections`: nets sorted by span (shortest first). Point pairs are oriented by a Prim-like rule, shortest escaped branch first (`getEscapedTerminalPairs`). For each pair:
   - Run `BgaTrackSearch`, a weighted octile A*: `f = g + 1.125*octile`. A planar step costs 1 or sqrt(2). A layer change costs `viaCost = 2*16` (2 pitches), and 0 at the pair's own reserved vias.
   - The search starts on inner signal layer `innerSignalLayers[netIndex % count]`, which spreads nets over layers.
   - Expansion budget: 4096 pops per step; fail if the frontier exceeds 262,144 entries.
   - The finished route is marked as that net's copper.
   - Any failure fails the whole solver (`no_via_site`, `no_path`, `frontier_limit`, `grid_budget`).

### C.4 Spec: pre-routing escape on a KiCad board

Module `escape/` runs before KRT and Freerouting on a copy of the board, `<board>_escape.kicad_pcb`. It writes `reports/escape_<board>.json`.

1. **Detect.** For each footprint, take the SMD pads on the top or bottom layer and apply the C.1 tests with the same constants. Add one rule: QFPs with more than 32 pads must still be detected, because 32 is too small for our parts.
2. **Power and ground to planes** (C.2):
   - Target nets are those with a filled zone on another copper layer that covers the pad's XY. Use KiCad's filled polygons, not rectangles; the point-in-polygon test is pcbnew's `HitTestFilledArea`.
   - Candidates and score as in C.2, with clearances from the board's design rules: net class clearance, `min via annular`, `hole-to-hole`, and the courtyard edge.
   - Place a via (net class via size) and a stub track (net class width) for each chosen point.
   - Pads already connected to the plane are skipped: a via in the pad, a thermal connection to a zone on the pad layer, or (for TH pads) a zone on any layer covering the pad.
   - Same-plane pads are then treated as connected, so they are left out of the router's `--nets` work list.
3. **BGA fan-out** (C.3, stages 1 and 2 only, for royalblue):
   - Grid step = pitch/16, around the BGA with a margin of 4 pitches.
   - For each ball not handled in step 2, count via sites within 3 pitches, then reserve vias scarcest first. Via sites must pass the KiCad clearances, and via-in-pad is allowed only if the board rules allow it.
   - Write the dog-bone stubs and vias as fixed copper owned by that net.
   - Leave stage 3 (routing between escapes) to KRT, with the escape vias as the new terminals on inner layers.
4. **DRC** on the escape board. Remove any escape object that is part of a violation, and say so in the report. Never waive a check.
5. **Determinism:** the same tie-break term and sort keys as C.3.

### C.5 Under one week

Two separate tests.

- **(a) Via-to-plane on jetson or video.** Days 1 to 3.
  - Measures: power and ground pins connected to planes before and after, new DRC violations (goal 0), and the change in KiCad's "unconnected items" count.
  - Then route the remaining open nets with the current flow and compare open counts. Power pins left over were part of the "power pins not dropped to planes" problem.
- **(b) BGA escape on royalblue.** Days 3 to 5.
  - Measures: the share of balls escaped DRC-clean, via sites per ball (how scarce), the open count after the normal KRT run with and without escapes (baseline about 49), and router time.

---

## D. DRC-guided local repair

### D.1 GlobalDrcForceImproveSolver (`HDR3/GlobalDrcForceImproveSolver.ts`, `solverConfig.ts`, `solverHelpers.ts`)

**Move set**, applied to a copy of the routes that touch the error:
- **Waypoint nudges:** add or move a waypoint at `(±0.17, 0)` and `(0, ±0.17)` mm on either route side (`spanExpansion 0`). Larger nudges `(±2.4, ±0.4)` and `(±0.4, ±2.4)` use `spanExpansion 2`.
- **Segment detours:** `halfSpan in {0.2, 0.4, 0.8, 1.2}` x `offset in {0.2, 0.3, 0.45, 0.6}` x side ±1 x routeSide {0, 1}. That makes 64 variants (`TRACE_PAIR_DETOUR_VARIANTS`).
- **Span detours:** `spanExpansion 3, offset 1.8`, and **displacement chains**, both in `LOW_COUNT_TRACE_TOPOLOGY_VARIANTS`.
- **Force pushes** on vias and segments away from the error centre (`applyDrcErrorForces`):
  - Step `MAX_ERROR_MOVE = 0.14` mm times a scale from `[1, 1.75, -1]`, for both "fast" and "deep" effort.
  - Via-pair pushes up to `VIA_PAIR_REPAIR_MAX_MOVE = 0.16`. Trace-to-pad pushes up to `TRACE_PAD_REPAIR_MAX_MOVE = 0.3`.
  - Same-net via pairs can be merged ("canonicalize").
- **Broad repulsion:** `BROAD_FORCE_PASSES = 12` (x2 when extended), each move at most `BROAD_MAX_MOVE = 0.035` or `penetration/2`.
- **Layer moves:** safe trace layer moves (`SAFE_TRACE_LAYER_LOCAL_EXPANSIONS = [0,1,2]`), trace layer corridors (up to `TRACE_LAYER_CORRIDOR_MAX_DRC_COUNT = 8` errors), via-in-pad layer moves, trace-pair layer moves, and terminal via relocation.
- Different-net via pairs get a targeted slot every `DIFFERENT_NET_VIA_PRIORITY_INTERVAL = 8` iterations.

**Acceptance** (`isBetterDrcSnapshot`):
1. Reject if the count of forbidden pad-drill errors grows.
2. Then compare lexicographically: the non-via-pad error count, then the repair error count, then the severity score, then the via error count.
3. Severity = the sum over errors of `max(0, required - gap)`, parsed from the messages (`gap: Xmm`, `required: Ymm`). An error without numbers counts 1 (`getDrcErrorSeverity`).

**After accepting** (`acceptSolvedRoutes`):
- If a change creates a new trace-to-obstacle overlap or a new short with a peer, the affected connections are restored from the last overlap-safe checkpoint (at most 2 restore passes).
- With a reference DRC evaluator, a candidate whose reference count grows is rolled back entirely.

**Budgets:**
- Default: `MAX_ITERATIONS = max(48, round(48*max(1,effort)))`, raised to `ceil(errors * 8/3 * max(1,effort))` and to 192 for boards with more than 120 routes (`BROAD_FALLBACK_SMALL_ROUTE_LIMIT`).
- Targeted attempts per error: `round(3*max(1,effort))`.
- Plateau stop: check every 1 iteration (2 or fewer errors), every 2 (fewer than 20) or every 8 (20 or more). Stop after `MAX_DRC_COUNT_PLATEAU_CHECKS = 2` checks with no improvement.
- **Pipeline 9 runs it with `maxIterations: 16`, `enableLargeBoardBroadFallback: false`, `enablePostSolveClearanceRelaxation: false`** (`P9/pipeline9PostProcessingSteps.ts`), so it is a short pre-pass there.

### D.2 Pipeline9JointDrcRepairSolver (`P9/Pipeline9JointDrcRepairSolver.ts`)

It is a staged pipeline:
1. Clearance projection.
2. `initialBoundedRegionalRepairSolver`.
3. `exactRepairSolver` (`GlobalDrcBranchPortfolioSolver`, a portfolio of the D.1 moves; not read in detail, **unverified**).
4. `regionalB01RepairSolver`.
5. `boundedRegionalRepairSolver`.
6. A final `TraceContactRepairSolver`, which throws if it publishes a new short.

Budget constants:
- `EXACT_REPAIR_MAX_ITERATIONS = 32`, `EXACT_REPAIR_BROAD_MAX_ITERATIONS = 12`.
- On large conflicted boards (20 or more errors and more than 120 routes), the budget scale is `min(1, 120*max(1,effort)/routes)`. It is squared at 200 or more errors, with a floor of 8 iterations (2 at 200 or more errors).

**Bounded regional repair** (`Pipeline9BoundedRegionalRepairSolver.ts` + `applyPipeline9BoundedRegionalRepairs.ts`):
- **Region:** a square of side `size`, from `regionSizes = [16, 32]` mm in the Pipeline 9 budget (the class default is `REGION_SIZES = [10, 16]`).
  - Centred on the first pending error. Nearby error centres are merged in while they fit within `size - 2*boundaryMargin`.
  - `boundaryMargin = max(0.5, maxCopperDiameter + clearance)` mm is a fixed collar. Copper in the collar does not move.
  - Pad errors are centred on the pad, not on the error marker.
  - Errors that are not via-to-pad are handled first.
- **Rip and reroute:** `extractRepairRegion` cuts every route at the region boundary.
  - Inside, `NegotiateTraceClearanceSolver` (`node_modules/@tscircuit/repair04/lib/`) reroutes the "dirty" spans (those named in errors) with bounded A*. The heuristic weight is `pathHeuristicWeight = 3`. The grid size scale is `pathGridSizeScale = 2 * (minRegionSize/size)`, so a bigger region gets a finer grid. Layer changes are allowed, and the search runs from both ends (`searchDirectionCount: 2`).
  - Its negotiation is PathFinder-like on spans: each span has weight = its length. Crossing another span costs `overlapRatio * weight`, and immutable copper costs Infinity. After each path, every span it conflicts with gets `weight += 1` and is queued again, and so does the path's own span. A span with no path is frozen.
  - Approach points at terminals are locked.
- **Acceptance:**
  - (1) Physical guards: no fixed-obstacle violation may get worse, and no new via-pad violation.
  - (2) A full reference DRC must pass `isPipeline9DrcPriorityImprovement`. Clearing all routed-copper errors beats anything else; otherwise the candidate needs strictly fewer errors.
  - When a candidate is accepted, the attempted-region list is cleared (`revisitChangedRegions`), so neighbouring regions can be tried again.
  - If a negotiation leaves unresolved spans with budget left, the larger region size is tried first next time.
- **Budget** (`getPipeline9BoundedRepairBudget`, with `s = max(1, effort)`; board size does not change it):

  | | Initial | Per accepted repair | Ceiling |
  |---|---|---|---|
  | regions | `ceil(4s)` | +2 | `ceil(24s)` |
  | candidate attempts (path searches) | `ceil(1024s)` | +512 | `ceil(4096s)` |
  | A* nodes | `ceil(2_000_000s)` | +2,000,000 | `ceil(40_000_000s)` |

  Also: `maxCandidateAttemptsPerRegion 512` and `maxPathSearchNodesPerCall 1_000_000`. Search work "earns" more budget only through accepted repairs.

### D.3 Spec: repair loop on KiCad DRC output

Module `repair/`:
1. `kicad-cli pcb drc --format json --severity-error` on the current board. Parse each violation: type, position, and the items involved (UUIDs, then nets). Keep the unconnected items as a separate list.
2. Work list order: shorts and clearance errors first, then via-to-pad errors, then unconnected items. Window centre = the pad position for pad errors, else the marker position. Merge centres as in D.2.
3. Window = a square of `16` mm, and `32` mm on a retry. Collar = `max(0.5, max_copper_width + clearance)`. Mutable area = the window minus the collar.
4. **Rip:** the track segments and vias of the involved nets, plus any other net's copper lying fully inside the mutable area (optional, at a second level). Cut tracks at the mutable boundary, so the boundary points become fixed terminals.
5. **Reroute:** KRT with `--nets <ripped nets>` and the allowed-area mask = the mutable rectangle (the same KRT change as in A.5). Until KRT has masks, use a cropped board instead: a copy of the board with all copper outside the window locked and a temporary rule area outside the window. Whether KRT honours KiCad rule areas is **unverified**.
6. **Order of ripped nets:** first the nets that appear in the most errors (`prioritizeConflictedRoutes`), then seeded.
7. **Accept** only if:
   - (a) a fast local check finds no new clearance overlap in the window (our own geometry check, from pcbnew `Collide`), and
   - (b) full KiCad DRC on the board shows fewer errors, or the same error count with fewer unconnected items, and no new error of a higher class.
   - Otherwise restore the saved copy. Nothing is waived or filtered.
8. **Budget:** the D.2 table, with the A* nodes reported by KRT counted against `maxPathSearchNodes` and "candidate attempts" = KRT net routes. Full DRC count: at most `regions + accepted` per run.
9. Open connections use the same loop: a window around the gap between the two closest unconnected items, ripping and rerouting the blocking nets in the window.

**Cost note:** full KiCad DRC on jetson is probably tens of seconds (**unverified**). Every candidate must therefore pass the cheap local check first. With a 24-region ceiling, that is at most about 24 to 48 full DRC runs per pass.

### D.4 Under one week: test on video (about 145 open)

1. Days 1 to 2: DRC JSON parser, window builder and collar locking, writing to a board copy. Test the rip-and-restore round trip: no changes should give an identical DRC result.
2. Days 3 to 4: reroute with KRT `--nets` inside the window (cropped-board method), plus acceptance by full DRC.
3. Day 5: run on the 145 open connections with the D.2 budget at effort 1.

Measures:
- Open connections before and after.
- DRC errors before and after (must not rise).
- Accepted and attempted windows.
- Seconds per accepted repair.
- The share of time spent in DRC against time spent routing.

Compare with one extra full Freerouting pass on the same board: open count and time.

---

## E. What I would build first

1. **B (determinism and effort budgets)**. This is the cheapest, and every later measurement depends on it.
2. **C (via-to-plane)**. Little code, and it directly attacks "power pins not dropped to planes".
3. **D (repair windows)** on video.
4. **A**: a corridor prototype on kit-dev, used as a diagnostic first, before writing KRT masks and a numba core for jetson.

The KRT changes (allowed-area mask, waypoints) are shared by A and D. Read `route.py` first, to see whether they already exist (**unverified**).
