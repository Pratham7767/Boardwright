# Changelog

## 0.7.0 (2026-11-18)
An MCP server for every feature, a deterministic routing engine that routes before Claude does, and a new chat window inside KiCad. One download (the KiCad add-on) gives all of it.

**MCP server (`plugin/scripts/bw_mcp.py`)**
- 15 compact tools: status, check, find, edit, place, route, plan, history, fab, lifecycle, diagnostics, engine, setup (new project, update scripts, doctor), digest (board summary, parts, nets, unrouted, near, net, area) and export (release files, simulation, pre-compliance pack, parts register, datasheet index). One-line answers, failures only.
- The same guards as the hooks: write tools take the one-editor lock and save an undo step; the user's own decisions (routing-plan approval, diagnostics consent, undo, the choices file) have no tool.
- Measured on the example board (three questions, Sonnet, plan mode): Boardwright's MCP alone used 21 % fewer input tokens and 40 % fewer tool calls than running the scripts. With the two other KiCad servers loaded as well, the same questions cost twice as much; see `docs/benchmark-engine.md`.

**Routing engine (`plugin/scripts/engine.py`)**
- Routes first, without Claude: KiCadRoutingTools in its strict mode (never lowers a clearance or size), then Freerouting for what is left. KiCad's DRC checks every result. A net whose new copper adds a DRC error is dropped and the rest is kept, so one bad net no longer throws away a whole stage. Claude only handles the leftovers.
- Mains and hazardous nets are never routed by the engine; fast nets (USB and the like) only with `--allow-fast`; the routing plan's approvals are respected.
- Open connections are counted with KiCad's connectivity, so big boards are counted completely (the DRC list stops at 499). Nets with a copper pour (planes, GND) are routed last with a shorter limit. Freerouting stops at the time limit and keeps what it routed.
- One-step install of its tools (a Java runtime, Freerouting 2.5.0, KiCadRoutingTools 0.24.1), each checked against a fixed checksum: from the chat's Setup checks, the installers, or `setup_engine.ps1` / `setup_engine.sh`.

**Chat window inside KiCad**
- A new look: day and night colours, a calm welcome screen with a living ring (it follows the mouse; drag it, click it), suggestions above a large message box, a round send button that becomes a stop button.
- Docked to the right side of the PCB Editor by default; it follows the editor.
- A row with the eight stages: green done, red needs attention; click one to ask about it.
- Remembers the colours, the mode, the model and the last conversation per board ("Continue last chat").
- The cost after each answer is now the cost of that answer (Claude Code reports a running total; the chat showed the total as if it were the last answer).
- After sign-in, one question: keep a private usage log? Nothing is sent by itself. "Send feedback" puts the feedback and the redacted report on the clipboard and opens a new GitHub issue for the user to post.
- The routing engine is one of the Setup checks, with an Install button that says what it downloads and asks first.

**Fixed**
- Mains nets were not protected through their safety domains since 0.6 (the safety report gave a count where a list was expected). Hazardous nets are now always left to the designer, and a mains board whose safety setup cannot be read treats every net as hazardous.
- KiCad's Python could show "Font ... not found" message boxes that waited for a click and froze unattended runs.

**Docs**
- A user guide with screenshots and baby steps: `docs/Boardwright-User-Guide.pdf`.

## 0.6.1 (2026-11-17)
No commands to remember, and the fixes from an independent review of 0.6.0.

**Choices by buttons**
- No commands to remember: when a choice is the user's (diagnostics, routing plan mode, which routes to approve, guided or express), Claude asks with buttons. For the protected choices the plugin records the click itself (a hook reads the answer) and refuses a question whose answer Claude fills in. The typed commands still work.
- Routing plan mode and other user choices now live in `.boardwright/choices.json`, which tools cannot write. Before, the mode was a `boardwright.json` setting Claude could have switched off itself.

