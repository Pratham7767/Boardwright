# Plan for 0.6: ideas borrowed from Backplane

Backplane (github.com/BackplaneWorks/Backplane, MIT licence) is a large agent workspace for KiCad. We studied it on 2026-11-17 and chose what to borrow. Boardwright keeps what makes it different: the eight stages with their checks, the safety, interference, fast-signal and power checks, standard KiCad, Windows support, and no ordering, uploading or usage counting.

The numbers in brackets are the feature numbers from that review.

## Rules that do not change

- A check is never switched off to make it pass.
- Mains and other dangerous nets, and fast pairs such as USB, are never routed automatically.
- Nothing is ordered, uploaded or sent. No keys or passwords are asked for or stored.
- Everything works with standard KiCad 10.

## Phase 0: measure first

Run 5 tasks on the example board (move parts, set a net class, route a few nets, place decoupling capacitors, fix a DRC error), 2–3 times each, and record tokens, tool calls, time, cost and pass/fail in `docs/benchmark.md`.

**Done when:** there is a "before" table. Every later phase is measured against it.

## Phase A: never lose work

**A1. Snapshot after every edit [17].** After each change to the board or schematic, save a copy in hidden git refs (`refs/boardwright/steps`), without touching the user's branch. `/boardwright:pcb-undo` lists the steps, compares two of them and goes back to one. A folder without git gets its own private history in `.boardwright/history.git`.

**A2. A commit after each stage, and one editor at a time [18].** When a stage's check passes, commit the design files with the message `stage N: <name> passed`. A lock file stops two Claude sessions (for example, the KiCad chat window and a terminal) from editing the same board at once. The second session reads only, and says who holds the lock.

**Done when:** an edit can be undone from any earlier step, and two sessions cannot both write the same board.

## Phase B: cheaper editing

**B1. One-call edit tool [6].** `bw_edit`: find, move, set, add and delete parts, tracks, vias and zones, set net classes and rules, and refill zones, in one call. It answers with the new state and which DRC errors are new, fixed or unchanged. It uses KiCad's live connection when KiCad is open, and KiCad's Python otherwise. Its output is capped, and a lookup includes pad sizes, so Claude never needs to parse the board file itself.

**B2. Place next to a pin [8].** `place: {ref: "C5", near: "U1.26", within: 2}` puts a part beside a pin and reports the distance.

**B3. A simple router [7].** A grid router that uses each net class's width and clearance, keeps to 45° and 90° turns, and sends all its tracks in one batch. It refuses mains, dangerous and fast nets and names them.

**Done when:** the Phase 0 tasks take a few calls each, and DRC and all our checks still pass.

## Phase C: routing plan mode for complex boards [9]

A mode the designer chooses, off by default. Turn it on with `/boardwright:pcb-new`, or with `"routing_plan": true` in `boardwright.json`. It is suggested, never forced, for boards with 4 or more layers or more than 60 nets.

1. Claude proposes a plan: the reference planes per layer, and a corridor for each group of nets, with its layer, width and impedance from the stackup.
2. The plan is written to `reports/routing-plan.md` and drawn on a user layer in KiCad (`User.4`), so the designer sees the corridors on the board.
3. The designer approves, edits or rejects each corridor. Only the designer can approve.
4. Claude routes only what was approved, inside its corridor, with B3 or by hand, and the checks run.

**Done when:** on a 4-layer test board, nothing outside an approved corridor gets routed, and a rejected corridor stays empty.

## Phase D: better checks

**D1. More factory profiles [11].** Add profiles for PCBWay, OSH Park and Eurocircuits next to JLCPCB. Each value records its page and the date it was read, and a value that can't be read again keeps its old one: never a guess. A factory's limits go into the KiCad rules file inside a marked section, and the user's own rules are never overwritten or loosened.

**D2. Old factory files [14].** The release check fails when anything in `fab/` is older than the board or schematic.

**D3. Lifecycle [16].** Flag parts that are end-of-life, obsolete or not recommended for new designs, using a public source that needs no key. The source is still to be chosen; until then the result is "unverified".

**Done when:** each check has a test with a planted fault, and `tools/check_all.py` runs them.

## Phase E: other AIs [1, 2]

**E1.** Add an `AGENTS.md` and a tool server that expose the checks, so Codex, Grok and other agents can run the same stages.

**E2.** Make every stage resumable from its report, so work stopped by a usage limit can continue in another AI or another session.

**Done when:** one stage runs end to end in a second agent.

## Not borrowed

Their KiCad fork, live co-editing, review markers inside KiCad, the DRC second opinion, the secrets vault, ordering, the viewers and embedded editors, the phone and web apps, bots, voice and usage counting.

## Order

Phase 0, then A, B, C, D, E. Phases D and E don't depend on B, so they can start earlier. Each phase ends with `python tools/check_all.py` and an entry in `CHANGELOG.md`.
