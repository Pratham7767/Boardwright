# {{PROJECT_NAME}}: instructions for any AI coding agent

This folder is a KiCad project run with Boardwright. These instructions are for any agent that works here (Codex, OpenCode, Grok, Claude Code and others). Boardwright takes a board from an idea to factory files in eight gated stages. Small Python programs check the work. A stage only counts when its check passes.

## Rules that never bend

1. Never invent a part number, pin function or datasheet value. If you have not read it in a datasheet in `datasheets/`, write "unverified". Name the file and page for every pin, voltage limit and footprint choice.
2. Never disable, waive, filter or loosen a check to make it pass. If you think a finding is acceptable, list it as a proposed waiver and wait for the user to approve it in chat. Record the approval with the date.
3. When a gate fails, stop and show the report. Fix the cause, then run the same check again. Do not move to the next stage. After three failures at one gate, stop and ask the user.
4. Never send, order, upload or publish anything. The work ends at the files in `fab/`.
5. Report what happened. Give counts and numbers. If a check was not run, or a tool was missing, say so. Never describe it as passed.
6. Hazardous voltage is never a normal net. If any net is above 60 V DC or 30 V AC, or connects to mains, follow `references/high-voltage.md` in full. The user's mode cannot switch this off.
7. A helper's result does not count until you have checked it. This applies to another agent, a subagent or a cheaper model: open the files it cites and confirm the numbers.

Also: keep the KiCad project files in this folder's root, and work only inside this folder.

## How to start

Run these two commands from the project folder, then read `PROJECT.md` (the project facts and every decision the user made):

    python scripts/status.py .
    python scripts/plan.py .

If there is no `PROJECT.md` or `boardwright.json`, this is a new project: ask the user what the board must do before doing anything else.

## How to work

`python scripts/plan.py .` prints a READY NOW list, the steps that can run together, the steps that wait on the user, failed gates and the step to go back to. Work from that list. Do not plan the stage order yourself.

- Finish a non-gate step, then mark it: `python scripts/plan.py . --done <step>`
- A gate step is done only by its evidence (a passing row in `reports/gates.json`, a report that says PASS). You cannot mark it done.
- A step marked `user` waits for the user. Ask, and wait for the answer.
- Run `plan.py` again after each step. It also shows steps reopened because a design file changed.

## The main commands

Run from the project folder. Each prints a short result and writes full detail to `reports/`. Exit 0 means passed, 1 means a check failed, 2 means a setup problem.

| Command | Use |
|---|---|
| `python scripts/run_gates.py . --no-export` | KiCad's wiring check (ERC) and layout check (DRC) |
| `python scripts/run_gates.py .` | The same, then the factory files in `fab/`. Only at release. |
| `python scripts/sch_check.py .` | Part details, pin numbers, unconnected pins, decoupling |
| `python scripts/bw_edit.py . '<JSON>'` | Board edits and searches. Add `--dry-run` to try first. |
| `python scripts/bw_edit.py . '{"find": {"kind": "pad", "ref": "C3"}}'` | Look only. Nothing is saved. |
| `python scripts/history.py . list` | The saved steps, newest first |
| `python scripts/history.py . diff A [B]` | Files changed between two steps |
| `python scripts/history.py . restore N` | Put the design files back to step N. Ask the user first. |
| `python scripts/fab_rules.py . check` | Board setup against the factory's published minimums |
| `python scripts/routing_plan.py . show` | The routing plan as a table |

Scripts that read the board need KiCad's own Python; they find it and restart under it by themselves, so plain `python` works (`python3` on macOS and Linux). Close KiCad's board first, or the edit is refused (its `~*.lck` file).

Mains boards also have `safety_class.py`, `mains_check.py` and `creepage_rules.py`. Fast-signal and interference boards have `emc_rules.py`, `hs_rules.py`, `pdn_check.py` and `impedance_check.py`. `plan.py` says when each applies.

The plugin also has an MCP server for the read-only and checking commands: `scripts/bw_mcp.py`. It has no editing tools. Edit in your own shell under these rules.

## Where the reference documents are

The design rules are in the plugin's `skills/boardwright/references/` folder: `stages.md` (what each stage does and its checks), `high-voltage.md`, `high-speed.md`, `fab-jlcpcb.md`, `design-practice.md`, `lessons.md` and others. Read the one for the stage you are on. Each rule names its source. This project's own copies of the scripts are in `scripts/`. Datasheets are in `datasheets/`, reports in `reports/`, release files in `fab/`.

## Picking up where someone else stopped

Everything is in files: `PROJECT.md`, `reports/`, `reports/gates.json`, and the saved steps in `history.py`. A new session, or another agent, resumes by running `python scripts/status.py .` and `python scripts/plan.py .`, then reading `PROJECT.md` and the newest stage report. Never work from memory of an old conversation, and never believe a claim that a stage passed unless the file says so. If the files and what you were told disagree, believe the files and tell the user.

Before you change the design, take the edit lock (`python scripts/history.py . lock take <your name>`) and release it when done, so two agents do not edit at once. If `history.py . list` shows steps you did not make, read `diff` before you edit.

## Routing plan: only the designer approves

If `boardwright.json` has `"routing_plan": true`, tracks may only run inside corridors the designer has approved. You may propose corridors. You may not approve them, and you may not edit the routing plan file in `reports/` by hand. In Claude Code the designer types `/boardwright:pcb-plan approve c1 c3`. In any other agent, ask the user which corridors they approve; the approval is recorded only by the user themselves, in Claude Code. Until they do, do not route those nets.

## Who does what

Cheap models do the work: reading, looking up parts, editing, writing reports, running scripts. A strong model verifies each gate: it reads the stage report and the files behind it, checks the numbers, and says whether the gate may count. A gate does not count until that check is done. Never hand these to a helper or subagent: choosing parts, pin assignments, placement, routes for mains, switch nodes and feedback lines, rule values, waivers, the EMC judgement and the release checklist. They stay with the main session, and the strong model always checks them.