**Fixed after an independent review (Opus)**
- History: two projects in one git repository shared one history, so undoing in one could overwrite the other's files. Each project now has its own (`refs/boardwright/steps/<id>`; an older shared history is moved aside, not deleted). Saves from several sessions at once could store empty or lost steps: each save now uses its own index and a lock. Undo crashed on file names with non-English characters.
- Guards: the hooks now also watch PowerShell, notebook edits, the questions Claude asks, and other KiCad tool servers. In routing plan mode, a plane needs the designer's approval like a corridor (a signal net listed as a plane was a way around it), and pasting raw KiCad text is refused. Writing the plan file with `tee` is refused; just reading a protected file is allowed.
- Board edits: `--dry-run` really writes nothing now (it wrote the net classes and rules). A batch is all or nothing: if one step fails, nothing is saved. A failed `place` puts the part back. In routing plan mode, `add` keeps tracks inside the approved corridor. The router checks a via against every copper layer, not only the layers it routes on.
- Diagnostics: more secrets are removed (OpenAI-style, Firecrawl, Google and Slack keys, JWTs, `api_key=`, `secret=`, `passwd=`, e-mails written as "name at mail dot com", and the git name and e-mail). The summary Claude writes is kept when the report is exported. Requests in fast mode or US-only inference are counted but not priced (they cost more; no guess).
- Smaller: the lifecycle report's `pass` matches its exit code; factory profiles count inner layers of any type; KiCad's Python is found inside the macOS app; the tool server for other agents is truly read-only and only works in Boardwright projects.

## 0.6.0 (2026-11-17)
Undo after every edit, cheaper board editing, an optional routing plan, more factory profiles, and a split between cheap models that do the work and the strongest model that checks it. Many ideas come from Backplane (see `THIRD_PARTY.md`); no code was copied.

**Design history**
- A hook saves a snapshot of the design files after every edit. `history.py . list | diff | restore` and the new `/boardwright:pcb-undo` command use it. Snapshots live on a hidden git ref (`refs/boardwright/steps`), or in `.boardwright/history.git` when the folder is not a git repository. Files are stored byte for byte. A restore saves the current state first, and refuses while KiCad has the file open.
- `history.py . stage-commit N "name"` commits only the design files and `reports/` after a stage passes.
- One editor at a time: a lock stops two Claude sessions from editing the same board. The second can still read. The lock frees at the end of the turn or after 30 minutes idle.

**Editing**
- `bw_edit.py`: find, move, set, add, delete, netclass, rule, refill, place and route in one call. It answers with the DRC difference (new, fixed and unchanged errors; unconnected before and after). KiCad must not have the board open; otherwise use the live KiCad tools.
- `place` puts a part within a given distance of a pin, avoiding other parts' courtyards and other nets' copper.
- `route` is a simple grid router. It uses the net class width and clearance, 45 and 90 degree turns, and vias. It refuses mains, hazardous and fast nets. On the example board it routed five short nets in about 8 seconds with no new DRC errors.
- Routing plan mode, optional and off by default: `/boardwright:pcb-plan on`. Claude proposes corridors in `reports/routing-plan.md` and on KiCad's User.4 layer. Only the designer approves, by typing `/boardwright:pcb-plan approve c1`. A hook records it from what the designer typed, so Claude cannot approve its own plan. Nothing is routed outside an approved corridor. `routing_plan.py . verify` checks it.

**Checks**
- `fab_rules.py`: factory profiles for JLCPCB, PCBWay, OSH Park (2-layer service) and Eurocircuits, read from each factory's own pages on 2026-11-16. Every value has its page and date. Values a factory does not publish are "unverified". `write` adds a marked section to the `.kicad_dru` that never loosens the board's own settings. Choose the factory with "fab" in `boardwright.json`.
- The release check "Fab files up to date" fails when any file in `fab/` is older than the board or schematic.
- `lifecycle_check.py`: reads LCSC's public product data (no key, one request a second, cached 7 days). Discontinued fails. A part LCSC flags but does not list as discontinued is "nrnd (check)" for a person to confirm. Parts with no LCSC number are "unverified", with links. It is the distributor's status, not the manufacturer's.

**Running the board scripts**
- The scripts that read the board (`bw_edit.py`, `board_digest.py`, the barrier, EMC and fast-signal checks) now find KiCad's own Python and restart under it by themselves, so plain `python scripts/...` works. The first benchmark showed Claude spending six to eight tool calls searching the disk for KiCad's Python and then editing the board file by hand instead.

