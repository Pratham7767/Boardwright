---
name: boardwright
description: Design a printed circuit board in KiCad from an idea to fab files, in eight gated stages (spec, parts, power budget, schematic, layout, EMC, BOM, release). Use when the user wants to design, continue, review or release a PCB in KiCad, says "run the pipeline", or opens a folder that has PROJECT.md or boardwright.json.
---

# PCB pipeline

You take a board from an idea to release files in KiCad 9/10. The work is split into eight stages. Each stage ends in a gate and one short report in `reports/`. A failed gate stops the work.

Project facts live in the project folder, not here:
- `PROJECT.md`: the idea, the answers from the interview, the mode, and every decision the user made (with date).
- `boardwright.json`: machine-readable settings for the gate scripts (net-class count, isolation barrier, EMC geometry checks).
- `reports/NN-stage.md`: one per stage. `datasheets/`: one PDF per part. `fab/`: release files.
- `scripts/`: the gate scripts, copied from this plugin by `/boardwright:pcb-new`. If the folder is missing, or `status.py` or `sch_check.py` is not in it, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py" . --update-scripts` (it replaces only the gate scripts).

At the start of every session the plugin's hook puts the output of `scripts/status.py` and `scripts/plan.py` into your context (a note beginning "boardwright session start"). If that note is missing, run both yourself. Then read `PROJECT.md`. Say in two lines which stage the project is at and what is open. Open a report only when you need a detail from it. Do not redo a stage that has a passing report unless its inputs changed.

Read [references/efficiency.md](references/efficiency.md) once per project, before stage 2. It says which script answers which question, how to keep token use down, and what to verify before each expensive step so the design is right the first time.

## Rules that never bend

1. **Never invent a part number, pin function or datasheet value.** If you have not read it in a datasheet in `datasheets/`, write "unverified". Cite file name and page for every pin, voltage limit and footprint choice.
2. **Never disable, waive, filter or loosen a check to make it pass.** If you think a finding is acceptable, list it as a proposed waiver and wait for the user to approve it in chat. Record the approval with the date.
3. **When a gate fails, stop and show the report.** Fix the cause, then rerun the same check. Do not move to the next stage.
4. **Never send, order, upload or publish anything.** The pipeline ends at the files in `fab/`.
5. **Report what happened.** Give counts and numbers. If a check was not run, or a tool was unavailable, say so in the report; do not describe it as passed.
6. **Hazardous voltage is never a normal net.** If any net is above 60 V DC or 30 V AC, or connects to mains, the rules in [references/high-voltage.md](references/high-voltage.md) apply in full and cannot be switched off by the user's mode.
7. **A subagent's result does not count until you have checked it.** See "Who does what".

## The stage graph drives the work

The stages are a graph of small steps (`scripts/pipeline.json`), not a list to walk through. `python scripts/plan.py .` reads the project and prints what is ready now, which of those can run at the same time, what waits on the user, which gates failed and where to go back to, and which finished steps were reopened because a design file changed since.

- Work from its READY NOW list. Do not plan the stage order yourself.
- Start the helper and script steps of one "can run together" group in the same turn.
- Mark a finished non-gate step with `python scripts/plan.py . --done <step>`. Gate steps complete only through their evidence (a passing row in `gates.json`, a report that says PASS, a clean check file).
- A failed gate sends you back to the step the planner names. Fix the cause, rerun the same gate. Three failures at one gate: stop and show the report.
- `/boardwright:pcb-auto <idea>` runs this loop from one prompt. `/boardwright:pcb-retro` looks back at a finished project and proposes pipeline improvements.

## Modes

`PROJECT.md` records the mode. Ask once if it is missing.

| | Guided | Express |
|---|---|---|
| For | someone new to PCB design | someone who can read a schematic |
| Start | interview in plain language, one topic at a time | reads `PROJECT.md`; asks only for missing must-haves |
| Stops | at the steps the planner marks `user` (spec, outline, placement review, hand checks, release checklist) and after each stage report, with a short explanation of what was done and why | only at `user` steps, when a gate fails three times, when a waiver is needed, or for a part swap |
| Explanations | teaches the key choices: for the three or four decisions in a stage that matter, one or two sentences on why; terms defined on first use. Not a full tutorial. | numbers only |

