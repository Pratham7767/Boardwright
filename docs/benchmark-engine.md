# Routing engine benchmark on KiCad's demo boards

Measured 2026-11-18 with KiCad 10 and the engine in `plugin/scripts/engine.py`. Reproduce with `python tools/bench/engine_bench.py`.

## Method

Each demo folder is copied to a work directory (the KiCad install is never touched). Every track, arc and via is removed with KiCad's Python and the zones are refilled; footprints, zones and the outline stay. KiCad's connectivity then counts the unrouted connections (this count is not capped; the DRC `unconnected_items` list stops at 499, see Observations). The engine runs twice, each time on a fresh stripped copy: once with its defaults (fast nets such as USB and hazardous nets are left out) and once with `--allow-fast`. The engine runs KiCadRoutingTools in strict mode, then Freerouting on what is left, and accepts a stage only if KiCad DRC shows no new error. `--minutes 15` is the engine's time limit per stage. After the run the board is checked again with KiCad DRC.

Completion is `1 - connections after / connections before`, over all connections. "Allowed" completion counts only the connections on nets the engine was permitted to route (it skips hazardous nets, and fast nets unless `--allow-fast`). "New errors" is the number of DRC errors not present on the stripped board.

## Round 5: Freerouting rounds on big boards (0.7.0)

On boards with more than 1000 open connections Freerouting stops at its time limit long before it is done. It now runs again from the board as kept, up to 4 rounds, while a round still closes at least 1 % of what is open. Each round is checked by KiCad's DRC like any stage.

| Board | Round 4 | Round 5 | Rounds |
|---|---|---|---|
| video (4 layers, 1345 connections) | 317-745 open | **284 open (79 % routed)** | 4 rounds: 100, 39, 25 and 28 nets kept |
| jetson (10 layers, 2946 connections) | 1646-1691 | 1679 | stopped after the first round (no net completed) |

Smaller boards run one round, as before. No run added a DRC error.

## Round 4: the rest of the research plan (0.7.0)