**Models**
- Commands now set their own model: `pcb-run`, `pcb-auto`, `pcb-new`, `pcb-plan` and `pcb-retro` on Sonnet; `pcb-gates`, `pcb-doctor` and `pcb-undo` on Haiku; `pcb-review` on Opus.
- `gate-reviewer` (Opus) now checks stages 2, 4, 5, 6, 7 and 8 of every board by default (before, only 2, 5, 6 and 8 when needed). `"reviewer": false` in `boardwright.json` turns it off except on hazardous or fast boards. New reviewer steps at stage 4 (schematic) and stage 7 (BOM: every flagged, unverified or failing line, and three at random).

**Diagnostics (optional, off by default)**
- `/boardwright:pcb-diagnostics on` (or `on without prompts`) starts a private record in `.boardwright/diagnostics/`: prompts, models, token use and cost (Claude Code's own figure, and an estimate from Anthropic's list prices read 2026-11-17), tool errors, refusals, API errors, failed checks and the stage reached, read from Claude Code's own session files by the end-of-turn and end-of-session hooks. Keys, tokens, e-mail addresses, the home folder and the user name are removed first.
- Only the user turns it on or off: a prompt hook records it from what they typed, and Claude's attempts to change the setting are refused.
- `report` (with a plain summary Claude writes from the numbers), `export` (a zip) and `delete`. Nothing is sent: the user sends the zip through the new GitHub issue form **Diagnostics report**, or by e-mail if an address is set in `plugin/scripts/diagnostics.json`. See `docs/PRIVACY.md`.
- Fixed on the way: a project's `scripts/` folder now gets every data file the scripts read (the factory profiles and prices were missing, so `fab_rules.py` failed inside a project).

**Other AI agents**
- New projects get an `AGENTS.md` (rules and how to resume) for Codex, OpenCode, Grok and others.
- `plugin/scripts/bw_mcp.py` is a small tool server (MCP) with read-only and checking tools only: `status`, `plan`, `run_gates`, `sch_check`, `history_list`, `fab_check`, `routing_plan_show` and `board_find`.
- Every stage can be resumed from the files (`status.py`, `plan.py`) by any session or agent.

**Tests**
- New: `plugin/tests/test_editing.py` (49 checks), `test_lifecycle.py` and `test_mcp.py`, all run by `python tools/check_all.py`.
- New benchmark harness `tools/bench/`: five editing jobs, two runs each, on Sonnet. Against 0.5.0, the ten runs cost 24% less ($2.88 against $3.77) and all passed (9 of 10 before); routing used about 60% fewer tokens. Details and limits: `docs/benchmark.md`.

## 0.5.0 (2026-11-16)
Phase 2 of the safety, EMC and high-speed plan, a reworked chat window, and commands that run end to end without permission prompts for read-only work.

**New checks**
- `emc_rules.py`: track over gaps in the adjacent ground pour, layer changes without a return via, cable ports with no filter or protection part, fast nets near the board edge, ground-pour coverage. Modelled on the published EMC rule lists of commercial checkers (no code taken from any tool). Nets on the hazardous side of a barrier are excluded.
- `impedance_check.py`: impedance estimate per net class from the stackup (Hammerstad-Jensen microstrip with thickness correction; IPC-2141A stripline and coupled pairs). Checked against textbook values (3.0 mm on 1.6 mm FR-4: 49.7 ohm) and the RP2350 guide's USB geometry (90.9 ohm).
- `pdn_check.py`: decoupling bank against each rail's target impedance (V x ripple / current step).
- `parts_register.py`: safety-critical parts with certificate, standard and rating; flags certificates held only under IEC 60950/60065.
- `precompliance_pack.py`: every report in one document for the responsible person and the test lab, with the tests only a lab can do.
- `sim_export.py`: IPC-2581, ODB++ and STEP for HyperLynx, CST or SIwave run by a person.

**Spacing tables**
- Each table records which independent sources agree, and `tools/mark_table_checked.py` records a check against the purchased standard (who, which edition and table, when). Statuses stay "secondary source" until then.

**Chat window**
- Header with the project name; labelled Mode and Model menus; "You" and "Claude" as headings; quieter tool lines; native status bar; Send as the default button; shorter labels.

**Commands**
- Every pipeline command pre-approves the read-only scripts, the read-only KiCad queries and writes inside `reports/`; anything that changes the design still asks. A live `/boardwright:pcb-review` of the example board now runs to the end and writes its report.

**Docs**
- README rewritten: what it checks, stages, platforms, install, use, limits.