Both modes run the same gates. Express mode never skips one.

## Entry points

`PROJECT.md` records where the project started.

| Entry | Starts at | First steps |
|---|---|---|
| From an idea | stage 1 | interview, then all eight stages |
| From an existing schematic | stage 2 | Write `01-spec.md` from the schematic and the user's answers. Then run stage 2 on the parts as drawn: every part needs an MPN, a datasheet and a pin check against its symbol, exactly as if you had chosen it. Then stage 3, ERC, and on to layout. Do not redraw the user's schematic; list what you would change and ask. |
| Review only | no stage | `/boardwright:pcb-review`: run the gates and the geometry checks, write `reports/review.md`, change nothing in the design. |

An existing design gets no credit for existing: nothing counts as verified until this project's reports show it.

## Stages and gates

Details for each stage are in [references/stages.md](references/stages.md). Read the section for a stage before you start it.

| # | Stage | Gate | Report |
|---|---|---|---|
| 1 | Spec: requirements, block diagram, interfaces, target standard | every requirement has a value and a source (user or ASSUMPTION) | `01-spec.md` |
| 2 | Parts: choose parts, save datasheets, MPN and supplier number in every symbol | every part has a datasheet in `datasheets/` and a cited pin table | `02-parts.md` |
| 3 | Power budget: power tree, worst-case current, dissipation | every rail has at least 20% headroom | `03-power.md` |
| 4 | Schematic | `run_gates.py --sch-only`: rule guard and ERC 0 errors; `sch_check.py`: 0 errors | `04-schematic.md` |
| 5 | Layout: rules, placement, routing, pours | `run_gates.py --no-export`: rule guard pass, DRC with schematic parity 0 errors, 0 unconnected | `05-layout.md` |
| 6 | EMC and signal integrity | no CRITICAL finding; isolation barrier check passes if the board has one | `06-emc.md` |
| 7 | BOM: stock, price, lifecycle | no end-of-life and no out-of-stock part at the suppliers in `PROJECT.md` | `07-bom.md` |
| 8 | Release | `run_gates.py` exports from a freshly refilled copy; `08-release.md` lists every assumption the user must verify | `08-release.md` |

Run the gates with the system Python: `python scripts/run_gates.py . --no-export` (`python3` on macOS and Linux). The scripts that read the board (barrier, EMC, fast-signal, digest, `bw_edit.py`) need KiCad's own Python: they find it and restart under it by themselves, so run them the same way, for example `python scripts/barrier_check.py .`. Never search the disk for KiCad's Python.

A gate that cannot be closed (for example a supplier that cannot be checked) is reported as **NOT PASSED (open)** and carried into the release checklist. Only the user can decide to go on with an open gate, and the release report must say so at the top.

## Who does what

**Cheap models do the work; the strongest model checks it.** Tokens go where they buy the most: doing a task (reading, looking up, editing, writing a report) is done by the cheapest model that can do it well, and deciding whether the result is right is done by the strongest model. The commands set this up themselves: `/boardwright:pcb-run`, `pcb-auto`, `pcb-new`, `pcb-plan` and `pcb-retro` run on Sonnet; `pcb-gates`, `pcb-doctor` and `pcb-undo` only run scripts and run on Haiku; `pcb-review` is verification and runs on Opus.

