# Benchmark: what editing a board costs

Five editing jobs on a copy of the example board, each done by a real headless Claude Code session (`claude -p`, Sonnet), twice. Every run is checked afterwards: the job's own check (the parts are where they should be, the nets have tracks, the stray track is gone) plus KiCad's DRC (no new errors, nothing unconnected). Numbers are medians of the two runs. Run on 2026-11-17, Windows 11, KiCad 10.0.8.

The jobs:
- **rotate_holes**: rotate the four mounting holes to 45 degrees, in place.
- **netclass**: add a net class and put two nets in it.
- **route_short**: route five short nets (LEDs and USB-C configuration pins) whose tracks were removed.
- **place_decap**: put a decoupling capacitor back next to its chip's supply pin, and route it.
- **drc_fix**: find and remove a stray track that causes a DRC error.

## Before (0.5.0) and after (0.6.0)

| job | passed | context tokens | tool calls | time (s) | cost ($) |
|---|---|---|---|---|---|
| rotate_holes | 2/2 → 2/2 | 424,990 → 358,530 | 8 → 6.5 | 44.5 → 33 | 0.31 → 0.23 |
| netclass | 2/2 → 2/2 | 299,376 → 383,352 | 6 → 7.5 | 68.5 → 42.5 | 0.25 → 0.27 |
| route_short | **1/2 → 2/2** | 1,057,267 → 420,445 | 16.5 → 8 | 186.5 → 52 | 0.51 → 0.28 |
| place_decap | 2/2 → 2/2 | 1,098,244 → 795,844 | 16.5 → 13 | 125.5 → 131.5 | 0.55 → 0.38 |
| drc_fix | 2/2 → 2/2 | 459,487 → 436,954 | 8.5 → 8.5 | 42.5 → 59 | 0.27 → 0.27 |
| **all ten runs** | **9/10 → 10/10** | | | | **3.77 → 2.88 total** |

What changed:
- **Routing** is where it pays: about 60% fewer tokens, half the tool calls, a quarter of the time, and both runs passed. In 0.5.0 one routing run said it was done with two nets still unrouted.
- **Placing a capacitor** cost about 30% less.
- **Small jobs** (rotating, the DRC fix) cost about the same or a little less. Adding a net class cost a little more: Claude read the edit tool's instructions first, which a one-line file edit does not need.
- **In total**, the ten runs cost 24% less, and every run passed.

## What the first try taught us

The first 0.6 run cost the same as 0.5.0 ($3.79 against $3.77). The session logs showed why: Claude did not know where KiCad's own Python was installed, spent six to eight tool calls searching the disk for it, and then edited the board file by hand anyway. So the new tools went mostly unused. Since then, every script that reads the board finds KiCad's Python and restarts under it by itself, so plain `python scripts/bw_edit.py ...` works. The table above is the run after that fix.

## Limits

- Two runs per job is few: one run more or less can move a median by a lot. The totals are more reliable than any single row.
- One small, two-layer board. Bigger boards may gain more from the router and lose more on reading.
- One model (Sonnet). The commands now run on Sonnet by default, so that is the case that matters most.
- The jobs were written for this test; they are not a sample of real design sessions.

## Running it yourself

```bash
python tools/bench/bench.py mylabel --runs 2 --update-scripts --model sonnet
```

It copies the example board for each run, so your own files are never touched. It uses your Claude plan: about $3 to $4 for the ten runs. Results go to `tools/bench/results/mylabel.json`. To measure an older version, pass `--plugin-dir` with a copy of that version's `plugin` folder.
