# How the Boardwright pipeline works

This folder is the Claude Code plugin: the part that does the design work and runs the checks. To install it, see the main [README](../README.md).

**Status: 0.5.0.** Tested on Windows 11 and Ubuntu 24.04 with KiCad 10.0.8, on a mains power-supply board and a USB sensor board. Not affiliated with the KiCad project or Anthropic.

## The idea

Claude does the design work. Small Python programs check it. A stage only counts as done when its checks pass. If a check fails, Claude goes back, fixes the cause and runs the check again. It never switches a check off to make it pass.

Each project folder keeps its own notes:

| File or folder | What it holds |
|---|---|
| `PROJECT.md` | What the board must do, and every decision you made |
| `boardwright.json` | Settings for the checks, such as the safety details of a mains board |
| `reports/` | One report per stage, and the results of every check |
| `datasheets/` | One datasheet per part |
| `fab/` | The files for the factory |
| `scripts/` | The check programs, copied into the project so they also run by hand |

## Two ways to work

- **Guided:** Claude asks questions in plain language, one topic at a time, and stops after each stage to explain what it did.
- **Express:** Claude reads your spec and stops only when a check fails or a decision is yours.

Both run the same checks.

## Commands

| Command | What it does |
|---|---|
| `/boardwright:pcb-doctor` | Checks that KiCad, Claude Code and the helper tools are ready |
| `/boardwright:pcb-new` | Starts a new board |
| `/boardwright:pcb-run` | Continues from the stage you are at |
| `/boardwright:pcb-auto <idea>` | Designs a whole board with as few stops as possible |
| `/boardwright:pcb-gates` | Runs every check and changes nothing |
| `/boardwright:pcb-review` | Reviews an existing board and writes `reports/review.md` |
| `/boardwright:pcb-retro` | Looks back at a finished board and suggests improvements to Boardwright |

Commands only run read-only checks without asking. Anything that changes your design asks you first.

## Helpers

For long, routine jobs Claude hands work to helpers that run on cheaper models:

| Helper | Job |
|---|---|
| `datasheet-reader` | Reads one datasheet and lists the pins and limits, with page numbers |
| `part-scout` | Looks up stock, price and lifecycle for a batch of parts |
| `pcb-mechanic` | Draws tracks Claude has already planned, and reruns checks |
| `gate-reviewer` | Gives a second opinion on a stage before it counts (strongest model) |

Design decisions are never handed to a helper.

## The checks

You can run any check by hand from the project folder. Each prints a short result and writes the full detail to `reports/`.

**Every board**

| Command | What it checks |
|---|---|
| `python scripts/run_gates.py . --no-export` | KiCad's wiring check (ERC) and layout check (DRC), and that the spacing rules really apply to the right nets |
| `python scripts/sch_check.py .` | The circuit drawing: part details, pin numbers, unconnected pins, decoupling capacitors |
| `python scripts/status.py .` | Where the project is |
| `python scripts/plan.py .` | What to do next |
| `python scripts/doctor.py .` | That the setup is complete |

**Boards that plug into the wall**

| Command | What it checks |
|---|---|
| `python scripts/safety_class.py .` | Sorts every connection into dangerous or safe |
| `python scripts/mains_check.py .` | Fuse first, correct safety capacitors, discharge time after unplugging |
| `python scripts/creepage_rules.py . --write` | Works out the safe distances and adds them to KiCad's rules |
| `python scripts/creepage_rules.py .` | Checks the distances twice, in two independent ways, and fails if they disagree |
| `python scripts/parts_register.py .` | Lists the safety parts and their certificates |

**Interference and fast signals**

| Command | What it checks |
|---|---|
| `python scripts/emc_harmonics.py .` | Which frequencies each clock produces, and which to test first |
| `<kicad python> -I scripts/emc_rules.py .` | Layout mistakes that cause interference: tracks over gaps in the ground copper, missing ground vias, unprotected connectors |
| `<kicad python> -I scripts/hs_rules.py .` | Fast pairs such as USB: matching lengths and layer changes |
| `python scripts/impedance_check.py .` | Estimated impedance of fast tracks |
| `python scripts/pdn_check.py .` | Whether each power supply has enough capacitors near the chips |

**Release**

| Command | What it does |
|---|---|
| `python scripts/run_gates.py .` | Runs the checks, then makes the factory files in `fab/` |
| `python scripts/precompliance_pack.py .` | Puts every result into one document for the person who signs off and the test lab |
| `python scripts/sim_export.py .` | Exports the board for professional analysis tools such as HyperLynx or CST |

`<kicad python>` means the Python that comes with KiCad (`python.exe` next to `kicad-cli`), because these checks read the board through KiCad.

Every check ends with a code: 0 means passed, 1 means a check failed, 2 means something is missing in the setup.

## Where the design rules come from

The rules Claude follows are in `skills/boardwright/references/`. Each rule names its source: manufacturers' application notes, published design guides and KiCad's documentation. Safety distances come from published summaries of IEC 60664-1 and IEC 62368-1. They are marked "secondary source" until someone checks them against the official standard.

## Licence

MIT. See `LICENSE`.