What changed after round 3:
- **Repeatable Freerouting:** a fixed item-order seed and one thread (two runs with the same seed produced byte-identical files).
- **A portfolio of three variants** run at the same time, the one with the fewest open connections kept (ties to the first): KiCadRoutingTools first; Freerouting first; and KiCadRoutingTools first with its global planner (#589) on. Each ends with a KiCadRoutingTools pass on the leftovers. KiCadRoutingTools' PathFinder-style history costs (#590) are on in all of them (its default). Big boards (more than 1000 open connections) run the plane repair and Freerouting only.
- **Blame by place:** when a new DRC error names no routed net, the nets with new copper within 3 mm of the error are dropped instead of the whole stage.
- **Pours refilled with the project's rules:** the baseline and every checked result are refilled by `kicad-cli` on a project copy, which applies the project's own rules file; KiCad's Python refill did not, which made pour-to-pad errors on jetson that no route caused. The routers still chain the boards as merged (given the refilled boards, Freerouting routed half as much on video); the board written to the project is refilled by `kicad-cli` and checked once more before it is written.
- Freerouting detects plane nets by itself in this build ("configured for plane routing"), so no plane-net setting is passed.
- Tried and not kept: KiCadRoutingTools' lean setup on big boards (6 s instead of 30+ minutes, but it left more open than Freerouting alone, video 636 against 375), and Freerouting without fan-out on big boards (jetson slightly better, video much worse). See `docs/research/pathfinder-plan.md`.

Open connections left after the engine with the final 0.7.0 code (lower is better); no run added a DRC error:

| Board | Layers | Connections | Round 3 | 0.7.0 | Routed | Variant that won |
|---|---|---|---|---|---|---|
| kit-dev-coldfire-xilinx_5213 | 4 | 478 | 97 | **2** | 99.6% | Freerouting first |
| stickhub | 2 | 128 | 5 | **5** | 96% | KiCadRoutingTools first |
| pic_programmer | 2 | 86 | 7 | **6** | 93% | KiCadRoutingTools first |
| cm5_minima | 6 | 208 | 25 | **24** | 88% | Freerouting first |
| royalblue54L_feather | 8 | 142 | 44 | **44** | 69% | Freerouting first |
| video | 4 | 1345 | 315 | **317-745** | 45-76% | plane repair + Freerouting |
| jetson-agx-thor-baseboard | 10 | 2946 | 1691 | **1646-1691** | 43-44% | plane repair + Freerouting |

Notes, honestly:
- **Video depends on the machine.** Freerouting stops at a time limit (15 minutes here). The same code left 317 open on a quiet machine and 734-745 when only about 3 GB of memory was free (Freerouting is a Java program that needs a lot of memory on a board this size). A longer limit, or more free memory, helps big boards directly.
- An earlier run of this round reported cm5 10 and royalblue 31 open. Those were checked with pours refilled by KiCad's Python, which ignores a project's own rules file; every check now refills with `kicad-cli` and the project's rules, as KiCad itself does, and the numbers above are from that stricter check.
- Jetson's Freerouting stage is now kept (it was thrown out whole before). In 15 minutes Freerouting finishes few nets on a board that size; the rest needs much longer runs or the deeper router work in `docs/research/pathfinder-plan.md`.

## Round 3: Freerouting's nightly build (0.7.0)

Freerouting 2.5.0 accepts a board-edge clearance setting but never reads it, so it routed too close to the board edge, and KiCad's DRC dropped those nets. Its 2.5.1 nightly of 2026-11-16 (commit 12f085e) applies the board-edge and hole clearances. The engine now installs that build, pinned by checksum, from the project's official image on ghcr.io.

| Board | Layers | Connections | With 2.5.0 (round 2) | With the nightly | New DRC errors |
|---|---|---|---|---|---|
| video | 4 | 1345 | 34% | **77%** (315 left; Freerouting kept all 169 nets it routed) | 0 |
| royalblue54L_feather | 8 | 142 | 62% | **69%** (44 left; no net dropped for edge errors, 24-25 before) | 0 |
| kit-dev-coldfire-xilinx_5213 | 4 | 478 | 78% | **80%** (97 left) | 0 |
| cm5_minima | 6 | 208 | 88% | 88% (25 left) | 0 |

Time limits: 15 minutes per stage here; round 2 used 10 for royalblue, kit-dev and cm5, so part of their gain may be the extra time. Video ran at 15 minutes both times. Jetson and the two small boards were not rerun with the nightly.

## Round 2: the research plan (0.7.0, default runs)

After a research round (`reports/Routing engine improvement plan.md` in the example project; summary in the changelog) the engine changed again:
- **One KiCadRoutingTools run, stopped by its own stop file.** At the time limit the engine creates the file named by `KICAD_STOP_FILE`; the router stops before its next net and writes everything routed so far. Batches are gone (each batch repeated the whole-board setup).
- **Big pour nets through the plane repair.** GND and power nets with many open connections are joined to their pour by KiCadRoutingTools' `repair_planes.py` with short taps and vias, in strict mode and with the board's own via size and clearances, instead of being routed as tracks.
- **A fresh folder for every router run**, with the project's own rules file beside the board and beside the output, and `PYTHONHASHSEED=0`: repeatable input for every run.
- **The board's real limits for Freerouting:** edge clearance, hole clearance, no clearance slack, no narrowing below the board's minimum width. Note: Freerouting 2.5.0 accepts the edge-clearance setting but nothing in it reads the value (the code that applies it is only in its nightly builds), so its board-edge errors remain; KiCad's DRC keeps dropping those nets.
- **KiCadRoutingTools is skipped above 1000 open connections:** on video and jetson its setup took more than 30 minutes before it routed one net, so it never reached its stop check.

| Board | Layers | Connections | First run | Round 1 | Round 2 | New DRC errors |
|---|---|---|---|---|---|---|
| pic_programmer | 2 | 86 | 0% | 92% | **92%** (7 left) | 0 |
| stickhub | 2 | 128 | 96% | 96% | **96%** (5 left) | 0 |
| kit-dev-coldfire-xilinx_5213 | 4 | 478 | 0% | 76% | **78%** (107 left) | 0 |
| cm5_minima | 6 | 208 | 89% | 88% | **88%** (25 left) | 0 |
| royalblue54L_feather | 8 | 142 | 70% | 61% | **62%** (54 left) | 0 |
| video | 4 | 1345 | 37% | 31% | **34%** (890 left, in 21 min instead of 39-52) | 0 |
| jetson-agx-thor-baseboard | 10 | 2946 | 0% | 0% | **43%** (1691 left) | 0 |

The jetson gain comes from the plane repair: GND and the power rails joined to their pours. Freerouting 2.5.0 still varies from run to run on video (28-34% over three runs; no seed setting in that version).

Still open: Freerouting's board-edge clearance and run-to-run variation (both fixed in its nightly builds, which need the user's approval to try); KiCadRoutingTools' setup time on very big boards (an upstream option, `minimal_obstacle_cache`, exists in its code but not on its command line); and completion on video.

## After the fixes (0.7.0, default runs)

The first run (below) showed five weaknesses: a whole stage was thrown away when a few nets caused DRC errors; the DRC's unconnected list stops at 499, so big boards were miscounted; Freerouting's work was lost when it ran out of time; GND on a big board used the whole time limit; and the result could vary between runs. 0.7.0 fixes the first four: only the nets that add a DRC error are dropped, open connections are counted with KiCad's connectivity, Freerouting stops at its own time limit and keeps what it routed, pour nets with many open connections get their own short pass, and big boards are routed in batches of 80 nets that are kept one by one.

