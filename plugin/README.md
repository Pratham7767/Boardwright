# How the Boardwright pipeline works

This folder is the Claude Code plugin: the part that does the design work and runs the checks. To install it, see the main [README](../README.md).

**Status: 0.6.0.** Tested on Windows 11 and Ubuntu 24.04 with KiCad 10.0.8, on a mains power-supply board and a USB sensor board. Not affiliated with the KiCad project or Anthropic.

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
| `/boardwright:pcb-undo` | Lists the saved steps, compares two of them and goes back to one |
| `/boardwright:pcb-plan` | Optional routing plan: `on`, `approve c1`, `reject c1`, `approve all`. Only you approve |
| `/boardwright:pcb-diagnostics` | Optional record of how the work went: `on`, `on without prompts`, `off`, `status`, `report`, `export`, `delete`. Only you turn it on; nothing is sent by itself ([details](../docs/PRIVACY.md)) |

Commands only run read-only checks without asking. Anything that changes your design asks you first.

Each command picks its own model. `pcb-run`, `pcb-auto`, `pcb-new`, `pcb-plan` and `pcb-retro` use Sonnet. `pcb-gates`, `pcb-doctor` and `pcb-undo` use Haiku; `pcb-diagnostics` uses Sonnet. `pcb-review` uses Opus.

## Helpers

The main session runs on Sonnet through the commands. For long, routine jobs Claude hands work to helpers that run on cheaper models. A stronger helper checks the work:

| Helper | Model | Job |
|---|---|---|
| `datasheet-reader` | cheaper | Reads one datasheet and lists the pins and limits, with page numbers |
| `part-scout` | cheaper | Looks up stock, price and lifecycle for a batch of parts |
| `pcb-mechanic` | cheaper | Draws tracks Claude has already planned, and reruns checks |
| `gate-reviewer` | Opus | Gives a second opinion on stages 2, 4, 5, 6, 7 and 8 of every board |

The idea: cheap models do the work, and the strongest model checks it. At stage 4 the reviewer looks at the schematic. At stage 7 it looks at every flagged, unverified or failing line of the parts list, and three more at random. Put `"reviewer": false` in `boardwright.json` to turn it off. It then still runs on boards with dangerous or fast nets.

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
| `python scripts/fab_rules.py . list` | The limits of the chosen factory. `check` lists conflicts with your board and changes nothing. `write [--fab NAME]` adds a marked section to the `.kicad_dru` that never loosens the board's own settings |
| `python scripts/lifecycle_check.py .` | Whether each part with an LCSC number is still sold |

**Editing and history**

| Command | What it does |
|---|---|
| `python scripts/bw_edit.py . '<ops as JSON>'` | Edits the board in one call. The ops are `find`, `move`, `set`, `add`, `delete`, `netclass`, `rule`, `refill`, `place` and `route`. It answers with the DRC difference: new, fixed and unchanged errors, and unconnected before and after. KiCad must not have the board open; otherwise Claude uses the live KiCad tools |
| `python scripts/history.py . list` | Lists the saved steps. `diff` compares two. `restore` goes back to one. It saves the current state first, and refuses while KiCad has the file open |
| `python scripts/history.py . stage-commit N "name"` | Commits only the design files and `reports/` after stage N passes |
| `python scripts/routing_plan.py . verify` | Checks that nothing is routed outside a corridor you approved |

Snapshots are kept on a hidden git ref (`refs/boardwright/steps`), or in `.boardwright/history.git` when the folder is not a git repository. Files are stored byte for byte.

Only one session can edit a board at a time. A lock stops two Claude sessions (for example the KiCad chat window and a terminal) from editing together. The second session can still read. The lock frees at the end of the turn, or after 30 minutes idle.

Two of the ops need a note:

- `place` puts a part within a given distance of a pin. It avoids other parts' courtyards and other nets' copper.
- `route` is a simple grid router. It uses the net class width and clearance, 45 and 90 degree turns, and vias. It refuses mains, hazardous and fast nets: safety domains above ES1, fast pairs, and net classes named like USB, HDMI, Ethernet, PCIe, LVDS, MIPI, DDR, HV or mains. Those are routed by hand.

