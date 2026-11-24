# Hand-over

Where Boardwright stands and how to continue, for any Claude (or person) picking it up. Update it at the end of each working session.

**State (2026-11-24): version 0.7.0, on `main`.** Pushed up to `0e38465`; local commit `290a03c` (Freerouting rounds on big boards) and the files from this hand-over are not pushed yet.

## What exists
- **Claude Code plugin** (`plugin/`): skills `pcb-*`, hooks (`plugin/scripts/edit_hooks.py`: edit lock, history, guards), gate scripts, the MCP server `plugin/scripts/bw_mcp.py` (15 tools).
- **Routing engine** (`plugin/scripts/engine.py`, `engine_kicad.py`): KiCadRoutingTools 0.24.1 (strict) and Freerouting 2.5.1 nightly 12f085e (pinned by checksum), installed by `plugin/scripts/setup_engine.ps1` / `.sh`. Three variants run side by side and the best DRC-clean result is kept. Results and what was tried: `docs/benchmark-engine.md`; congestion-aware routing notes: `docs/research/pathfinder-plan.md`; research report: `reports/Routing engine improvement plan.md` in the example project folder.
- **KiCad add-on** (`kicad-addon/`): the chat window (`bw_chat.py`, `bw_core.py`, `bw_theme.py`, `bw_dock.py`), built into `kicad-addon/dist/boardwright-kicad.zip` by `build.py`.
- **User guide**: `docs/Boardwright-User-Guide.pdf` (source `docs/guide/user-guide.html`; screenshots by `tools/guide/capture_window.py`).

## Open items
1. **Routing on very big boards.** jetson (10 layers, 2946 connections) stays at about 44 %: Freerouting completes few nets there in 15 minutes and KiCadRoutingTools' setup is too slow on it. video (4 layers) reaches 79 % with Freerouting rounds but depends on free memory. Next ideas in `docs/research/pathfinder-plan.md`.
2. **OmniRoute for development** (owner's wish, 2026-11-24): `tools/dev/ensure-omniroute.ps1` / `.sh` install a private Node 24 and OmniRoute (pinned) and start it, so Claude Code can keep working through other AI providers when the Claude plan's limit is reached. Not run yet: an automatic safety check in Claude Code refused to let Claude run it; the owner runs it once by hand (`powershell -ExecutionPolicy Bypass -File tools\dev\ensure-omniroute.ps1`). Keys are created in OmniRoute's own dashboard and never go into this repo.
3. **Release tag.** No `v0.7.0` tag yet; tagging publishes a GitHub release, so it waits for the owner.
4. **Freerouting**: switch from the nightly to the first proper 2.5.1 release when it appears.

## Resume
1. Clone `https://github.com/Pratham7767/Boardwright` (or copy this folder) and open it in Claude Code. `CLAUDE.md` holds the working rules.
2. For routing work on a new computer: run `plugin/scripts/setup_engine.ps1` (or `.sh`) once.
3. Before pushing: `python tools/check_all.py --quick`.
