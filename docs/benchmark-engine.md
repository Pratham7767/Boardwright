# Routing engine benchmark on KiCad's demo boards

Measured 2026-11-18 with KiCad 10 and the engine in `plugin/scripts/engine.py`. Reproduce with `python tools/bench/engine_bench.py`.

## Method

Each demo folder is copied to a work directory (the KiCad install is never touched). Every track, arc and via is removed with KiCad's Python and the zones are refilled; footprints, zones and the outline stay. KiCad's connectivity then counts the unrouted connections (this count is not capped; the DRC `unconnected_items` list stops at 499, see Observations). The engine runs twice, each time on a fresh stripped copy: once with its defaults (fast nets such as USB and hazardous nets are left out) and once with `--allow-fast`. The engine runs KiCadRoutingTools in strict mode, then Freerouting on what is left, and accepts a stage only if KiCad DRC shows no new error. `--minutes 15` is the engine's time limit per stage. After the run the board is checked again with KiCad DRC.

Completion is `1 - connections after / connections before`, over all connections. "Allowed" completion counts only the connections on nets the engine was permitted to route (it skips hazardous nets, and fast nets unless `--allow-fast`). "New errors" is the number of DRC errors not present on the stripped board.

## Results

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