| Board | Layers | Connections | Before the fixes | After | Time | New DRC errors |
|---|---|---|---|---|---|---|
| pic_programmer | 2 | 86 | 0% | **92%** (7 left) | 72 s | 0 |
| kit-dev-coldfire-xilinx_5213 | 4 | 478 | 0% | **76%** (113 left) | 21 min | 0 |
| stickhub | 2 | 128 | 96% | **96%** (5 left) | 4 min | 0 |
| cm5_minima | 6 | 208 | 89% | **88%** (25 left) | 16 min | 0 |
| royalblue54L_feather | 8 | 142 | 70% | 61% (55 left) | 16 min | 0 |
| video | 4 | 1345 | 37% | 31% (930 left) | 31 min | 0 |
| jetson-agx-thor-baseboard | 10 | 2946 | 0% | 0% | 49 min | 0 |

Time limits: 10 minutes per stage for the first four rows, 15 for the last three (as in the first run). No run added a DRC error.

What is still weak, honestly:
- **Big boards (video, jetson).** KiCadRoutingTools spends its first minutes loading a board this size, so batches with a short time limit end before routing anything; on jetson every batch timed out. Batches now get at least 6 minutes (not yet re-measured). The first run's jetson `--allow-fast` row reached 37 % because its single long KiCadRoutingTools run happened to finish; the engine still needs a way to keep partial results from a run that times out.
- **Freerouting and board edges.** On royalblue Freerouting routes closer to the board edge than the board allows (0.127 mm); KiCad's DRC drops those nets, correctly. Freerouting is now run without neck-down (it narrowed tracks below the board minimum on video) and with its strict checks on.
- **Repeatability.** Runs on the same board can route slightly different nets.

## First run (before the fixes)

| Board | Layers | Footprints | Nets | Connections | Default: done / allowed | Default: new DRC errors | Default: time | Fast allowed: done / allowed | Fast allowed: new DRC errors | Fast allowed: time |
|---|---|---|---|---|---|---|---|---|---|---|
| pic_programmer | 2 | 63 | 111 | 86 | 0.0% / 0.0% | 0 | 116 s | 0.0% / 0.0% | 0 | 107 s |
| video | 4 | 189 | 588 | 1345 | 36.6% / - | 0 | 25.3 min | 36.6% / - | 0 | 24.9 min |
| stickhub | 2 | 94 | 47 | 128 | 96.1% / 96.1% | 0 | 7.6 min | 96.1% / 96.1% | 0 | 8.0 min |
| kit-dev-coldfire-xilinx_5213 | 4 | 160 | 278 | 478 | 0.0% / 0.0% | 0 | 26.4 min | 0.0% / 0.0% | 0 | 25.9 min |
| cm5_minima | 6 | 112 | 220 | 208 | 89.4% / 97.1% | 0 | 25.2 min | 89.4% / 97.1% | 0 | 25.3 min |
| royalblue54L_feather | 8 | 71 | 95 | 142 | 70.4% / 74.6% | 0 | 20.6 min | 69.7% / 69.7% | 0 | 22.6 min |
| jetson-agx-thor-baseboard | 10 | 1125 | 1387 | 2946 | 0.0% / - | 0 | 30.2 min (over 30 min) | 37.2% / - | 0 | 15.0 min |

## Who routed what, and what was left out

| Board | Run | Nets routed by KiCadRoutingTools | Nets routed by Freerouting | Nets left out (reason: count) | Connections left out | Stage seconds (krt / freerouting) |
|---|---|---|---|---|---|---|
| pic_programmer | default | 0 (stage rejected; would have left 4 open, 3 new errors) | 0 (stage rejected; would have left 5 open, 2 new errors) | none | 0 | 54.4 / 15.2 |
| pic_programmer | allow-fast | 0 (stage rejected; would have left 4 open, 2 new errors) | 0 (stage rejected; would have left 5 open, 1 new errors) | none | 0 | 53.3 / 14.8 |
| video | default | 116 | 0 (Freerouting timed out after 15 minutes) | none | 0 | 605.2 / 901.0 |
| video | allow-fast | 116 | 0 (Freerouting timed out after 15 minutes) | none | 0 | 579.3 / 900.9 |
| stickhub | default | 41 | 0 | none | 0 | 169.3 / 259.9 |
| stickhub | allow-fast | 41 | 0 | none | 0 | 158.3 / 296.2 |
| kit-dev-coldfire-xilinx_5213 | default | 0 (stage rejected; would have left 14 open, 5 new errors) | 0 (Freerouting timed out after 15 minutes) | none | 0 | 674.3 / 900.7 |
| kit-dev-coldfire-xilinx_5213 | allow-fast | 0 (stage rejected; would have left 14 open, 5 new errors) | 0 (Freerouting timed out after 15 minutes) | none | 0 | 645.8 / 900.5 |
| cm5_minima | default | 88 | 0 (Freerouting timed out after 15 minutes) | none | 0 | 570.2 / 901.4 |
| cm5_minima | allow-fast | 88 | 0 (Freerouting timed out after 15 minutes) | none | 0 | 570.6 / 901.4 |
| royalblue54L_feather | default | 36 | 0 (stage rejected; would have left 40 open, 7 new errors) | fast net, route it by hand or pass --allow-fast: 2 | 8 | 478.4 / 737.5 |
| royalblue54L_feather | allow-fast | 31 | 0 (stage rejected; would have left 37 open, 7 new errors) | none | 0 | 646.8 / 694.1 |
| jetson-agx-thor-baseboard | default | 0 (timed out after 15 minutes) | 0 (Freerouting timed out after 15 minutes) | none | 0 | 900.1 / 903.4 |
| jetson-agx-thor-baseboard | allow-fast | 1 | not run | none | 0 | 869.9 / - |

