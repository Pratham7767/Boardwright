---
name: pcb-retro
description: After a board - look back at what cost time or went wrong in this project and propose concrete improvements to the pipeline
disable-model-invocation: true
---

Review how this project went and write `reports/retro.md`. Change nothing in the design.

Collect the evidence (scripts first, then only the files you need)
1. `python scripts/status.py .` and `python scripts/plan.py . --all`.
2. `git log --format="%ad %s" --date=short`: how many commits each stage took and which stages were revisited.
3. From the stage reports: every gate that failed and why, every item marked unverified or open, every swap, every waiver.
4. `reports/gates.json`, `sch-check.json`, `emc-geometry.json` if present: warnings that stayed.

Write `reports/retro.md`, at most 60 lines
- **Rework:** each time work was redone (a stage revisited, a part swapped after the schematic, a route redone), with the cause and the stage where it could have been caught earlier.
- **Late findings:** problems found at a later stage than the one that owns them.
- **Wasted steps:** steps that produced nothing the later stages used.
- **Checks that never fired** on this board, and checks that were missing.
- **Tool problems:** scripts or tools that failed, were slow, or returned too much text.
- **Proposals:** for each finding, one concrete change: a line for the skill's lessons file, a new script check (what to compare with what), a planner change (a dependency, a node to run earlier or in parallel, a node to remove), or a template change. Mark each as "evidence: this project" and say how often it happened.

Rules
- Only findings you can point to in a file, a commit or a gate report. No general advice.
- Do not edit the plugin from inside a project. The retro is a proposal; the plugin's maintainer applies it and records it in the plugin's lessons file.
- Tell the user where the file is and list the three proposals that would have saved the most time.
