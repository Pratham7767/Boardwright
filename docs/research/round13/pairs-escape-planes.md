# Research: diff pairs, BGA/connector escape, plane nets (KiCadRoutingTools + others)

Source read: github.com/drandyhaas/KiCadRoutingTools `main` (newer than the 0.24.1 you run; latest tag seen v0.24.2).
Raw copies in this folder: route_diff.py, route.py, diff_pair_loop.py, single_ended_loop.py, env_knobs.py, differential-pairs.md, route-plane.md, power-nets.md, configuration.md, README.md (bga_fanout).
Anything on `main` may be absent from 0.24.1: check with `route_diff.py --help` in your install. Marked "unverified" where I could not confirm.

## A. Differential pairs

### A1. Time limit / stop file / partial save (confirmed from source)
- `KICAD_STOP_FILE` (and `KICAD_STOP_AFTER`) are read only in `py_router/single_ended_loop.py` (~l.695-726): stops before the next net when the file exists, sets `state.checkpoint_stop`, and `route.py` (~l.5091) skips later passes and WRITES the partial board. Defined in `py_router/env_knobs.py` l.583-584. So route.py already honours a stop file; route_diff.py does not (grep: no STOP_FILE in route_diff.py or diff_pair_loop.py).
- Diff pair loop: `py_router/diff_pair_loop.py` ~l.496: `if state.cancel_check is not None and state.cancel_check(): ... break` (checked between pairs). `batch_route_diff_pairs(input_file, output_file, net_names, ..., cancel_check=None, progress_callback=None, ...)` at route_diff.py l.636 (param at ~l.762) takes a callable.
- Actionable: call `batch_route_diff_pairs` from Python (import route_diff) with `cancel_check=lambda: os.path.exists(stop_file) or time.time() > deadline`, instead of the CLI. Between-pair granularity only (a pair in progress finishes). Whether the output file is written after a cancel: the loop only sets `user_cancelled` and breaks, and the code after continues to reroute/reconcile/write, so partial output is likely, but I did not trace the write path: unverified. Test with a 2-pair run and a pre-created stop file.
- Cheaper alternative with no code: your 12-pair batches are right. Run each batch with `-O`/chained output so each batch's result is kept (route_diff persists protected nets in the output `.kicad_pro`, so later batches won't rip earlier pairs: `persist_protected_nets`, route_diff.py end of main).
- Other speed knobs on route_diff.py: `--max-iterations` (A* cap per attempt), `--max-ripup`, and `quick` level (a `--quick LEVEL` parameter exists on batch_route_diff_pairs; level 2 skips polish passes). `--effort-factor` exists in the plugin text (README). Exact CLI spelling for quick: unverified for 0.24.1.

### A2. Per-layer width/gap (outer 0.19/0.18, inner 0.15/0.125)
- Docs (differential-pairs.md "P/N Path Generation", ~l.371-400): per-layer widths are supported three ways: `--impedance Z` (solves widths per layer from the stackup), a stored impedance declaration, or a layer-scoped `.kicad_dru` rule, e.g. `(rule "strip" (layer "In2.Cu") (constraint track_width (opt 0.154mm)))`, used when neither `--track-width` nor `--impedance` is given. Offset is taken per layer (`layer_pair_spacing`). A layer with no scoping rule keeps the net class `diff_pair_width`.
- So: give route_diff.py NO `--track-width`, put per-layer `track_width` rules in the .kicad_dru (you already have them), and pass ALL copper layers with `--layers F.Cu In1.Cu In2.Cu B.Cu`. The default is `--layers F.Cu B.Cu` only (differential-pairs.md l.81-86), which is exactly why your pairs only route on outer layers at the outer size. This is the highest-value fix for the "outer only" symptom. Gap per layer from a rule: the doc says "Without an impedance target (widths from a layer-scoped rule) the gap is kept", so the gap (0.18 vs 0.125) is NOT switched per layer by a width rule alone; `--impedance` is the route that adjusts gap per layer: unverified whether a layer-scoped gap rule is read. Test on 2 pairs and measure.
- Fallback when a coupled route fails: "Narrowed to fit (#1742)" retries coupled at narrower width on runs with per-layer widths (main only; unverified in 0.24.1).

