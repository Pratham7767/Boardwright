# Boardwright

[![checks](https://github.com/prathware/boardwright/actions/workflows/checks.yml/badge.svg)](https://github.com/prathware/boardwright/actions/workflows/checks.yml)

**Design a printed circuit board in KiCad by talking to Claude.** You describe the board; Claude Code takes it from idea to fab files in eight gated stages, and you watch every change happen in the open KiCad window. It never orders, uploads or publishes anything.

Free and open source (MIT). A community project, not affiliated with the KiCad project or Anthropic.

> **Status: 0.3.0, early testing.** Windows 11 with KiCad 10.0.8 is tested end to end on two real boards (a mains flyback supply and a USB sensor board). **Linux** is supported and tested on Ubuntu 24.04 with KiCad 10.0.8 (installer, gate scripts on a real board, the KiCad button's window); a full board design run on Linux is still to be done. macOS is untested. Expect rough edges, and please report them: see [docs/TESTING.md](docs/TESTING.md).

## What you get

| Part | What it is |
|---|---|
| **Claude Code plugin** (`plugin/`) | The pipeline: a skill with eight stages and their gates, 13 check and export scripts, 4 helper agents on cheaper models, design rules from manufacturer application notes, and slash commands such as `/boardwright:pcb-new`. Works in the Claude Code terminal, VS Code, JetBrains and the desktop app. |
| **KiCad add-on** (`kicad-addon/`, Windows and Linux) | A speech-bubble button in KiCad's PCB Editor that opens a chat window next to KiCad, talking to *your own* Claude Code in the open board's folder: streamed replies, Allow/Deny for every change, model and mode menus, and a first-run check that walks you through install and sign-in. |
| **Installers** (`install/`) | One command that checks and sets up everything, asking before each change. |

## The eight stages

| Stage | Gate (the work stops if it fails) |
|---|---|
| 1 Spec | every requirement has a value and a source |
| 2 Parts | every part has a datasheet and a pin table with page numbers |
| 3 Power budget | at least 20% headroom on every rail |
| 4 Schematic | ERC 0 errors, schematic check 0 errors |
| 5 Layout | rule guard passes; DRC with schematic parity 0 errors; nothing unconnected |
| 6 EMC | no CRITICAL finding; isolation barrier check if the board has one |
| 7 BOM | no end-of-life or out-of-stock part |
| 8 Release | Gerbers, drill, placement, BOM and schematic PDF from a freshly refilled copy, plus a checklist of everything you must verify yourself |

**Guided** mode interviews you in plain language and explains its choices. **Express** mode reads your spec and stops only when a gate fails or a decision is yours. Both run the same gates.

## Install

You need a Claude plan that includes Claude Code (Pro, Max, Team or Enterprise) or an Anthropic API account. Every message uses your own plan or credit, and a whole board takes many messages.

**Windows**, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/prathware/boardwright/main/install/install.ps1 | iex
```

**Linux** (and macOS, untested), in a terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/prathware/boardwright/main/install/install.sh | bash
```

It asks one question (**Set up everything? [Y/n]**), then installs whatever is missing from official sources: KiCad, Python, Git, Claude Code, the plugin and its helper tools. It also prepares the KiCad add-on and starts Claude Code's own sign-in. The one manual step left is in KiCad: **Plugin and Content Manager → Install from File...** for the add-on. **Step-by-step and manual instructions: [docs/INSTALL.md](docs/INSTALL.md).**

## Use

1. Make an empty folder for your board and open it in Claude Code (or open the board in KiCad and click the Boardwright button).
2. `/boardwright:pcb-doctor`: checks your setup.
3. `/boardwright:pcb-new guided`, then describe your board. For the fewest stops: `/boardwright:pcb-auto <what the board should do>`.
4. Later: `/boardwright:pcb-run` continues where you left off. `/boardwright:pcb-gates` runs the checks and changes nothing. `/boardwright:pcb-review` reviews an existing board.

## What it will not do

- **It does not make a board safe.** A clean check only proves the board obeys the rules that were set. A board with mains or other hazardous voltage must be reviewed by a qualified person before it is powered.
- It does not prove EMC compliance; stage 6 is a geometry-based risk estimate.
- It does not order, upload or publish anything, and it never waives a failed check: it lists proposed waivers and waits for you.
- It never asks for, reads or stores your passwords, API keys or tokens. Sign-in is always Claude Code's own.

## See a finished example

[examples/usb-sensor-test](examples/usb-sensor-test) is a real board taken from idea to fab files with Boardwright: the spec, stage reports, gate results and release files.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md): installation in detail, updating, uninstalling, troubleshooting
- [docs/TESTING.md](docs/TESTING.md): for testers, covering what to try and how to report
- [docs/ROADMAP.md](docs/ROADMAP.md): known gaps
- [docs/RELEASING.md](docs/RELEASING.md): for the maintainer, covering pushing, releases and checks (`python tools/check_all.py`)
- [plugin/README.md](plugin/README.md): the pipeline in detail (scripts, helpers, models)
- [kicad-addon/README.md](kicad-addon/README.md): the KiCad add-on in detail (build, how it works, KiCad quirks)
- [THIRD_PARTY.md](THIRD_PARTY.md): the projects Boardwright builds on

## Licence

MIT, see [LICENSE](LICENSE), including the note on hazardous designs.
