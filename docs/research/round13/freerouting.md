# Freerouting 2.5.x headless: necking, speed, vias, settings (source-verified)

Source read: github.com/freerouting/freerouting, master as of 2026-11-27 (HEAD 779e271, 2026-11-25). The files that matter here were diffed against commit 12f085e6e (your nightly build, 2026-11-16) and are identical, so the line numbers below hold for your jar, except where marked.
Base path P = src/main/java/app/freerouting. Links: https://github.com/freerouting/freerouting/blob/12f085e6e/<P>/<file>#L<n>

## 1. "Necked retry", [continue-auto-neck], "Start necked"

### 1.1 What the necked retry is
- File: P/autoroute/pipeline/AutorouteConnectionRouter.java, method `retryConnectionNecked` (L347-L425). The log text "Necked retry routed net 'X' at N um trace width." is at L417-L422.
- Trigger (L304-L328): the normal class-width maze search for ONE connection returned FAILED or INSERT_ERROR, AND the connection is not a plane escape (`!escaping`), AND `router.neck_width_um > 0`. The router then re-runs the maze search for the same connection with every layer's trace half-width clamped to `min(classHalfWidth, neckHalfWidth)`.
- Scope: it is the WHOLE connection (one start set to one destination set, however long). It is NOT limited to pin escapes or short segments. All active layers get the narrower width, including layers the route does not use. Ripup is allowed with `start_ripup_costs * passNo`.
- If the necked search also fails, the original failure stands (returns null).
- If it succeeds, the net number is added to `router.neckedRouteNets` (L403), then a pull-tight runs with the neck cost array.
- After a success the net is "necked": with `start_necked` (default true), later connections of that net skip the class-width search and route at neck width directly (L204-L242). These are counted by `startNeckedRouted` and `startNeckedFailed` and logged in P/autoroute/pipeline/AutorouteBatchLoop.java L716-L721 as "Start necked: N connection(s) of nets that needed the neck before routed at the neck width without a class-width search, M ...". These are quiet: no per-net "Necked retry" line.
- Seeding of necked nets (P/autoroute/pipeline/BatchAutorouter.java L280-L292): when the pass loop starts, ANY trace already on the board whose half-width is below its net's class half-width puts that net in `neckedRouteNets`. Candidates are pre-routed DSN wires and the exit stubs. Exit stubs (`router.autorouter.exit_stubs`, default true) use the width `board.rules.getMinAllowedTraceHalfWidth()` when it is above 0, else the class width (P/autoroute/pipeline/ExitStubs.java L1003-L1005). The minimum allowed width is set only when a `.kicad_pro` is passed with `-de` (P/management/HeadlessBoardManager.java L505-L523). Whether that is what makes your nets start necked is unverified.
- A plane escape is never necked (comment L198-L201). The search to the rest of the net may neck.

### 1.2 How the three settings relate
| Setting | CLI | JSON key | Default | What it does |
|---|---|---|---|---|
| neck width | `--router.neck_width_um=N` | `router.neck_width_um` | 0 (off). With `-de x.dsn+x.kicad_pro` it defaults to the larger of the project's min_track_width and min_connection (P/settings/sources/KiCadProjectSettings.java L26; docs/command_line_arguments.md). | Master switch for the necked retry (whole connection), for `start_necked`, for DirectPinRouting's neck retry (P/autoroute/pipeline/DirectPinRouting.java L87-L92) and for the neck floor of micro-neckdown. |
| automatic neckdown | `--router.automatic_neckdown=true/false` | `router.automatic_neckdown` | true | ONLY pin-level narrowing: narrowing at a pin whose pad is narrower than the trace (`Pin.getTraceNeckdownHalfwidth`, used in P/autoroute/maze/MazeSearchEngine.java L550 and L587, and P/autoroute/path/FoundConnectionInserter.java `insertNeckdown`), plus "micro-neckdown" inside the neckdown zone of a pin, at 75, 60 and 50 percent of the class width (L627-L720). It does NOT disable the necked retry. Issue #978 shows this: with neckdown off and neck_width_um=150, traces are 150 um. Your `automatic_neckdown=false` therefore still leaves the necked retry on. |
| start necked | `--router.autorouter.start_necked=true/false` | `router.autorouter.start_necked` | true (DefaultSettings L206) | Only changes whether necked nets skip the class-width search. It does not enable necking. It does nothing when neck_width_um is 0. |