## Observations

**Where it did well.** stickhub (2 layers, 128 connections) went from 128 to 5 open with no new DRC error, in about 8 minutes. KiCadRoutingTools did nearly all the work (41 of 45 nets); Freerouting's stage was accepted but added nothing. cm5_minima (6 layers) reached 89% (97% of what the engine was allowed to route), royalblue54L_feather (8 layers) 70%, and video (4 layers, 1345 connections) 37%, all with zero new DRC errors. Accepting a stage only when it adds no DRC error did its job: no run ever wrote a board with a new error.

**Where it failed, and why.**

1. *One DRC error throws away a whole stage.* On pic_programmer, KiCadRoutingTools closed 82 of 86 connections but the stage was rejected for 2 to 3 new errors, all from one piece of silkscreen-like text on a copper layer (`PCB text '1=>>' on top_layer`) that the router drove a track through. The result was 0% instead of about 95%. kit-dev-coldfire went the same way (478 to 14 open in the router, rejected for 5 errors, text such as `MOD1` and `JTAG_EN` on copper, plus a via clearance). The engine merges nets all-or-nothing per stage; it does not drop only the offending nets and keep the rest. The router apparently ignores text on copper layers as an obstacle.
2. *The DRC unconnected list stops at 499 items.* On video (1345 real open connections) and jetson (2946), `kicad-cli` reports exactly 499. The engine plans from that list, so on video it only saw 121 of the nets, and "unconnected 499 -> 499" in its own summary hides real progress (the true count fell 1345 to 853). On jetson the 499 visible items were all one net, GND, so the engine chose a single net and ignored the rest of the board. Exit code and the "Leftovers" list are therefore wrong on big boards.
3. *Freerouting timed out at 15 minutes on every board where it had work (video, cm5, kit-dev, jetson) and its output was discarded.* With 22 connections left on cm5_minima it still ran the full 15 minutes and returned nothing. Where it did finish (royalblue), its result was rejected for edge-clearance errors against Edge.Cuts (7 new errors).
4. *Large boards do not fit in the limit.* jetson (1125 footprints, 10 layers) spent the whole 15 minutes in KiCadRoutingTools on GND alone. With `--allow-fast` the same GND job finished in 870 s and closed 1096 connections (2946 to 1850); in the default run it hit the 900 s limit by seconds, so the two jetson rows differ only by timing. The default run took 30.2 min wall, just over the 30 minute line; it was not killed because the cap was raised to 60 minutes for the reruns.
5. *Fast and hazardous nets:* only royalblue has fast nets in the engine's view (2 nets, 8 connections left out by default). `--allow-fast` changed the result only slightly (31 vs 36 nets by KiCadRoutingTools, 69.7% vs 70.4%), within run-to-run noise. The USB-C pin-clearance issue did not come up on any of these boards. No BGA fanout or plane-specific failure showed in the reports; what the reports do show is the text-on-copper rejection and the timeouts above.
6. *Runs are not byte-for-byte repeatable.* The same pic_programmer stage was rejected for different nets in different runs (DATA-RB7 and VCC_PIC in one, DATA-RB7 only in another).

**Caveats.** Times are wall times on a 16-core Windows machine and were affected by running several boards at once: pic_programmer, stickhub and cm5_minima ran with 10 benchmark streams in parallel (pic_programmer took 32 s when run alone), the others with 3 to 5. Treat times as upper bounds. The strip step removes board-level copper only; jetson still held 34 vias after stripping (probably inside footprints; unverified), and its first strip ran before a fix that stops KiCad's missing-font dialog from blocking (the font message boxes appeared during the benchmark; the scripts now silence KiCad's messages). "New DRC errors" counts distinct error keys not present on the stripped board. Per-net "allowed" completion is blank where the 499 cap makes it meaningless.

