# boardwright

A Claude Code plugin that takes a printed circuit board from an idea to fab files in KiCad, in eight gated stages. You watch every board change happen in the open KiCad window, and nothing is ever ordered or uploaded for you.

**Status: 0.4.0, early testing.** Tested end to end on Windows 11 with KiCad 10.0.8 on two real boards. Linux is tested on Ubuntu 24.04 with KiCad 10.0.8 (installer, gate scripts, the KiCad button's window); a full board run there is still to be done; macOS is untested. A community plugin, not affiliated with the KiCad project or Anthropic. Install, update and test instructions are in the repository's README and `docs/`.

## What it does

| Stage | Gate |
|---|---|
| 1 Spec | every requirement has a value and a source |
| 2 Parts | every part has a datasheet and a pin table with page numbers |
| 3 Power budget | at least 20% headroom on every rail |
| 4 Schematic | ERC 0 errors |
| 5 Layout | rule guard passes; DRC with schematic parity 0 errors; nothing unconnected |
| 6 EMC | no CRITICAL finding; isolation barrier check if the board has one |
| 7 BOM | no end-of-life or out-of-stock part |
| 8 Release | Gerbers, drill, placement, BOM and schematic PDF, exported from a freshly refilled copy, plus a checklist of everything you must verify yourself |

Two modes: **guided** (plain-language interview, stops after every stage and explains) and **express** (reads `PROJECT.md`, stops only when a gate fails or a decision is yours). Both run the same gates.

## What it will not do

- It does not make a board safe. A clean check only proves the board obeys the rules that were set. Boards with mains or other hazardous voltage must be reviewed by a qualified person before they are powered.
- It does not prove EMC compliance. Stage 6 is a geometry-based risk estimate.
- It does not order, upload or publish anything.
- It does not waive a failed check. It lists proposed waivers and waits for you.

## Requirements and install

KiCad 9 or 10 with its API server enabled, Claude Code, Python 3.10+, and two helper tools (kicad-buddy for the live link, mcp-server-kicad for schematics). The repository's installer sets all of it up; by hand:

```
claude plugin marketplace add Pratham7767/Boardwright
claude plugin install boardwright@boardwright
python "<plugin folder>/scripts/setup.py"     # uv, kicad-buddy, mcp-server-kicad, KiCad API setting
```

## Use

1. Make an empty folder for your board and open it in Claude Code.
2. Run `/boardwright:pcb-doctor` and fix anything marked FAIL.
3. Run `/boardwright:pcb-new guided` (or `express`) and describe your board. Or, for the fewest stops: `/boardwright:pcb-auto <what the board should do>`.
4. Later sessions: `/boardwright:pcb-run` continues from the stage you are at. `/boardwright:pcb-gates` runs the checks without changing anything.

Already have a design? Run `/boardwright:pcb-new` in a folder that holds your schematic to continue from it, or `/boardwright:pcb-review` for a review-only report on a finished board.

## How the work is split between models

The main session makes every design decision and reviews every gate; run it on the strongest model you have. Mechanical work goes to cheaper helpers, in parallel where their inputs are independent:

| Helper | Model | Job |
|---|---|---|
| `datasheet-reader` | Sonnet | one datasheet each: pin table and ratings with page numbers |
| `part-scout` | Haiku | stock, price and lifecycle for batches of BOM lines |
| `pcb-mechanic` | Sonnet | pushes the routes it is given, runs DRC loops, cleans up silkscreen |
| `gate-reviewer` | Opus | independent review of a stage before its gate counts |

A helper starts with no context, so it only saves usage on long mechanical jobs. Small edits are done directly.

## Scripts

`init_project.py` copies these into your project's `scripts/` folder, so they also run by hand:

```
python scripts/run_gates.py . --no-export     # rule guard, ERC, DRC with parity
python scripts/run_gates.py .                 # the same, then exports into fab/
python scripts/doctor.py .                    # setup check
python <plugin>/scripts/setup.py --check      # helper tools, KiCad API setting (without --check: installs)
python scripts/plan.py .                      # what is ready now, what can run together, what failed
python scripts/status.py .                    # where the project is, in 25 lines
python scripts/sch_check.py .                 # schematic verification before layout
<kicad>/bin/python -I scripts/board_digest.py . --section summary   # compact board facts
<kicad>/bin/python -I scripts/barrier_check.py .   # isolation barrier, needs boardwright.json
<kicad>/bin/python -I scripts/emc_geometry.py .    # EMC geometry, needs boardwright.json
python scripts/safety_class.py .              # voltage domains, ES/PS classes (boardwright.json "safety")
python scripts/mains_check.py .               # fuse first, X/Y classes, varistor, X discharge, earth
python scripts/creepage_rules.py . [--write]  # spacing per barrier (IEC 60664-1 method), rules, cross-check
python scripts/spacing.py --mains 230 --insulation reinforced   # the spacing calculation on its own
<kicad>/bin/python -I scripts/hs_rules.py . [--write]   # pair skew, via parity, return vias ("high_speed")
python scripts/emc_harmonics.py .             # clock and switcher harmonics against the emission bands
```

Exit codes: 0 pass, 1 a gate failed, 2 setup or tool problem. There is no option to skip a check.

## Chat inside KiCad

The repository's `kicad-addon/` adds a button to KiCad's PCB Editor that opens a chat window running this plugin in the open board's folder (Windows and Linux). See `kicad-addon/README.md`.

## Design rules

`skills/boardwright/references/` holds the rules the skill applies, each with its source: `block-guides.md` (per circuit block, from manufacturer application notes), `design-practice.md` (stackup, return paths, spacing, crystals, USB protection, inrush, fiducials, KiCad board setup), `field-lessons.md`, `high-voltage.md`, `high-speed.md`.

## Known gaps

See `docs/ROADMAP.md` in the repository.

## Licence

MIT. See `LICENSE`, including the note on hazardous designs.
