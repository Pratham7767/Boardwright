---
name: pcb-plan
description: Routing plan mode for complex boards. The designer turns it on or off, and approves or rejects the corridors Claude proposes, before anything is routed
model: sonnet
disable-model-invocation: true
argument-hint: "on | off | approve <ids or all> | reject <ids> | nothing to show the plan"
allowed-tools: Bash(python scripts/routing_plan.py . show*), Bash(python3 scripts/routing_plan.py . show*), PowerShell(python scripts/routing_plan.py . show*)
---

You are already in the project folder: do not `cd`.

The designer typed `/boardwright:pcb-plan $ARGUMENTS`. The plugin's prompt hook has already recorded what they decided (look for its note: "Routing plan mode turned ..." or "Routing plan: approved ..."). You never approve, reject or switch the mode yourself, and you do not edit the plan file.

- **on / off**: confirm the mode in one line. When it is on and the board has no plan yet, propose one now (see below) and stop for the designer.
- **approve / reject**: run `python scripts/routing_plan.py . show` and say what is approved, rejected and still proposed. Then route only the approved corridors: `python scripts/bw_edit.py . '{"route": [...]}'` for ordinary nets (it keeps them inside their corridor), by hand for power, switch nodes, feedback and fast nets. Finish with `python scripts/routing_plan.py . verify`. For a rejected corridor, ask what the designer wants instead and propose again.
- **nothing**: run `python scripts/routing_plan.py . show` and explain the plan in plain words.

How to propose a plan (mode on):
1. Read the stackup and the net classes. Choose a reference plane for each signal layer.
2. Group the nets into corridors: nets that run together, with one layer (or two, with the via places in the path), a width from the net class or the impedance target, and a path of points from pads to pads.
3. Write the plan as JSON and run `python scripts/routing_plan.py . propose @plan.json`, then `python scripts/routing_plan.py . draw` (KiCad closed) so the corridors show on the User.4 layer.
4. Tell the designer how to look (turn on User.4 in KiCad, or read `reports/routing-plan.md`) and how to answer: `/boardwright:pcb-plan approve c1 c2`, `reject c3`, `approve all`. Then stop.
