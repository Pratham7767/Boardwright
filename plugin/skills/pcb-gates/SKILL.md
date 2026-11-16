---
name: pcb-gates
description: Run the ERC/DRC gates and the safety, EMC and high-speed checks that are configured, without exporting, and show the results
disable-model-invocation: true
allowed-tools: Bash(python scripts/run_gates.py . --no-export*), Bash(python scripts/sch_check.py .*), Bash(python3 scripts/run_gates.py . --no-export*), Bash(python3 scripts/sch_check.py .*), PowerShell(python scripts/run_gates.py . --no-export*), PowerShell(python scripts/sch_check.py .*), Bash(python scripts/safety_class.py .*), PowerShell(python scripts/safety_class.py .*), Bash(python scripts/mains_check.py .*), PowerShell(python scripts/mains_check.py .*), Bash(python scripts/creepage_rules.py .*), PowerShell(python scripts/creepage_rules.py .*), Bash(python scripts/emc_harmonics.py .*), PowerShell(python scripts/emc_harmonics.py .*), Bash(* -I scripts/barrier_check.py .*), PowerShell(* -I scripts/barrier_check.py .*), Bash(* -I scripts/emc_geometry.py .*), PowerShell(* -I scripts/emc_geometry.py .*), Bash(* -I scripts/hs_rules.py .*), PowerShell(* -I scripts/hs_rules.py .*), Bash(* -I scripts/board_digest.py .*), PowerShell(* -I scripts/board_digest.py .*)
---

Run the read-only checks for the PCB project in the current folder (you are already in it: no `cd`) and report the results. Change nothing. Run them in this order: the creepage cross-check needs fresh DRC and barrier results.

`<kicad python>` below is KiCad's bundled Python: `python.exe` next to `kicad-cli` (Windows), or `python3` on Linux. Always run it with `-I`.

1. `python scripts/run_gates.py . --no-export`: show the gate table. Then `python scripts/sch_check.py .`: its summary line and every error.
2. Board measurements, if their section exists in `boardwright.json`:
   - `barrier`: `<kicad python> -I scripts/barrier_check.py .`: the closest distance and the limit.
   - `emc`: `<kicad python> -I scripts/emc_geometry.py .`: every row that is not ok.
   - `high_speed`: `<kicad python> -I scripts/hs_rules.py .`: each pair's skew, vias and result.
3. `safety` section: `python scripts/safety_class.py .`, `python scripts/mains_check.py .`, and last `python scripts/creepage_rules.py .` (check mode only; never `--write` in this command).
4. `emc.clocks` set: `python scripts/emc_harmonics.py .` (a measurement plan, not a gate).
5. List every error verbatim. For warnings, give the count per type.
6. If the rule guard failed, say that the DRC result cannot be trusted until it passes, and what to restore.

Do not fix anything in this command. Offer the fix as the next step.