## 0.4.1 (2026-11-16): bug fixes from a bug hunt
Every script was run on empty, brand-new, non-English-path and broken-config projects and on the AC-DC board.
- **mains_check.py passed silently at stage 4.** It found the mains nets through the board, which has no nets before layout, so the X-capacitor and discharge checks were skipped. It now matches net classes against the schematic's own nets.
- **The creepage gate could not pass for a new user.** Its cross-check needs `barrier_check.py`, which only read the older `barrier` section. `barrier_check.py` now derives the barrier from `safety.barriers` when there is no `barrier` section.
- **An empty or incomplete `safety` section passed** on a mains board; it now fails, and a mains domain or a mains-connected PROJECT.md without `safety.mains` stops mains_check.py.
- **The cross-check could skip a barrier** whose classes the barrier measurement did not cover; that now fails.
- **"X2 0.33uF" was read as 2 F** (the class tag before the value); the value parser now prefers a number with a multiplier or unit. Fuse ratings such as "T2A" still parse.
- `emc_harmonics.py` crashed on a non-numeric frequency; it now reports a setup problem. `spacing.py` gives a message instead of a traceback for inputs beyond its tables.
- New tests for each fix.

## 0.4.0 (2026-11-16): safety, EMC and high-speed checks (phase 1 of the research plan)
Built from the research in "Boardwright safety EMC high speed plan". Every limit names its source and status; tables not yet checked against the purchased standards say "secondary source" or "unverified".

- **Safety intake** (`safety_class.py`, `boardwright.json` "safety"): voltage domains, ES1/ES2/ES3 and PS1/PS2/PS3 per IEC 62368-1, `mains_referenced` domains counted as ES3, a barrier required for every domain above ES1, the standard and product class recorded as the user's decisions.
- **Creepage and clearance gate v2** (`creepage_rules.py`, `spacing.py`, `spacing_tables.json`): required distances per barrier by the IEC 60664-1 method (impulse voltage, transient and peak clearance, altitude, creepage by pollution degree and material group, reinforced rules, slot width). KiCad's calculator was studied, not copied; unlike it, creepage always takes the next table row up (KiCad interpolates above 160 V, which can under-state). `--write` puts the rules at the end of the `.kicad_dru`; the check fails on a missing or weak rule, KiCad older than 10.0.6, stale DRC results, a DRC violation, or when KiCad's DRC and `barrier_check.py` disagree.
- **Rule guard:** a net class now needs patterns that match nets on the board, not just patterns.
- **Mains topology** (`mains_check.py`): fuse first on the line input, X class across mains, Y class across barriers (Y1 for reinforced), varistor after the fuse, X-capacitor discharge time through the bleeder, touch-current estimate, earth on class I.
- **High-speed pairs** (`hs_rules.py`, "high_speed"): generated KiCad skew/length (and pair gap) rules, plus an independent measurement of length including via barrels, skew in mm and ps, via parity and return vias.
- **EMC harmonic plan** (`emc_harmonics.py`, "emc.clocks"): harmonics per FCC 15.109 / CISPR 32 band, conducted band, coincidences, cable ports to probe.
- Stage graph: new steps `spec.safety`, `sch.mains`, `layout.safety_class`, `layout.creepage`, `layout.hs`, `emc.harmonics`.
- Tests: `plugin/tests/test_safety.py` (32 checks with planted faults). Fault tests on the AC-DC board: secondary copper pushed inside the barrier (both checks fail), rules that match nothing (cross-check fails), a net class whose patterns match nothing (rule guard fails).
- README disclaimer rewritten to say what is checked and what is not.
- `/boardwright:pcb-gates` runs the board measurements before the creepage cross-check, and pre-approves the read-only KiCad-Python scripts by script name (the interpreter path differs per machine). Tested live through Claude on the AC-DC board: every check runs without a permission prompt and nothing is written.
- `emc_harmonics.py` prints a short summary (about 600 characters instead of 3,500); the full tables stay in `reports/emc-harmonics.md`.

## 0.3.1 (2026-11-16)
- KiCad add-on: its description in KiCad's Plugin and Content Manager now says it works on Windows and Linux (it said "Tested on Windows only").
- No other changes. Installing 0.3.1 over 0.3.0 is optional.