| Who | Model | Does | Checked by |
|---|---|---|---|
| main session (the commands above) | Sonnet | the stage work: interview, choices, schematic, layout edits with `bw_edit.py`, reports | `gate-reviewer` at every gate, and the scripts |
| `datasheet-reader` | Sonnet | one part per helper: pin table, absolute maximums, footprint drawing, each with page numbers | the main session opens the cited pages for every pin wired; `gate-reviewer` at stage 2 |
| `part-scout` | Haiku | stock, price and lifecycle for a list of part numbers | `gate-reviewer` at stage 7: every flagged, unverified or failing line and three at random |
| `pcb-mechanic` | Sonnet | pushing track and via coordinates already chosen, DRC loops, silkscreen cleanup, running gate scripts | DRC counts and distances, then `gate-reviewer` |
| scripts (`run_gates.py`, `sch_check.py`, the safety, EMC and fast-signal checks) | none | every measurable rule | they are the check |
| `gate-reviewer` | Opus | verifies one stage against its evidence before the gate counts; changes nothing | its findings go to the user |

A helper starts with no context, so give it a complete brief: files, exact inputs, what "done" looks like, what it must not touch. Do small jobs (a few tool calls) yourself; a helper costs more than it saves for those. Run helpers in parallel when their inputs are independent: one `datasheet-reader` per part in stage 2, `part-scout` on batches of about 15 lines in stage 7. Never run two helpers that write the same file, and never more than one helper that edits the board.

`gate-reviewer` runs at stages 2, 4, 5, 6, 7 and 8 of every board (the planner adds the steps; `"reviewer": false` in `boardwright.json` turns them off, except on hazardous or fast boards). On hazardous boards it also checks stages 1 and 3. A gate does not count until its reviewer says "gate may count" or the user has seen and accepted each finding. Do not ask the reviewer to redo work: give it the stage number and let it check the evidence.

Never hand to a helper: choosing parts, pin assignments, placement decisions, routes for mains, switch nodes and feedback lines, rule values, waivers, the EMC judgement, and the release checklist. These stay in the main session and are always part of what `gate-reviewer` checks.

## Asking the user: buttons, not commands

The user should never have to remember a command. When a choice is theirs, ask with the AskUserQuestion tool, so they click a button. Three choices are protected: the plugin records them from the button the user clicks, and refuses a question whose answers you fill in yourself. Use these headers and option labels exactly, or the click is not recorded:

| When | header | question (your words) | options, exactly |
|---|---|---|---|
| once per project, when the session-start note says diagnostics are not decided, at a pause (not mid-task) | `Diagnostics` | one or two sentences: Boardwright can keep a private record of how this project goes (prompts, models, cost, errors) on this computer, which they can send back if they choose; nothing is sent by itself | `Yes, record everything` / `Yes, but not my prompts` / `No` |
| before stage 5 on boards with 4 or more copper layers, more than about 60 nets or fast interfaces | `Routing plan` | what the mode does, in one sentence | `Turn on` / `Keep off` |
| after proposing or changing a routing plan (`routing_plan.py propose` and `draw`) | `Approve routes` | which corridors they approve; set `multiSelect: true` | one option per corridor, `c1: /SDA, /SCL on F.Cu` (the id, a colon, then what it is); at most 4 per question, so ask several questions for more |

The plugin's note after the answer says what was recorded. If the user picks "Other" or closes the question, nothing changes: ask again later or go on without it. The typed commands (`/boardwright:pcb-diagnostics on`, `/boardwright:pcb-plan on`, `/boardwright:pcb-plan approve c1`) still work for users who prefer them.

Ask the other choices with buttons too (no hook needed): guided or express mode, which entry point, a proposed waiver, a part swap, going on with an open gate.

## Working with KiCad

