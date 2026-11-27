# KiCad PNS (push-and-shove) router: can it be a headless last-mile fixer?

Sources: gitlab.com/kicad/code/kicad (master and branch 10.0), github.com/PabloSoage/kicad-pcb-routing-tools,
github.com/LGAI-Research/PCBWorld-Engine. "master" = KiCad 11 dev; items also checked on 10.0 are marked.
Anything not read in source is marked unverified.

## 1. Headless drive: what is and is not possible

| Route | Possible? | Evidence |
|---|---|---|
| pcbnew Python (SWIG) | NO. No PNS/ROUTER class is exported. | `pcbnew/python/swig/pcbnew.i` on 10.0 has zero hits for "router"/"pns". |
| IPC API RunAction (KiCad 10) | Only in a running GUI. | `api/proto/common/commands/editor_commands.proto` message `RunAction{string action}`, comment: "TOOL_ACTIONs are specifically *not* an API ... prototyping only". Handler `API_HANDLER_PCB::handleRunAction` (10.0 api_handler_pcb.cpp:155) calls `toolManager()->RunAction(name, true)`; returns RAS_OK / RAS_INVALID. |
| kicad-cli | NO routing command. | `kicad/cli/` has pcb drc/export/diff/upgrade, jobset, api-server; no route. |
| `kicad-cli api-server` (headless IPC) | Not in KiCad 10 (404 on branch 10.0). On master it exists (`kicad/cli/command_api_server.cpp`, "headless mode"), but `API_HANDLER_BOARD::handleRunAction` starts with `checkForHeadless("RunAction")` and returns "not available in headless mode". So even KiCad 11 headless cannot run PNS actions. | |
| C++ linking PNS | YES. | `PNS_KICAD_IFACE_BASE` (pns_kicad_iface.h) is the GUI-free `PNS::ROUTER_IFACE`. `qa/tools/pns/pns_log_player.cpp` (`PNS_LOG_PLAYER`) loads a `.kicad_pcb` with `PCB_IO_KICAD_SEXPR::LoadBoard`, then `m_iface->SetBoard`, `m_router->SetInterface`, `ClearWorld`, `SyncWorld`, `LoadSettings`, `SetMode`, `ImportSizes`, `UpdateSizes`, `StartRouting(p,item,layer)`, `Move(p,item)`, `FixRoute(p,item,false,false)`. |

### GUI actions that exist (names verified in `pcbnew/tools/pcb_actions.cpp`)
- `pcbnew.InteractiveRouter.SingleTrack` (routeSingleTrack, key X)
- `pcbnew.InteractiveRouter.DiffPair`
- `pcbnew.InteractiveRouter.RouteSelected` (Shift+X): "Sequentially route selected items from ratsnest anchor"
- `pcbnew.InteractiveRouter.RouteSelectedFromEnd`
- `pcbnew.InteractiveRouter.Autoroute` (routerAutorouteSelected, Shift+F): "Attempt Finish Selected (Autoroute)"
- `pcbnew.InteractiveRouter.OptimizeSelected`, `.AttemptFinish`, `.HighlightMode`, `.ShoveMode`, `.WalkaroundMode`, `.SettingsDialog`
- Declared in pcb_actions.h but name strings not read (unverified): routerInlineDrag, routerSpreadTracks, routerContinueFromEnd, routerUndoLastSegment, tune* actions.
- Selection over IPC exists: `AddToSelection`, `ClearSelection`, `GetSelection` (editor_commands.proto).

No action takes start/end coordinates. Start is a ratsnest anchor of a selected pad/track; end is the nearest unconnected anchor (`ROUTER::GetNearestRatnestAnchor`, `TOPOLOGY::NearestUnconnectedAnchorPoint`).