The CLI parser is reflection based. Any `--router.<path>=<value>` works if the path resolves to a field's `@SerializedName` (P/settings/sources/CliSettings.java, P/util/ReflectionUtil.java). `router.max_passes` and similar flat keys are rewritten to `router.autorouter.*`.

### 1.3 Where [continue-auto-neck] comes from (this is a different mechanism)
- P/autoroute/pipeline/RoutingFallback.java L58-L61: the strategy `continue-auto-neck` does `settings.setNeckWidthUm(150)`. It is in the DEFAULT list (P/settings/sources/DefaultSettings.java L139): "direct-first,fanout-retry,short-escape,open-escape,no-fanout,continue-auto-neck". Introduced in commit 033d59e (2026-11-13, PR #1134).
- `applicable()` (L104-L130) drops `continue-auto-neck` when `neck_width_um > 0`, so it should NOT run if your neck flag is effective. If you see passes tagged [continue-auto-neck], the job's neck_width_um was 0 at that moment. The cause is unverified. Candidates: the flag was lost, or a `no-neck` or `continue-no-neck` strategy ran first. `continue-no-neck` is auto-appended by P/autoroute/pipeline/RoutingFallbackRunner.java L355-L370 when neck_width_um > 0 and no .kicad_pro min track width exists.
- Fallback strategies are full extra routing attempts. The runner (RoutingFallbackRunner.java L40-L140) re-routes from the saved input board once per alternative strategy, each with its own pass loop. It stops at the first complete and clean board. It is ranked by fewer opens, then fewer new violations, then score. That is a big time cost on a large board.
- The warning "Fallback auto-neckdown (neck_width_um=150.0) was used because routing remained incomplete with no explicit neck_width_um configured." is at RoutingFallbackRunner.java L155-L161.

### 1.4 How to switch necking off completely
All three, because each has an independent path:
1. `--router.neck_width_um=0` disables the necked retry and the start_necked path. CLI beats the `.kicad_pro` default (priority ladder in docs/settings.md).
2. `--router.autorouter.fallback_strategies=none` removes the fallback re-runs. "none" anywhere in the list returns an empty list (RoutingFallback.parse L136-L141). This also stops `continue-auto-neck` from re-enabling a 150 um neck. If you want to keep other fallbacks, give an explicit list without `continue-auto-neck`, e.g. `direct-first,fanout-retry,short-escape,open-escape,no-fanout`. Valid names: no-neck, continue-auto-neck, continue-fine-neck, fanout-retry, short-escape, open-escape, direct-first, no-fanout, continue, continue-no-neck, none.
3. `--router.autorouter.start_necked=false` is optional belt and braces.
4. Keep `--router.automatic_neckdown=false` to stop pin-level and micro narrowing.
5. `--router.autorouter.exit_stubs=false` stops exit stubs from being pre-placed at a possibly narrower width. Exit stubs are placed before the fanout (see 1.1).
6. Exploration kind "neck-100um" (RoutingSupervisor.java L125, L162-L170) is only used when `explore_patience > 0` (default 0), so it is already off.

### 1.5 Restricting necking to short segments at pads
There is no setting that restricts the necked retry to pad escapes. The only pad-local mechanism is `automatic_neckdown=true` with `neck_width_um=0`. Pin neckdown narrows only inside the pad's neckdown zone (`reachesNeckdownZone`, FoundConnectionInserter.java L633-L639). It is therefore short and local, but it narrows to the PAD width, which can be below your minimum track width. The floor is `AutorouteControl.neckHalfWidth()` (P/autoroute/maze/AutorouteControl.java L497-L513), which is the project min track width if a `.kicad_pro` was given, else 0.
- Micro-neckdown percentage candidates (75, 60, 50 percent) are only used if they are at or above `neckHalfWidth()`. Bug #978 (traces of 75, 90 and 112 um under a 150 um neck) is closed. At 12f085e the floor and the neckdown-zone restriction are present.
- Pin neckdown candidates are NOT floored (comment L648-L651: they stay "consistent with insertNeckdown so a trace can still enter a pad"). Under DRC strictness (min track width in KiCad), pin neckdown can produce traces below min track width. Unverified in practice. Safest for DRC is `automatic_neckdown=false`.

### 1.6 Neck width larger than the net class width
- `retryConnectionNecked` L350-L369: it computes `narrowerSomewhere` (any active layer where class half-width > neck half-width). If there is none, it returns null: NO necked retry and no start_necked, silently. Per layer, `Math.min(classHalf, neckHalf)` is used, so the neck never widens a trace.
- Neck half-width = `max(max(1, round(neckUm * resolution) / 2), board.rules.getMinAllowedTraceHalfWidth())`. It is raised to the project min track width if known. Integer division means a rounding of up to one board unit.
- DirectPinRouting does the same check and logs "Neck width is not narrower than the class width." (DirectPinRouting.java L158-L162).

## 2. Speed on very large boards

### 2.1 Threads: the autorouter pass is single-threaded in 2.5.x
- P/autoroute/pipeline/AutorouteBatchLoop.java L65-L69 logs "Pipeline thread limits: autorouter pass is single-threaded, optimizer.max_threads=N." The batch loop calls `AutoroutePassRunner.runSingleThread`.
- `router.autorouter.max_threads` is "kept for the canonical CLI. The autorouter pass does not read it." (P/settings/AutorouterSettings.java L46-L53). docs/settings.md says: "reserved for future multi-threaded passes".
- docs/research/large-board-autorouter-performance.md: the clone-and-shuffle multi-thread pass (`runMultiThread`) was deleted in RC10. Snapshot search, spatial bins and corridor clipping were measured and rejected: slower or lost connections. Fanout is single-threaded too.
- Conclusion: `--router.max_threads` and `--router.autorouter.max_threads` do NOT speed up a pass. They only matter for the optimizer pool (you disabled it). There is no safe multi-threaded autorouter pass in 2.5.x to turn on. Your max_threads=1 loses nothing.

### 2.2 What actually changes per-pass time (default values from DefaultSettings.java)
| Setting | CLI path | Default | Effect (source-based) |
|---|---|---|---|
| fallback strategies | `--router.autorouter.fallback_strategies` | "direct-first,fanout-retry,short-escape,open-escape,no-fanout,continue-auto-neck" | Each applicable strategy is a full extra route from the input board whenever the main loop ends incomplete (RoutingFallbackRunner). With `none` there is one pass loop. This is the biggest total-time lever; it gives up retries that might complete the board. |
| stagnation | `--router.autorouter.stagnation_pass_limit` | 10 | Stops after N passes without improvement. |
| max_passes | `--router.autorouter.max_passes` | 0 (unlimited) | You use 30. |
| per-connection timeout | none | 100 s * 2^(pass-1), capped at Integer.MAX ms (AutorouteConnectionRouter L192-L194) | Not configurable. A single hard connection can eat 100 s in pass 1, 200 s in pass 2, and so on. |
| job timeout | `--router.job_timeout=HH:MM:SS` | 12:00:00 | Covers fanout, autorouter and optimizer together. The stop flag is checked BETWEEN items, not inside a maze. A pass can overrun the timeout by up to one connection's time. |
| via_costs | `--router.scoring.via_costs` (path `scoring.via_costs`; unverified that the CLI resolver accepts it, JSON `router.scoring.via_costs`) | 50 | Via cost multiplier for the maze (AutorouteControl L385-L411). Higher means fewer layer changes. Effect on pass time is unverified. |
| plane_via_costs | `scoring.plane_via_costs` | 5 | Via into a plane. |
| smd_net_via_cost_factor | `--router.autorouter.smd_net_via_cost_factor` | 0.1 | Multiplies via cost on nets whose pins are ALL single-layer SMD (AutorouteControl L401-L412). At 0.1 this makes vias very cheap on SMD boards like yours. Raise to 1.0 for fewer vias. The `open-escape` fallback sets 1.0. Effect on time is unverified. |
| start_ripup_costs | `scoring.start_ripup_costs` | 100 | Ripup cost = value * pass number. Higher means less ripup and fewer long reroutes per pass, but weaker completion (code path L375). Effect on time is unverified (no measurement in the repo). |
| trace_pull_tight_accuracy | `--router.trace_pull_tight_accuracy` | 500 | Used by `optChangedArea` after every routed connection (AutorouteConnectionRouter L283-L290 and L405-L412). The comment is only "the accuracy of the pull tight algorithm". Higher or lower is untested here. In profiles the maze dominates (about 99 percent of item time on Aleste), so pull-tight is not the main cost. |
| exit_stubs | `--router.autorouter.exit_stubs` | true | Pre-places stubs for fine-pitch ICs (8 or more pins) before the fanout. |
| fanout | `--router.fanout.enabled` | true | You have it false. |
| strict_drc | `--router.strict_drc` | false | Per connection, it serializes the WHOLE board before the connection is routed and restores it on a violation (AutorouteConnectionRouter L165-L170 snapshot logic and L255-L262). On a 4700-pin board this is a notable per-connection cost. Magnitude unverified. If your pass is 9 minutes, strict_drc likely adds a lot. The comment says it is applied "only when enabled explicitly: snapshotting every connection of every late pass would serialize the whole board per connection." |
| ignore_net_classes | `--router.autorouter.ignore_net_classes=A,B` | none | Skips the net classes entirely. Comma lists are re-joined for composite KiCad names like "PWR,Default" (RouterSettings L610-L650). You can use it to route a subset: put the not-wanted classes in it. Nets are then left unrouted. |
| priority_net_classes / priority_via_costs | `--router.autorouter.priority_net_classes` | none | Routed first in every pass, and other signal nets cannot rip them up. |
| max_items | `--router.autorouter.max_items` | Integer.MAX | Stops the stage after N routed items (AutoroutePassRunner L143-L148). Useful for batch/staged runs. |
| plane_as_priority | `--router.autorouter.plane_as_priority` | false | Plane pads are dropped into planes first, one via each. |
| layer direction | `.rules` `(layer_rule ... preferred_direction ...)`, or DSN `(autoroute_settings)` | automatic (RouterSettings.applyBoardSpecificOptimizations L400-L470 sets cost factors from the board bounding box aspect ratio) | `layers[]` is `transient` (not settable by JSON or CLI). Only a `.rules` file or the GUI sets it. |
| item_order_seed | `--router.autorouter.item_order_seed` | null | Changes the item order after pass 1. |

### 2.3 Batch routing / subsets
- No explicit net include list exists. The mechanisms are `ignore_net_classes` (exclude classes), `priority_net_classes`, `max_items`, and the optional `.rules`.
- Running staged jobs by feeding the SES of stage 1 back with `-de board.dsn+stage1.ses` is supported by the CLI (docs/command_line_arguments.md). Whether previous traces become fixed or reroutable: unverified.

### 2.4 Known issues and discussions on performance
- docs/research/large-board-autorouter-performance.md (in repo): Aleste (2210 pins, 2 layers): pass 1 took 1748 s. Maze is about 263 of 264 s in `autorouteItem`. Tail connections cost more than the average. Edge-pin cache fix cut fanout 3.3x.
- Issue #1188 (open, 2026-11-20): "Routing a 4-layer board with planes got 45% slower since 11 November". Autorouter +8 percent in 84284fcc0 (dense-first ordering and failed-pair memoization, PR #1134, 2026-11-13), 17 more vias. The reporter used `--router.autorouter.fallback_strategies=none`, `--router.scoring.via_costs=150`, `--router.autorouter.plane_as_priority=true` (confirms the scoring path works on the CLI).
- PR #1134: memoizing zero-ripup failed connection pairs per pass and dense-first ordering; claims -44 percent autorouter time over 8 boards with max_threads=1 and max_passes=10.
- Issue #1009: `--router.max_threads` and `-mt` only reach the optimizer; the autorouter pass is single-threaded.
- Issue #837 (closed): users routing large boards for days; the job timeout was capped at 24 h in the GUI at that time.
- Reliability of multi-threaded routing in 2.5.x: not applicable to the autorouter pass (does not exist). The multi-threaded optimizer exists. Issue #1123 (closed 2026-11-12) fixed an optimizer memory leak, one board copy per candidate (OOM since #992). Each worker deep-copies the board.

## 3. Vias

### 3.1 How Freerouting picks the via padstack
- Via padstacks come only from the DSN: `(structure ... (via "A" "B"))` is read in P/io/specctra/parser/Network.java (`board.library.setViaPadstacks`, L1516-L1544). `(class ... (circuit (use_via ...)))` and `(via_rule ...)` build `ViaRule`/`ViaInfo` lists per net class (Network.java L286-L400, insertViaRules). If no via infos exist, `createDefaultViaInfos` creates one for EVERY via padstack in the library (L367-L388). If the DSN `use_via` names a padstack that is in the library but not in the `(via ...)` list, it is added to the library via padstacks (L300-L309).
- Per net, the router uses `net.getNetClass().getViaRule()` (P/autoroute/maze/AutorouteControl.java L292-L305); for netless items, the first board via rule.
- At insertion (P/autoroute/path/FoundConnectionInserter.java `insertVia`, L897-L945) it walks the net class via list IN ORDER and uses the first via that spans the layers and passes the shove/clearance check and the SMD-attach check. So list order matters: the first fitting via wins, and later (smaller) entries are only used when earlier ones do not fit. During search, the maze takes via radius from all list entries (AutorouteControl L360-L382).
- Fanout with `fanout.fallback_to_board_vias=true` (default): a net's via list is merged with the board-wide default via rule (the first element of `board.rules.viaRules`) (P/board/facade/RoutingBoard.java `fanoutFallbackViaRule`, L1075-L1100 and L1250-L1290). With fanout off, as in your runs, this does not apply.
- `fanout.start_via_diameter_mm` and `end_via_diameter_mm` (default 0.25) are declared in FanoutSettings but I found no readers in the code, so they appear to be unused. Unverified.

### 3.2 Can any mode create a via padstack that is not in the DSN?
Searched all `new Padstack`, `Padstacks.add`, `new ViaInfo`, `new Via(`. Routing code (necked retry, DirectPinRouting, fanout, neckdown, exit stubs) never creates padstacks. Necking only changes TRACE half-widths. ViaInfos are created only by the DSN/KiCad readers and by `KiCadDesignRulesTranslator` (P/io/kicad/KiCadDesignRulesTranslator.java L795-L820, which only clones an existing padstack with a different clearance class and a name suffix "#..."). So a via hole of 0.3 mm cannot be created by Freerouting if the SES padstack names are only the DSN ones.

SES writer: `SesWriter.writeLibrary` writes only `board.library` via padstacks, and `writeVia` writes `viaPadstack.name` (P/io/specctra/SesWriter.java L233-L248 and L390). Names are unchanged, e.g. "Via[0-3]_800:400_um".

### 3.3 Likely explanation for the 0.3 mm holes (KiCad side, from KiCad source)
KiCad's SES importer takes the drill from the padstack NAME: the text between ':' and the last '_', in micrometres. If it equals the DEFAULT net class's via drill, it is set to UNDEFINED_DRILL_DIAMETER, i.e. "use the net class's via drill". If the name has no ':' the drill is -1 (default) (kicad-source-mirror pcbnew/specctra_import_export/specctra_import.cpp, `makeVIA` L186-L260; call at L539-L544).
- Therefore if any via in the SES uses a padstack whose name carries the same drill as the DEFAULT net class (0.4 mm), KiCad stores "undefined" and then resolves it per net class at load time. A net class whose via drill is 0.3 mm shows 0.3 mm holes. That fits what you saw. This is a hypothesis; it was not checked against your files.
- Check: grep the SES `(via "..." x y)` entries and the `(library_out (padstack ...))` names, and compare with the PCB's net class via_drill values. If the SES names are only 800:400, any 0.3 mm result comes from KiCad's UNDEFINED mapping. A fix on your side is to give the default net class a via drill that is not any of your DSN via drills, or to make the net classes' via drills equal to the padstack's.
- Also possible: the "late round" board had a via from the KiCad PCB that is not in the DSN. Unverified.

## 4. Other settings a headless caller should know (defaults from DefaultSettings.java and RouterSettings.java)

Clearance, DRC and geometry:
| Key (CLI `--router.<key>`) | Default | Notes |
|---|---|---|
| `strict_drc` | false | Rips up a connection whose new items have clearance violations and counts it unrouted (RouterSettings L125-L133). Costly (see 2.2). |
| `clearance_tolerance_um` | 1.0 | Shortfalls at or below this are ignored as discretization noise. You set 0. |
| `drc_epsilon_um` | null (0.0 in ExitStubs) | Board checker tolerance. |
| `exact_copper` | true | Measures pad/via copper exactly instead of octagon bounding shapes. Keep true for DRC-clean output. |
| `copper_to_edge_clearance_um` | 250 | You pass X. Also taken from the .kicad_pro or .kicad_pcb when given. |
| `hole_clearance_um` | 0 | You pass Y. |
| `hole_to_hole_um` | 250 (KiCad min_hole_to_hole default) | Edge to edge between drill holes of any nets. Not in your current flag list. |
| `fix_kicad_footprints` | false | Gives overlapping netless pads their footprint's net. |
| `plane_as_obstacle` | false | If false, foreign traces may cross fills. |
| `plane_nets` | [] | Explicit list of plane net names. |
| `allowed_via_types` | true | false disables vias. |
| `automatic_neckdown` | true | See section 1. |
| `neck_width_um` | 0, or the .kicad_pro min track | See section 1. |
| `trace_pull_tight_accuracy` | 500 | |

Autorouter (`--router.autorouter.<key>`):
`enabled` true; `max_passes` 0; `stagnation_pass_limit` 10; `max_items` MAX; `item_order_seed` null; `ignore_net_classes` []; `priority_net_classes` none; `priority_via_costs` unset; `start_necked` true; `fallback_strategies` (see 1.3); `explore_fallback_strategies` "short-escape,open-escape"; `explore_patience` 0 (exploration disabled); `residual_repair_max_open` 4 (a board with 4 or fewer open connections is first continued from its best state); `smd_net_via_cost_factor` 0.1; `plane_as_priority` false; `plane_share_gap_um` 500; `via_in_pad` and `via_touching_pad` unset/null (allow vias in SMD pads of the own net: an important DRC and fab-capability toggle); `via_centre_of_gravity` unset; `fanout_via_pad_gap` 0.0; `ball_escape_order` "auto"; `exit_stubs` true; `save_intermediate_stages` false; `max_threads` null (not read).

Scoring (`--router.scoring.<key>`, JSON `router.scoring.*`): `via_costs` 50; `plane_via_costs` 5; `start_ripup_costs` 100; `default_preferred_direction_trace_cost` 1.0; `default_undesired_direction_trace_cost` 1.0; `default_bend_cost` 0.0; `unrouted_net_penalty` 5e6; `clearance_violation_penalty` 1e6; `bend_penalty` 10. `router_scoring.*`: V2_CONTINUOUS, clearance_violation_count_weight 25, depth_weight 300.

Fanout (`--router.fanout.<key>`): `enabled` true; `max_passes` 20; `max_milliseconds_per_pin` 10000; `ripup_allowed` true; `min_escape_length_mm` 2.5; `max_escape_length_mm` 4.5; `pin_sorting_order` "outer_first"; `fallback_to_board_vias` true; `retry_without_escape_window` false; `strategy` "eager"; `two_layer_bga` "no_fanout"; `bga_escape_enabled` true; `bga_escape_min_pins` 9; `timeout` null.

Optimizer (disabled in your runs): `enabled` true; `max_passes` 100; `improvement_threshold` 2.5; `patience` BALANCED; `max_autoroute_passes` 6; `via_nudge_enabled` false; `step_slide_enabled` true.

Job: `job_timeout` "12:00:00"; `result_json` null (path for a machine-readable result manifest in headless mode, useful for a caller).

Input files: `-de board.dsn+board.kicad_pro+board.kicad_dru+board.kicad_pcb` (any order, `+` joined). It is the only way to get KiCad's min track width, the `.kicad_dru` rules, the copper-to-edge and hole clearances, and zone clearances (docs/command_line_arguments.md). An adjacent .kicad_pro is NOT loaded automatically. A `.kicad_pro` given with `-de` that cannot be read stops the run. `-drc <file.json>` writes a DRC report in KiCad JSON schema.

Priority ladder (docs/settings.md): Default 0, freerouting.json 10, DSN 20, SES 30, rules 40, env `FREEROUTING__ROUTER__*` 55, CLI 60, GUI 65, API 70. A DSN `(autoroute_settings)` or `.rules` can supply via_costs, plane_via_costs, start_ripup_costs and layer rules, but the CLI overrides them.

## Unverified items
- Why your jobs show [continue-auto-neck] even though a neck width was passed.
- Whether the CLI path `--router.scoring.via_costs` resolves exactly (it is used by an issue reporter in #1188, so it very likely does).
- Quantified effect of start_ripup_costs, via_costs, trace_pull_tight_accuracy and strict_drc on pass time.
- Whether staging via a prior SES keeps its traces fixed.
- The exact cause of the 0.3 mm vias (hypothesis in 3.3).
- `fanout.start_via_diameter_mm` and `end_via_diameter_mm` appear unused.