### A3. Failure after BGA fan-out (endpoint-resolution-failure)
- The string "endpoint-resolution-failure" is not in KRT main source or docs (grep): it looks like your engine's own label. Unverified origin.
- Documented causes in KRT: (1) `--layers` must include the inner layer the fan-out used, else "strands the inner-layer stubs and silently drops those pairs" (butterstick 8/40 vs 22/40 pairs) (differential-pairs.md l.81-86). (2) Fan out with `bga_fanout.py --diff-pairs "<pat>"` so P and N exit on the same layer, converged to the pair spacing and extended past the boundary ("so route_diff picks them up", bga_fanout README l.331-340). Without `--diff-pairs` the stubs are single-ended and the endpoint pairing ("closest P-N pairs on the same layer", differential-pairs.md l.98-102) fails. (3) `--escape-method underpad`/`dogbone` + route_diff "Inner-Layer Launch via Escape Vias" (l.622-645) composes with coupled routing. (4) Bare-pad endpoints are handled by synthesised escape direction (l.120-135), so a pair with NO stubs on one end is also fine; half-stubbed pairs are the risky case.
- Actions: run `bga_fanout.py ... --diff-pairs` with the same `--diff-pair-gap` as route_diff, and the same `--layers` list; verify with `route_diff.py` log for "Endpoint" lines.

