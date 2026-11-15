# Changelog

## 0.2.0 (2026-11-16): first version for testers
- New repository layout: Claude Code plugin, KiCad add-on and installers in one repo, installable from GitHub with `claude plugin marketplace add prathware/boardwright`.
- One-command installers for Windows (`install/install.ps1`) and macOS/Linux (`install/install.sh`, untested).
- `scripts/setup.py`: installs uv, kicad-buddy (pinned 0.1.0) and mcp-server-kicad (pinned 0.21.1), ticks KiCad's API server setting. Asks before each change; `--check` changes nothing.
- A session-start hook puts the project's status and plan into Claude's context, which saves two tool calls per session. It also warns when a project's scripts are older than the plugin's.
- Slash commands moved from the legacy `commands/` to skills, and are user-invoked only. The read-only `pcb-doctor` and `pcb-gates` scripts run without a permission prompt.
- Smaller always-on context: about 905 down to about 689 tokens per session (`claude plugin details`).
- Removed the unused `kicad-pcb` MCP server (board edits go through the live link; exports through `kicad-cli`).
- New `references/design-practice.md`: stackup, return paths, widths and spacing, crystals, USB protection, inrush, fiducials and the KiCad board setup. Drawn from Phil's Lab, Robert Feranec's workshop, Altium, ST AN2867, TI SLVAF82 and SLVA670, and the KiCad docs, and used at stages 4 and 5.
- `doctor.py` no longer warns about `KICAD_CLI` when kicad-cli is found.
- KiCad add-on 0.2.0: an **Install helpers** button in the Setup box, a model menu (your default, Opus, Sonnet, Haiku), and a hint after a usage-limit reply.

## 0.1.x
- First board runs (mains flyback supply, USB sensor board) on Windows 11 and KiCad 10.0.8, and the first KiCad add-on builds.
