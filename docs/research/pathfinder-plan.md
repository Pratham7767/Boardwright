# Congestion-aware routing (rank 7 of the routing plan)

The routing research (`reports/Routing engine improvement plan.md` in the example project) ranked negotiated-congestion routing (PathFinder, McMurchie and Ebeling 1995) and a coarse global-routing stage last: an estimated 2-4 weeks, then 3-6 more, of changes to KiCadRoutingTools' Rust core. Reading KiCadRoutingTools 0.24.1 before writing any of it changed the plan.

## What KiCadRoutingTools already has

- **History-based negotiated congestion, PathFinder-style** (`py_router/history_congestion.py`, upstream #590). Every conflict leaves a small permanent cost on the cells involved: a contest (a failed search's blocked frontier meeting a routed net's copper), a rip's footprint, and a failed search's frontier. Later searches route around repeatedly contested ground instead of ripping. It is **on by default** (`KICAD_HISTORY_COST=0.1`, cap 0.5); its upstream evaluation found the win concentrated on congested boards.
- **A global planning pass** (`py_router/global_plan.py`, #589): every net is rough-routed first (fast, greedy A*, ignoring the other unrouted nets); the predicted paths give a plan-informed net order and optional soft corridor reservations. It is **opt-in** (`KICAD_GLOBAL_PLAN=1`); upstream found the `share` order best and a reservation cost of 0.05 mildly helpful (0.15 hurt).
- Density congestion costs (`KICAD_CONGESTION_COST`, `KICAD_CONGESTION2_COST`): off by default.
- The Rust grid (`grid_router.GridObstacleMap`) takes per-cell, per-layer extra costs (`set_layer_proximity_batch`) and exports congestion helpers (`cong_delta`, `cong_block_slack`): the hooks a further congestion scheme would use.

So the engine does not need its own PathFinder: it needs to (1) let KiCadRoutingTools run on big boards at all, and (2) use the planner where it helps, measured.

## What we measured

1. **Lean setup on big boards: fast, but no gain.** `route.py` builds an obstacle cache for every net on the board before routing its first one; on the 1345-connection video board that took more than 30 minutes. Its lean mode (`batch_route(minimal_obstacle_cache=True)`, not on its command line) cut that to 6 seconds (base map 5.5 s, net cache 0.8 s), run through a small launcher that set that one default in memory. But routed in batches of 60 nets with their own limits and stop files, it left more open than Freerouting alone (video: 636 open against 375), and on jetson every batch ran out of time (a single long rip-up cascade, where the stop file is not checked). So on boards with more than 1000 open connections the engine keeps KiCadRoutingTools out and uses the plane repair plus Freerouting, which measured best there (video 76 %). The launcher was removed.
2. **A portfolio of three variants** on smaller boards, run at the same time in separate folders, the one with the fewest open connections kept (ties to the first): KiCadRoutingTools first; Freerouting first; and KiCadRoutingTools first with the global planner on (`KICAD_GLOBAL_PLAN=1`, `KICAD_GLOBAL_PLAN_COST=0.05`). On video the planned variant left slightly fewer open than plain KiCadRoutingTools-first (624 against 636). Every stage of every variant is checked by KiCad DRC against the project as it was, so every result is rule-clean.

## When to change the Rust core

Only if the benchmark shows a gap these do not close. The candidates, in order:
- A self-imposed time budget inside the single-ended loop and the rip-up reroute (a deadline check next to the stop-file check), so one long cascade cannot overrun the limit. Upstream declined wall-clock behaviour (#100, #713), so this would be a local patch.
- Present-cost (per-iteration overuse) pricing in addition to history, in the full PathFinder form: route every net ignoring overuse, then price shared cells until none are shared, keeping the best legal snapshot each iteration.
- A coarse global router that bounds each net's A* to a corridor (in the style of tscircuit's capacity mesh) to cap runtime on the 2946-connection board.

Each would be raised upstream first (KiCadRoutingTools is active: 0.24.1 shipped 2026-11-16), and none may loosen a rule: the engine keeps `--escalation off --strict-sizes --no-fix-drc-settings`, and KiCad's DRC stays the gate.