- Board edits go through the `kicad-live` tools while KiCad has the board open, so the user sees each change and can undo it. Never write a `.kicad_pcb` file that KiCad has open. Details and known traps: [references/live-mode.md](references/live-mode.md).
- KiCad cannot edit schematics live. Say what you will change, edit with the schematic tools, ask the user to reload, then run ERC.
- Save with KiCad's save action. When a stage's gate passes, run `python scripts/history.py . stage-commit <N> "<stage name>"`: it commits only the design files and `reports/` (in a folder without git it saves a history step instead).
- Design history: the plugin's hook saves a step after every edit to a design file. `python scripts/history.py . list` shows them; `/boardwright:pcb-undo` takes the user back to one. Restore only when the user asks.
- One editor at a time: the hook gives this session the board's edit lock at its first edit and frees it at the end of the turn. If a tool is denied because another session holds the lock, do not work around it (no other tool, no raw file write): read only, and tell the user which session holds it.
- The session-start note already holds the project's status (stages, gates, ready steps): answer from it, and call `status` only after something changed (an edit, a check, a new report). Do not run the status scripts again to repeat it.
- Use the plugin's `boardwright` MCP tools first: they are cheaper than shell commands and carry the same guards (edit lock, history step, refusals). `status` (where the project is and what is next), `check` (gates, sch, safety, emc, hs, pdn, impedance, fab, lifecycle, blocks, all: failures only), `find` (pads, tracks, vias, zones, nets), `edit` (one batch of ops: move, set, add, delete, netclass, rule, refill), `place`, `route`, `engine`, `plan`, `history`, `fab`, `lifecycle`, `diagnostics`; also `digest` (short board summary, read-only), `setup` (new project, update scripts, doctor) and `export` (release fab files, sim files, pre-compliance pack, parts register, datasheet index). Each answers with the DRC difference or a short result, so no separate DRC run is needed after a batch. The same work is available as scripts (`python scripts/bw_edit.py . '<ops>'`, `python scripts/engine.py . run`) when the MCP server is not available. Board edits need KiCad to have the board closed; while it is open, use the `kicad-live` tools.
- **Routing: the engine first, then you.** At stage 5, after placement is approved, run the `engine` tool (`run`). It routes deterministically under the board's own rules, in strict mode that never lowers a clearance or size: KiCadRoutingTools first, then Freerouting for what is left, each stage kept only if KiCad's DRC shows no new error. It never touches mains or hazardous nets, leaves fast nets and pairs out unless the designer agreed to `--allow-fast`, and respects the routing plan. Then handle only its **leftovers** (`engine leftovers`, or `reports/engine.md`): route those with `route` or `edit`, or by hand for the nets it left out on purpose. Do not route a board net by net when the engine has not run.
- `route` (and `bw_edit` `route`) is for the few connections left: low-risk signal nets only. It refuses mains, hazardous and fast nets by itself; never route those any other way than by hand. You route power, switch nodes, feedback and fast nets by hand, and review every routed net in the DRC difference and the digest.
- If the engine's tools are missing (`engine status`), say so and give the user the one command from the install guide; do not install anything yourself.
- Boards with fast signals or four or more layers: [references/high-speed.md](references/high-speed.md).
- Suppliers, hand checks and regional cost: [references/suppliers.md](references/suppliers.md).
- Design choices that make a board right the first time (stackup, return paths, widths and spacing, crystals, USB protection, inrush, fiducials, KiCad board setup), from Phil's Lab, Robert Feranec's workshop, Altium, ST, TI and the KiCad docs: [references/design-practice.md](references/design-practice.md). Read it before stage 4 and again before stage 5, and choose the stackup from it before placing anything.
- Circuit and layout rules for each block on the board (decoupling, buck, crystal, USB, ESD, I2C, analog, ground, thermal, RF, input protection), from manufacturers' application notes: [references/block-guides.md](references/block-guides.md). Read the sections for the blocks this board has, before stage 4 and again before placement.
- Fab rules: [references/fab-jlcpcb.md](references/fab-jlcpcb.md). Lessons from real runs that cost time: [references/lessons.md](references/lessons.md). Read the lessons file before stage 5. What designers and fabs report going wrong, stage by stage: [references/field-lessons.md](references/field-lessons.md); go through the part for a stage before its gate.

## Limits to state in every release report

- A clean ERC and DRC only prove the board obeys the rules that were set.
- The EMC stage is a risk estimate from geometry, not a compliance result. A lab measurement is required.
- Pin and footprint choices must be checked by a person against the datasheets before ordering.
- A board with hazardous voltage must be reviewed by a qualified person before it is powered.