## 0.3.0 (2026-11-16): ready for testers on GitHub
- **Fixed: new projects had no stage graph.** `init_project.py` copied the scripts but not `pipeline.json`, so `plan.py` (and with it `/boardwright:pcb-auto`) failed in every new project. It no longer copies the plugin-only tools (`setup.py`, `session_start.py`, `selftest.py`) into projects.
- **Fixed: every new project was treated as hazardous.** The planner read the template's unanswered `Mains-connected: yes / no` as "yes" (and `hand / machine` as machine assembly), which would have added the high-voltage rules and an Opus review at every stage.
- **Fixed: crashes on non-English paths.** On Windows, scripts writing to a pipe used cp1252 and crashed on paths such as `OneDrive\文档`; the session-start hook went silent. All scripts now write UTF-8 and decode child output as UTF-8.
- Installers ask **one** question ("Set up everything? [Y/n]") instead of one per step.
- `examples/usb-sensor-test`: a complete board made with the pipeline (spec to fab files; datasheets not redistributed).
- `tools/check_all.py` runs every check; GitHub Actions run it on Windows and on Ubuntu with KiCad 10 (`checks.yml`), and a tag such as `v0.3.0` builds and publishes the KiCad add-on release (`release.yml`).
- Tidied the issues pyflakes found (unused imports and variables).

## 0.2.0 (2026-11-16): first version for testers
- New repository layout: Claude Code plugin, KiCad add-on and installers in one repo, installable from GitHub with `claude plugin marketplace add Pratham7767/Boardwright`.
- One-command installers for Windows (`install/install.ps1`) and macOS/Linux (`install/install.sh`, untested).
- `scripts/setup.py`: installs uv, kicad-buddy (pinned 0.1.0) and mcp-server-kicad (pinned 0.21.1), ticks KiCad's API server setting. Asks before each change; `--check` changes nothing.
- A session-start hook puts the project's status and plan into Claude's context, which saves two tool calls per session. It also warns when a project's scripts are older than the plugin's.
- Slash commands moved from the legacy `commands/` to skills, and are user-invoked only. The read-only `pcb-doctor` and `pcb-gates` scripts run without a permission prompt.
- Smaller always-on context: about 905 down to about 689 tokens per session (`claude plugin details`).
- Removed the unused `kicad-pcb` MCP server (board edits go through the live link; exports through `kicad-cli`).
- New `references/design-practice.md`: stackup, return paths, widths and spacing, crystals, USB protection, inrush, fiducials and the KiCad board setup. Drawn from Phil's Lab, Robert Feranec's workshop, Altium, ST AN2867, TI SLVAF82 and SLVA670, and the KiCad docs, and used at stages 4 and 5.
- `doctor.py` no longer warns about `KICAD_CLI` when kicad-cli is found.
- KiCad add-on 0.2.0: an **Install helpers** button in the Setup box, a model menu (your default, Opus, Sonnet, Haiku), and a hint after a usage-limit reply.

### Linux support (0.2.0)
- KiCad add-on declared for Windows and Linux. On Linux it uses the system Python's wxPython. It finds the board from window titles (X11 with wmctrl or xdotool) or else from KiCad's most recent board. Sign-in and Install helpers open in the first terminal emulator found. Stop kills Claude Code's whole process group.
- `install.sh` is now the Linux installer: the official KiCad 10 PPA on Ubuntu 22.04+, Git through apt, the add-on step, and `--check`, `--no-signin`, `--no-open`.
- `setup.py` names the right KiCad install for each platform and explains why the Flatpak KiCad can't be used.
- Tested in WSL Ubuntu 20.04 (no KiCad): the add-on's chat tests, project detection, the fallback messages, and `install.sh --check`.
- Tested in a clean Ubuntu 24.04 container: `install.sh --yes` installed KiCad 10.0.8 from the PPA, Claude Code, the plugin and the helpers. On a real board, 8 of 8 gate scripts pass with Linux kicad-cli. Also tested: the session-start hook, doctor, the add-on tests, the chat window under a virtual display with the system wxPython, and the bundled plugin's validation.
- The installer leaves out the 280 MB 3D-model package (`kicad-packages3d`) and installs KiCad with only its symbol, footprint and template libraries.
- Fixed: the installer wrongly reported open helper items when no terminal could be opened.

## 0.1.x
- First board runs (mains flyback supply, USB sensor board) on Windows 11 and KiCad 10.0.8, and the first KiCad add-on builds.
