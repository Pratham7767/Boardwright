---
name: pcb-gates
description: Run the ERC/DRC gates (and the barrier and EMC geometry checks if configured) without exporting, and show the counts
disable-model-invocation: true
allowed-tools: Bash(python scripts/run_gates.py . --no-export), Bash(python scripts/sch_check.py .), Bash(python3 scripts/run_gates.py . --no-export), Bash(python3 scripts/sch_check.py .), PowerShell(python scripts/run_gates.py . --no-export), PowerShell(python scripts/sch_check.py .), Bash(python scripts/safety_class.py .), PowerShell(python scripts/safety_class.py .), Bash(python scripts/mains_check.py .), PowerShell(python scripts/mains_check.py .), Bash(python scripts/creepage_rules.py .), PowerShell(python scripts/creepage_rules.py .), Bash(python scripts/emc_harmonics.py .), PowerShell(python scripts/emc_harmonics.py .)
---

Run the read-only checks for the PCB project in the current folder and report the results. Change nothing.

1. `python scripts/run_gates.py . --no-export`. Show the gate table.
   Then `python scripts/sch_check.py .` and show its summary line and every error.
2. If `boardwright.json` has a `safety` section: `python scripts/safety_class.py .` and `python scripts/mains_check.py .`; after the DRC and barrier runs, `python scripts/creepage_rules.py .` (check mode only; never `--write` here). If it has `high_speed`: `<kicad>/bin/python -I scripts/hs_rules.py .`. If `emc.clocks` is set: `python scripts/emc_harmonics.py .`.
3. If `boardwright.json` has a `barrier` section, run `barrier_check.py` with KiCad's bundled Python and show the closest distance and the limit.
4. If it has an `emc` section, run `emc_geometry.py` the same way and show every row that is not ok.
5. List every error verbatim. For warnings, give the count per type.
6. If the rule guard failed, say that the DRC result cannot be trusted until it passes, and what to restore.

Do not fix anything in this command. Offer the fix as the next step.
