---
name: pcb-gates
description: Run the ERC/DRC gates (and the barrier and EMC geometry checks if configured) without exporting, and show the counts
disable-model-invocation: true
allowed-tools: Bash(python scripts/run_gates.py . --no-export), Bash(python scripts/sch_check.py .), Bash(python3 scripts/run_gates.py . --no-export), Bash(python3 scripts/sch_check.py .), PowerShell(python scripts/run_gates.py . --no-export), PowerShell(python scripts/sch_check.py .)
---

Run the read-only checks for the PCB project in the current folder and report the results. Change nothing.

1. `python scripts/run_gates.py . --no-export`. Show the gate table.
   Then `python scripts/sch_check.py .` and show its summary line and every error.
2. If `boardwright.json` has a `barrier` section, run `barrier_check.py` with KiCad's bundled Python and show the closest distance and the limit.
3. If it has an `emc` section, run `emc_geometry.py` the same way and show every row that is not ok.
4. List every error verbatim. For warnings, give the count per type.
5. If the rule guard failed, say that the DRC result cannot be trusted until it passes, and what to restore.

Do not fix anything in this command. Offer the fix as the next step.