### A4. Other tools / methods
- KiCad's own PNS diff-pair router: interactive only; no headless API. KiCad IPC (kipy) does not expose the router (unverified; I did not check kipy's API listing). `kicad_run_action` could fire router actions only in a live GUI session, not a batch.
- Topola (topola.dev, Rust topological router; Specctra DSN/SES): diff-pair support unverified; not a drop-in.
- Freerouting: no coupled diff-pair routing (it routes pairs as independent nets; from my knowledge, unverified here).
- Published: Fang et al., "Routing for Chip-Package-Board Co-design Considering Differential Pairs", ICCAD 2008 (https://www.cecs.uci.edu/~papers/iccad08/PDFs/Papers/07A.3.pdf); Cho, Kam et al., "Mixed-Signal Escape Routing Algorithm for Multilayer PCBs" (diff pairs with length matching); "On the escape routing of differential pairs" (HKBU, two algorithms, optimal single-pair routing); ILP for mixed diff-pair/single-signal escape ("Escape Routing of Mixed-Pattern Signals Based on ...", ORKG item 105938138). Takeaway used by KRT too: route the pair as one "fat" centerline (offset ±(w+g)/2) and then fan out at the ends.

## B. BGA / connector escape

### B1. bga_fanout.py options that address shorts (confirmed from py_router/bga_fanout/README.md)
- `--nets "*" "!GND" "!+3.3V"`: exclude plane nets from escape. Plane balls then get a plane-drop via (`--plane-drop auto`, default) instead of a signal escape; `--plane-net-layers NET:LAYER[,LAYER]` (e.g. `GND:In1.Cu`) suppresses the drop via where the future pour reaches the pad on its own layer. Shorts onto neighbouring GND pads usually mean GND balls were treated as obstacles/signal or the escape clearance was too small; excluding GND and using the drop is the documented path.
- `--clearance` (default 0.25 in README table, but "board's own rules honoured": per-layer `.kicad_dru`, net classes #1529, class/type rules #1565). Set it to your real rule (0.1 for fine pitch). README sizing rule (l.122-145): `via_size <= pitch - track_width - 2*clearance`; e.g. 0.8 mm pitch, track 0.127, clearance 0.1 => via <= 0.473 (0.5 grazes, 0.45 clean). Compute your connector pitch before choosing `--via-size/--via-drill/--track-width`.
- `--escape-method`: `auto` (channel then underpad, keeps whichever escapes more), `channel`, `underpad` (via in pad), `dogbone` (via in diagonal inter-ball gap, "never escapes fewer balls than underpad", validated against exact geometry). `--same-net-pad-clearance > 0` forbids via-in-pad (underpad and plane drops run dog-bone; a ball with no legal site fails visibly rather than shorting).
- Output JSON_SUMMARY has `drc_grazes` (a check_drc pass over the output at `--clearance`: `pad_via`, ...) and `min_clearance_used`: read these right after the run to catch shorts before committing. Also `py_tools/check_orphan_stubs.py`, `check_weird.py`.
- `--check-for-previous` (skip balls already fanned), `--layer-costs` (negative = no escape copper on that layer, e.g. a future plane layer), `--grid-step` (match route.py), `--diff-pair-gap`.
- `place_fanout_clearance.py` (py_placer): moves decap-like 2-pad parts that the fan-out grazes (README "After fanout").
- Run only on the pairs/nets you need in chunks (`--nets` patterns) so one dense group cannot short others; the 5-minute full-connector run is likely the monolithic case. A 699-pin connector is not a BGA: bga_fanout treats it as a ball grid; behavior on 2-row staggered edge connectors is unverified. For connectors, route_diff's own "Bare-Pad Target on a Different Layer (Connector Fanout)" swap (differential-pairs.md l.140-150, option under configuration.md "layer-optimization options") drops a through-via on each bare pad and grows a short stub toward the source layer: try that instead of a full fan-out.

### B2. Other tools
- Laksen/kicad-bga-tools (bga_dogbone.py: dogbone vias for all connected pads) https://github.com/Laksen/kicad-bga-tools
- thanhduongvs/kicad-fanout-tool (QFP/BGA escape fan-out plugin) https://github.com/thanhduongvs/kicad-fanout-tool
- KiCad forum collection "adaptive fanout, via stitching ..." https://forum.kicad.info/t/a-collection-of-plugins-for-kicad-for-quick-analysis-and-other-helpers/71792
- weirdgyn/viastitching https://github.com/weirdgyn/viastitching ; hringdrifi/kicad-via-stitcher (KiCad 10)
- All unverified for quality/compatibility; none read in detail. They are GUI action plugins (pcbnew Python), so not directly headless-callable (unverified).

### B3. Published methods
- Ordered escape routing via min-cost multi-commodity flow (MMCF) (summarised at https://www.aivon.com/blog/pcb-assembly/navigating-bga-escape-routing-essential-techniques-for-high-density-pcbs/ : secondary source).
- "Escape Routing for Staggered-Pin-Array PCBs" (https://www.researchgate.net/publication/221627866) : relevant for staggered connectors.
- Escape of diff pairs: HKBU paper above; Cho/Kam mixed-signal paper.
- Practitioner patterns: PCD&F "BGA Escape/Routing Patterns for Fine-Pitch Devices" https://pcdandf.com/pcdesign/index.php/2007-archive-articles/2659-bga-escaperouting-patterns-for-fine-pitch-devices ; EE.SE "Escape diff pairs from 0.8mm pitch BGA" https://electronics.stackexchange.com/questions/734863 .
- Network-flow note: flow models give channel capacity per row/layer (max pins escaped per layer); useful as a pre-check to decide how many layers a connector needs, KRT's channel engine is heuristic ("a few channels over-subscribe", README underpad rationale).

## C. Plane nets (GND, +3.3V on a 4-layer board)

### C1. What KRT says (confirmed)
- Intended flow (README l.254-266): pour planes FIRST, then fan-out, then route ALL nets including plane nets:
  `route_planes.py in.kicad_pcb poured.kicad_pcb --nets GND +3.3V --plane-layers In1.Cu In2.Cu` (bare pour, #562: no taps placed), `bga_fanout.py ... --plane-net-layers GND:In1.Cu`, `route_diff.py`, then `route.py` over ALL nets, "do NOT exclude the plane nets here" because the route step welds plane pads into the pour and ends with an in-run plane finalize (pad taps + region joins + KiCad-oracle completion check). `KICAD_PLANE_FINALIZE=0` disables it.
- route-plane.md "Repairing Disconnected Plane Regions" (l.679-852): repair_planes.py needs existing zones on the board (it auto-detects zones; `--nets`/`--plane-layers` limit); standalone it "cannot know the sizes a chain routed at": defaults to the board Default class, so pass `--track-width --via-size --via-drill --clearance` explicitly; `--grid-step 0.05` for fine pitch; `--repair-pads` (default on) retries each unconnected plane pad with a stitching via + short trace, fine-pitch retry steps clearance down toward fab floor; `--rip-blocker-nets` (+ `--max-rip-nets`, `--power-nets/--power-nets-widths`, `--no-bga-zone`) connects a pad by tracing to a same-net pad ripping signal blockers; `--no-kicad-recheck`; `--max-iterations` default 200000; `--zone-clearance`; `--same-net-pad-clearance > 0` keeps repair vias off pads. Failure reasons doc (l.1006): all anchors blocked, iteration limit, no viable path.
- "Joins 0 nets" on kit-dev most likely means: no same-net zone existed on the board when repair ran (GND/+3.3V were routed as TRACKS, so there is nothing to repair), or the zones were not poured on a layer with room. unverified diagnosis; check `list_pcb_zones` for GND/+3.3V first. On big boards it works because the plane pour ran first.
- Widths: with no `--track-width`, every net routes at its own net-class width and `.kicad_dru` track_width rules (power-nets.md l.7). `--power-nets "+3.3V" --power-nets-widths 0.4` outranks the class. Failed wide routes are automatically retried at the layer default width with neck-down near pads (`--neckdown-length` 2.5 mm, `--neckdown-taper-length`, `--no-power-tap-neckdown`): so a plane net routed as track can legitimately ship with narrow sections that your 0.4 mm gate flags. `--escalation fab` (default) narrows below the requested size to complete; `--escalation board` stops at board minimums; `--escalation off` "ships the net open/fails and reports", except pad-entry neck <= 2 mm. If your gate needs >= 0.4 mm everywhere, use `--escalation off` plus pour planes rather than track-routing the net (configuration.md l.198, l.218-240).
- Recommendation for a 4-layer stack: GND on In1.Cu, +3.3V on In2.Cu (or `"A|B"` shared layer syntax, route-plane.md l.61 and "Multi-Net Layer Zone Generation"), `--add-gnd-vias`, `--stitch-vias` in a re-run after routing (route-plane.md l.568).

### C2. Other tools / methods
- Via stitching: weirdgyn/viastitching, hringdrifi/kicad-via-stitcher (above). KiCad zone fill + "Remove isolated copper" and DRC "unconnected items"/ zone connectivity via kicad-cli is what KRT's "KiCad oracle" uses.
- "Dogbone to plane" (via in diagonal gap with short 45 deg stub connecting to pad): KRT `--escape-method dogbone` and plane-drop; Laksen/kicad-bga-tools bga_dogbone.py; teardrops: KRT `--add-teardrops` (fanout, route_planes, repair_planes all accept it) and KiCad 7+ native teardrop settings; KiCad "Teardrops" plugin NanoDano/ (unverified name).
- Rule of thumb from KRT's tips (route-plane.md l.541): reduce via size (0.4/0.2) for more placement options; pour first.

## Ranked suggestions (gain vs effort)

1. (A, low effort, high gain) Pass every copper layer to route_diff: `--layers F.Cu In1.Cu In2.Cu B.Cu`, with no `--track-width`, per-layer `.kicad_dru` track_width rules. Fixes outer-only routing and stranded inner fan-out stubs. Verify gap per layer (A2 caveat).
2. (A, medium) Call `batch_route_diff_pairs(..., cancel_check=...)` from your Python engine to honour your stop file and a deadline; keep 12-pair batches chained so completed pairs persist.
3. (C, low) Pour GND/+3.3V with route_planes.py before any routing; route.py over ALL nets (don't exclude plane nets); pass repair_planes explicit `--track-width/--via-size/--via-drill/--clearance` if run standalone. Use `--escalation off` / `--no-power-tap-neckdown` if the 0.4 mm gate must hold.
4. (B, low) bga_fanout: exclude plane nets (`--nets "*" "!GND"`), `--plane-net-layers`, correct `--clearance`/via size from the pitch formula, `--same-net-pad-clearance > 0`, `--diff-pairs` with same gap/layers as route_diff; read `drc_grazes` in JSON_SUMMARY and reject the output if nonzero.
5. (B, medium) Fan out in chunks per group, run `check_drc`/`check_weird`/`place_fanout_clearance`; for connectors try route_diff's bare-pad layer-swap rather than bga_fanout.
6. (B/A, high effort) Own escape router (MMCF / ordered escape) only if 1-5 fail; paper refs above.

## Not confirmed
- Whether 0.24.1 has the same flags/behaviour as main; whether route_diff CLI main passes any cancel_check; whether output is written after cancel; per-layer gap from layer-scoped rules; "endpoint-resolution-failure" origin; kipy router API; Topola diff-pair support; quality/headless use of third-party plugins.
