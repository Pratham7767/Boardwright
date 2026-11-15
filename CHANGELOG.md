# Changelog

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