### What `Autoroute` does (`ROUTER_TOOL::RouteSelected`, router_tool.cpp ~line 2247)
1. Needs a non-empty selection (footprints expand to all their pads), else returns.
2. For each selected item it walks `RN_NET` ratsnest edges and takes each anchor on that item.
3. Per anchor: sets m_startItem/m_startSnapPoint, posts `routerAttemptFinish`, calls `performRouting()`.
4. `ROUTER::Finish()` (pns_router.cpp:631): `Move()` toward the nearest ratsnest anchor up to 5 tries; succeeds only if `CurrentEnd()==otherEnd` and the other end's layers overlap the CURRENT layer. So single layer, no automatic via.
5. On failure the tool stays in the interactive `performRouting` loop waiting for events (user routes or ESC). Uses `PCB_EDIT_FRAME`, view controls, cursor warp: GUI only.

## 2. How PNS routes one connection
- `LINE_PLACER::routeHead` (pns_line_placer.cpp:1022) dispatches on `Settings().Mode()`: `RM_MarkObstacles`, `RM_Walkaround` (`rhWalkOnly`), `RM_Shove` (`rhShoveOnly`).
- Walkaround: `rhWalkBase` builds a `WALKAROUND`, `SetIterationLimit(WalkaroundIterationLimit())` default 40, policies `WP_CCW` and `WP_CW`, hug-length threshold 1.5, then `OPTIMIZER`. `jump_over_obstacles` default false.
- Shove: `rhShoveOnly` first walks around solids (pads, vias), then `SHOVE::Run()`. `SHOVE::shoveMainLoop` (pns_shove.cpp:1888) ends with `SH_INCOMPLETE` when iter >= `ShoveIterationLimit` (default 250) or `ShoveTimeLimit` expires (default 1000 ms), or an unmovable item blocks. On failure it falls back to `rhWalkOnly`. `ShoveVias` default true, `via_force_prop_iteration_limit` 40. Pads are never moved; locked vias/items not shoved (`pushOrShoveVia`: `IsLocked`).
- Vias/layers: the placer does not search for layer changes. A via is added only when the caller toggles via placement (`ROUTER::ToggleViaPlacement`, `LINE_PLACER::ToggleVia`, `makeVia`, `buildInitialLine`) and then `SwitchLayer`. Layer-aware path finding must come from the caller.
- Clearances: `PNS_PCBNEW_RULE_RESOLVER::QueryConstraint` (pns_kicad_iface.cpp:583) maps PNS constraints to the board's `DRC_ENGINE` (`m_board->GetDesignSettings().m_DRCEngine`): CLEARANCE, DIFF_PAIR_GAP, HOLE_CLEARANCE, EDGE_CLEARANCE, PHYSICAL_(HOLE_)CLEARANCE, HOLE_TO_HOLE, plus WIDTH, VIA_DIAMETER, VIA_HOLE in `ImportSizes`. Custom rules (.kicad_dru) and net classes are honoured; `IsKeepout` handles rule areas; `IsNetTieExclusion` handles net ties.
- PNS is local: it pushes toward a target. Over long congested distances it needs waypoints.

## 3. Diff pair placer
`DIFF_PAIR_PLACER` (pns_diff_pair_placer.cpp): `Start` -> `FindDpPrimitivePair` -> `rules->DpNetPair()` finds P/N nets (`DpCoupledNet`). Width and gap come from `SIZES_SETTINGS` (`DiffPairWidth`, `DiffPairGap`, `EffectiveDiffPairViaGap`), imported by `PNS_KICAD_IFACE_BASE::ImportSizes` from DRC constraints (`CT_DIFF_PAIR_GAP`, `CT_WIDTH`) or inherited from connected tracks (`inheritTrackWidthAndDpGap`). Centre pitch is `gap() = DiffPairGap + DiffPairWidth`. Shove via `attemptWalk`, `tryWalkDp`, `SHOVE::ShoveObstacleLine`. Programmatic use: same C++ API with `PNS_MODE_ROUTE_DIFF_PAIR`; not available from SWIG or IPC. Per the PabloSoage README, in DP mode `FixRoute` returns false on partial progress, and a pair layer change is: toggle via, fix, then `SwitchLayer`.

