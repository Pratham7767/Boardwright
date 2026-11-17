# Getting it right the first time, with fewer tokens

Most of the cost of a board is rework: a wrong pinout found at layout, a placement that cannot be routed, a rule that was never applied. And most of the tokens go to reading large tool results and re-reading what is already known. The two problems have the same cure: let scripts do the checking and the summarising, and decide once, early, with the facts in hand.

## Scripts before reading

Use the script that answers the question. Do not page through tool listings or open design files to work out something a script prints in a few lines.

| Question | Use | Not |
|---|---|---|
| Where is this project, what is open? | `python scripts/status.py .` | reading every report |
| What is on the board? | `board_digest.py . --section summary` (then `parts`, `nets`) | listing footprints, tracks and nets tool by tool |
| What is around this part? What does this route look like? | `board_digest.py . --section near REF` / `--section net NAME` | exporting the board as text |
| Is the schematic sound? | `python scripts/sch_check.py .` | reading the schematic file |
| Do the gates pass? What failed? | `python scripts/run_gates.py . --no-export` (prints errors grouped by type) | opening `drc.json` |
| Is the barrier intact? EMC geometry? | `barrier_check.py`, `emc_geometry.py` | measuring pad by pad |
| Are the block rules met (decoupling distance, protection parts at connectors, crystal load, I2C pull-ups, track width for current, release files)? | `block_check.py` | checking part by part |
| Where exactly is this pad, track or via, and how big is it? | `bw_edit.py . '{"find": {"kind": "pad", "ref": "U1"}}'` | parsing the board file, or writing a parser |
| Change the board (move, rotate, set width, add or delete tracks and vias, net class, rule, refill) | one `bw_edit.py` call with every op in a list; it answers with the new DRC difference | many small tool calls, then a separate DRC |
| Put a capacitor next to a pin | `bw_edit.py . '{"place": {"ref": "C5", "near": "U1.17", "within": 2}}'` | trying positions by hand |
| Route ordinary nets (LEDs, pull-ups, slow signals) | `bw_edit.py . '{"route": ["/LED1", "/SDA"]}'` | writing a router; drawing every segment by hand |

`board_digest.py`, `bw_edit.py`, `barrier_check.py`, `emc_geometry.py` and `block_check.py` read the board with KiCad's own Python; they find it and restart under it by themselves, so run them with plain `python`. Never search the disk for KiCad's Python. `bw_edit.py` edits the board file, so KiCad must not have it open; when it does, edit with the `kicad-live` tools (`bw_edit.py ... --dry-run` lists a route's segments for `pcb_add_tracks`).

## Datasheets: read pages, not files

Datasheets are the largest single token cost. Never open a whole PDF to find a pin table.

1. `uv run scripts/datasheet_index.py . <part>` writes `datasheets/.index/<name>.index.txt` (what is on each page) and `<name>.extract.txt` (the text of the pin, ratings, package and ordering pages only).
2. `datasheet-reader` reads the extract first. It opens a PDF page only when the extract shows the fact is in a drawing or on a page with no text, and then only that page.
3. Page numbers in the extract are PDF page numbers; cite them as they are.
4. The reader's result is saved as `datasheets/<MPN>.facts.md`. Before starting a reader for a part, look for that file: a part read once is not read again, in this project or the next. Copy facts files of parts you reuse into the new project's `datasheets/` together with the PDF.
5. An extract is a finding aid, not the source. Anything safety-relevant (insulation ratings, absolute maximums of hazardous-voltage parts) is confirmed on the PDF page itself.

## Speed without losing quality

Faster means fewer round trips and less waiting, never fewer checks.

- **Run independent work at the same time:** all `datasheet-reader` helpers of stage 2 together; `part-scout` batches together; the stage 3 power budget while they run.
- **Look at stock early.** One quick `part-scout` pass over the non-passive parts at the end of stage 2 saves a re-layout after stage 7.
- **Reuse proven blocks.** A regulator or interface block that passed all gates in an earlier project of the user is copied with its facts files and report rows, and marked "reused from <project>". It still goes through this project's gates.
- **Combine the cheap gates.** After a batch of edits run the rule guard, ERC, DRC and `sch_check.py` in one command line and read one result.
- **Express mode stops less, checks the same.**
- **What may never be skipped for speed:** the pin and footprint check of every non-passive part, the rule guard, DRC with parity after the last edit, the barrier check on hazardous boards, the refill before export, and the user's review of placement and of the release checklist.

## Token rules

1. **Read once.** A report, datasheet page or digest you have read in this session is known. Do not reopen it to quote it.
2. **Ask for the part, not the whole.** One section of a digest, one page range of a datasheet, the first lines of a report.
3. **Batch board edits.** One call with all tracks of a route, not one call per segment. One DRC per batch, not per edit.
4. **Helpers get briefs, not context.** A brief names files, inputs, limits and the shape of the answer, and asks for a short report. Never ask a helper to "look around".
5. **Helpers return tables.** Ask for a fixed table and a line count limit. Long prose from a helper is paid for twice.
6. **Do not delegate small jobs.** Under about five tool calls, do it yourself: a helper starts cold.
7. **State lives in files.** Decisions go into `PROJECT.md`, results into `reports/`. A new session starts from `status.py`, not from the old conversation.
8. **Do not narrate.** One line per step is enough for the user to follow.

## First-pass quality: decide early, verify before building on it

Each stage has a point after which mistakes become expensive. Verify just before it.

**Before drawing the schematic (end of stage 2)**
- Every pin you will wire has been read from the datasheet for the exact package and compared with the symbol. This is the single most common cause of a dead board.
- Every footprint has been compared with the land pattern drawing.
- Start from the manufacturer's reference design or typical application circuit and record every deviation. Do not design a regulator or an interface from memory.

**Before layout (end of stage 4)**
- `sch_check.py` has no errors: fields complete, every symbol pin has a pad in its footprint, no single-pin nets left unexplained, every IC power pin has a capacitor.
- Net classes, custom rules and `expect_netclass_patterns` are in place and the rule guard passes. Rules come before copper.
- The board outline, mounting holes and connector positions are fixed with the user. Moving a connector after routing costs the routing.

**Before routing (placement review)**
- Write a floorplan first: blocks in current-flow order, the critical loops of each block listed with the parts that form them. Place from the floorplan, not part by part.
- Place the parts of each critical loop together and measure the loops with `emc_geometry.py` on the placement alone. A loop that is too big at placement stays too big after routing.
- Check the unrouted list from `board_digest.py`: crossing ratsnest lines between blocks mean a part is turned the wrong way. Rotate now.
- Check mechanical conflicts: tall parts, heatsinks, connector access, courtyard overlaps (through-hole courtyards count on both sides).
- Show the user the placement and stop. This is the cheapest review in the whole project.

**While routing**
- Order: hazardous and high-current paths, switch nodes, fast nets, feedback and sense lines, then everything else, then pours.
- Decide each critical route completely (layer, width, path) before pushing it. Use `--section near` to see what is in the way.
- Run the gate after each net group, not at the end. Ten errors are easy to place; a hundred are not.

**Before release**
- Refill, rerun everything, and compare each number in the reports with the script output of the final board. A report written before the last change is out of date.

## What cannot be done in one pass

Say this to the user instead of promising it: part choices depend on stock that is only known at stage 7; EMC is only known after a lab measurement; and the user's own decisions (connectors, enclosure) arrive when they arrive. The pipeline reduces rework; it does not remove review.