**Routing plan (optional, off by default).** On bigger boards Claude asks with buttons whether you want it (or type `/boardwright:pcb-plan on`). Approving routes is also a click: Claude lists the corridors as tick boxes. Claude proposes corridors, writes them to `reports/routing-plan.md` and draws them on KiCad's User.4 layer. Only you approve, by typing `/boardwright:pcb-plan approve c1` (or `reject`, or `approve all`). A hook records your approval from what you typed, so Claude cannot approve its own plan. Nothing is routed outside an approved corridor. This is suggested for boards with 4 or more layers or more than about 60 nets.

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
| `python scripts/emc_rules.py .` | Layout mistakes that cause interference: tracks over gaps in the ground copper, missing ground vias, unprotected connectors |
| `python scripts/hs_rules.py .` | Fast pairs such as USB: matching lengths and layer changes |
| `python scripts/impedance_check.py .` | Estimated impedance of fast tracks |
| `python scripts/pdn_check.py .` | Whether each power supply has enough capacitors near the chips |

**Release**

| Command | What it does |
|---|---|
| `python scripts/run_gates.py .` | Runs the checks, then makes the factory files in `fab/` |
| `python scripts/precompliance_pack.py .` | Puts every result into one document for the person who signs off and the test lab |
| `python scripts/sim_export.py .` | Exports the board for professional analysis tools such as HyperLynx or CST |

Factory profiles exist for JLCPCB, PCBWay, OSH Park (2-layer service) and Eurocircuits. They were read from each factory's own pages on 2026-11-16, and each value has its page and date. A value the factory does not publish is "unverified". Most of Eurocircuits' track, gap and ring limits are unverified, because its table is an image. Choose the factory with `"fab"` in `boardwright.json` (the default is `jlcpcb`).

The release check "Fab files up to date" fails when any file in `fab/` is older than the board or schematic.

The lifecycle check reads LCSC's public product data. It needs no key, makes one request a second and keeps answers for 7 days. A discontinued part fails. A part LCSC flags but does not list as discontinued is shown as "nrnd (check)" for a person to confirm. A part with no LCSC number is "unverified", with links. This is the seller's status, not the manufacturer's.

The checks that read the board need the Python that comes with KiCad. They find it and restart under it by themselves, so plain `python` works.

Every check ends with a code: 0 means passed, 1 means a check failed, 2 means something is missing in the setup.

## Where the design rules come from

The rules Claude follows are in `skills/boardwright/references/`. Each rule names its source: manufacturers' application notes, published design guides and KiCad's documentation. Safety distances come from published summaries of IEC 60664-1 and IEC 62368-1. They are marked "secondary source" until someone checks them against the official standard.

## Using Boardwright with other AI agents

The checks are plain Python programs, so other AI coding agents (Codex, OpenCode, Grok and others) can run them too. Every stage can be resumed from the files (`status.py` and `plan.py`) by any session or agent.

- **`AGENTS.md`:** every new project folder gets this file. It holds the same rules as the skill, how to start, and how to pick up a stage another session stopped. Codex, OpenCode and several others read it by themselves. The agent starts with `python scripts/status.py .` and `python scripts/plan.py .`, so it works from the files and not from an old conversation.
- **`scripts/bw_mcp.py`:** a small MCP server. It lets an agent call the read-only and checking programs as tools: `status`, `plan`, `run_gates`, `sch_check`, `history_list`, `fab_check`, `routing_plan_show` and `board_find`. It has no editing tools. The agent edits in its own shell, under the rules in `AGENTS.md`, and only you approve routing corridors.

To add it to an agent that supports MCP servers, register a server that runs the command `python` with the argument `<path>/plugin/scripts/bw_mcp.py`, and set its working directory to the project folder. Each tool also accepts a `project` argument if the agent cannot set the working directory. Where the agent asks for a transport, choose stdio. The server needs only Python and, for `board_find`, KiCad's Python (found the same way as `kicad-cli`; set `KICAD_CLI` if it is not).

## Licence

MIT. See `LICENSE`.
