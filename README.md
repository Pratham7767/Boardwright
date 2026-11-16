# Boardwright

[![checks](https://github.com/Pratham7767/Boardwright/actions/workflows/checks.yml/badge.svg)](https://github.com/Pratham7767/Boardwright/actions/workflows/checks.yml)

Boardwright takes a printed circuit board from an idea to fab files in KiCad, with Claude Code doing the design work and a gate at every stage. You see each change in the open KiCad window. Nothing is ordered, uploaded or published.

Free and open source (MIT). Not affiliated with the KiCad project or Anthropic.

## What it checks

| Area | Checks |
|---|---|
| Electrical | ERC, DRC with schematic parity, net-class rule guard, schematic verification, block rules (decoupling, protection, crystal, I2C, track width) |
| Safety (mains and hazardous voltage) | Voltage domains and energy classes (IEC 62368-1); creepage and clearance per barrier by the IEC 60664-1 method, enforced in KiCad DRC and cross-checked by an independent measurement; mains topology (fuse first, X/Y classes, varistor placement, X-capacitor discharge, touch current, earth); safety-critical parts register |
| EMC | Layout rules (track over pour gaps, layer changes without return vias, unfiltered cable ports, edge proximity, ground coverage); switching-loop areas and distances; harmonic plan against FCC 15.109 and CISPR 32 bands; export to IPC-2581, ODB++ and STEP for HyperLynx, CST or SIwave |
| High speed and power | Pair length, skew, via parity and return vias; impedance estimate from the stackup; decoupling bank against each rail's target impedance |
| Release | Gerbers, drill, placement, BOM, schematic PDF and JLCPCB assembly files from a refilled copy; a pre-compliance pack for the responsible person and the test lab |

Every limit names its source and status. Values not yet checked against a purchased standard say so in the report.

## Stages

| | Stage | Gate |
|---|---|---|
| 1 | Spec | every requirement has a value and a source |
| 2 | Parts | every part has a datasheet and a pin table with page numbers |
| 3 | Power budget | at least 20% headroom on every rail |
| 4 | Schematic | ERC and schematic check clean; mains topology on mains boards |
| 5 | Layout | DRC clean with schematic parity; spacing gate on mains boards; pair and impedance checks on fast boards |
| 6 | EMC | no CRITICAL finding |
| 7 | BOM | no end-of-life or out-of-stock part |
| 8 | Release | release files from a refilled copy; checklist of everything a person must verify |

Guided mode interviews you and explains its choices. Express mode stops only when a gate fails or a decision is yours. Both run the same gates.

## Platforms

| | Windows 11 | Linux (Ubuntu 22.04/24.04) | macOS |
|---|---|---|---|
| Claude Code plugin and checks | tested | tested | untested |
| KiCad chat window | tested | tested | not available |
| KiCad | 9 or 10 (tested on 10.0.8) | 9 or 10 (tested on 10.0.8) | 9 or 10 |

## Install

You need a Claude plan that includes Claude Code, or an Anthropic API account. Every message uses your plan or credit.

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Pratham7767/Boardwright/main/install/install.ps1 | iex
```

Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Pratham7767/Boardwright/main/install/install.sh | bash
```

The installer asks once, then installs what is missing from official sources: KiCad, Python, Git, Claude Code, the plugin and its helper tools. It prepares the KiCad add-on and starts Claude Code's own sign-in. Finish in KiCad with **Plugin and Content Manager → Install from File...**. Details and manual steps: [docs/INSTALL.md](docs/INSTALL.md).

## Use

1. Open an empty folder in Claude Code, or open a board in KiCad and click the Boardwright button.
2. `/boardwright:pcb-doctor` checks the setup.
3. `/boardwright:pcb-new guided` starts a board. `/boardwright:pcb-auto <idea>` runs with the fewest stops.
4. `/boardwright:pcb-run` continues. `/boardwright:pcb-gates` runs every check and changes nothing. `/boardwright:pcb-review` reviews an existing board.

## Limits

Boardwright's reports are pre-compliance evidence for a responsible person. They are not a safety certificate, a test report or a prediction of an EMC lab result.

- Impedance, PDN and skew-in-picoseconds figures are calculated estimates.
- Electric strength, touch current, fault behaviour, temperature, emissions, immunity and signal integrity are known only from tests on built hardware.
- Selling a product needs the manufacturer's declaration and, where the law requires it (BIS CRS in India, FCC in the US, the EU EMC and Low Voltage directives), testing by a recognised lab.
- **Mains and hazardous-voltage boards can kill.** A qualified person reviews them before they are powered.
- Failed checks are never waived automatically; proposed waivers wait for you.
- Boardwright never asks for, reads or stores passwords, API keys or tokens. Sign-in is Claude Code's own.

## Example

[examples/usb-sensor-test](examples/usb-sensor-test): a USB sensor board taken from idea to fab files, with every stage report.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md) installing, updating, uninstalling, troubleshooting
- [docs/TESTING.md](docs/TESTING.md) a test plan for early users
- [plugin/README.md](plugin/README.md) the pipeline, scripts and helper agents
- [kicad-addon/README.md](kicad-addon/README.md) the KiCad add-on
- [docs/ROADMAP.md](docs/ROADMAP.md) known gaps and next work
- [docs/RELEASING.md](docs/RELEASING.md) for maintainers
- [THIRD_PARTY.md](THIRD_PARTY.md) projects Boardwright builds on

## Licence

MIT. See [LICENSE](LICENSE), including the note on hazardous designs.