## 4. Existing projects
- **PabloSoage/kicad-pcb-routing-tools** (GPL-3.0, pushed 2026-11-13, KiCad 10): `layout/pnsdrive/pns_drive.cpp`, added to KiCad's `qa/tools/pns` and built in a KiCad 10.0.8 source tree (Linux, apptainer container; cmake `-DKICAD_BUILD_QA_TESTS=ON -DKICAD_BUILD_PNS_DEBUG_TOOL=ON -DKICAD_SCRIPTING_WXPYTHON=OFF`, target `pns_drive`). Text script commands: `load`, `mode single|dp`, `policy shove|walk|mark`, `size`, `start X Y LAYER NET`, `follow`, `move`, `finish X Y`, `fix`, `layer`, `via`, `commit`, `abort`, `drag`, `tune ...`, `fixall`, `shovevias`, `violate`, `save`. Loads board + .kicad_pro + .kicad_dru. Paired with `waypoints.py` (single-layer grid A* corridor). Its notes: init `PGM_BASE`/`MOCK_PGM_BASE`, `Pgm().InitPgm(true,true,true)`, register `PCBNEW_SETTINGS` (else segfault); call `BOARD::SynchronizeTuningProfileProperties()`; router needs a no-op `DEBUG_DECORATOR`; pass the end item to the last `Move()` before `FixRoute`; disable ASLR (router choices depend on pointer order); `ShoveVias(false)` to avoid via/track-end drift. It is a close relative of the user's own stack; whether it is the user's A* repo is unknown.
- **LGAI-Research/PCBWorld-Engine** (GPLv3): KiCad 9.0.8 patched; `kicad-patches/rl/` holds a headless RL router exposed as pybind11 module `kicad_rl_router`, served over a unix socket (`engine_server/rl_engine_server.py`); built by `build_rl_router.sh`, optional `BUILD_CLI=1 BUILD_PCBNEW=1`. Notes "a single shove can legitimately take minutes". Contents of `kicad-patches/rl` not read (unverified).
- **KiCad's own** `qa/tools/pns` (`pns_log_player`, `pns_debug_tool_main`, `qa_pns_regressions_main`): replay harness, proof PNS runs without the GUI.
- Tubbles/pnsrouter: Rust re-implementation inspired by PNS, not KiCad code; unverified quality.

## 5. Recommendation
Feasible, but not through Python/SWIG/IPC on stock KiCad 10.

A. Headless path (recommended): build `pns_drive` (or a purpose-built `pns_fix` modelled on `PNS_LOG_PLAYER`) against KiCad 10.0.x source, linking `PNS_KICAD_IFACE_BASE`. One-time heavy build (Linux/container proven; Windows build unverified). Ship as a separate GPL-3 binary per OS and call it from Python by subprocess with a text script. This conflicts with "add-on alone gives every feature" unless the binary is bundled.
Steps per leftover connection:
 1. From kipy or `kicad-cli pcb drc` JSON "unconnected_items" get the two endpoints (pad/via/track end), net, layer.
 2. Same layer: script `load`, `policy walk` first (no collateral), then `policy shove`, `size 0 0` (use rules), `start X Y LAYER NET`, `move`, `finish X Y` (end item snaps), judge success by routed-length change, `save`.
 3. Different layers: toggle via, `fix`, `layer`, then `finish`; take the via position from your own A*.
 4. Gaps over about 20 mm: give waypoints from your A* (`follow`).
 5. Diff pairs: `mode dp`; judge progress by length change.
 6. Afterwards `kicad-cli pcb drc --refill-zones`; keep the result only if the leftover count falls and no new violations appear. Work on a copy and diff.
B. Live-GUI path (KiCad open only): IPC `AddToSelection` pads, then `RunAction("pcbnew.InteractiveRouter.Autoroute")`. Same layer only, no coordinates, blocks in the interactive loop on failure, needs GUI, RunAction is explicitly non-API. Fragile for unattended use; whether a later `RunAction` can cancel the stuck loop is unverified.
C. Not feasible: pcbnew SWIG, kicad-cli, KiCad 11 headless api-server (RunAction refused headless).
Caveats: PNS never moves pads; locked items stay; results depend on item/pointer order.
