# Boardwright

[![checks](https://github.com/Pratham7767/Boardwright/actions/workflows/checks.yml/badge.svg)](https://github.com/Pratham7767/Boardwright/actions/workflows/checks.yml)

**Boardwright helps you design a circuit board in KiCad by chatting with Claude.**

You describe the board you want. Claude chooses the parts, draws the circuit, lays out the board and makes the files a factory needs to build it. At each step, Boardwright checks the work. If a check fails, the work stops until the problem is fixed.

It is free and open source. It never orders, uploads or publishes anything for you.

## What you need

- **KiCad 9 or 10**, the free circuit-board design program.
- **Claude Code** with a paid Claude plan, or an Anthropic API account. Every message uses your own plan.
- **Windows 11 or Linux.** Mac is not tested yet.

## Install

On **Windows**, open PowerShell and paste:

```powershell
irm https://raw.githubusercontent.com/Pratham7767/Boardwright/main/install/install.ps1 | iex
```

On **Linux**, open a terminal and paste:

```bash
curl -fsSL https://raw.githubusercontent.com/Pratham7767/Boardwright/main/install/install.sh | bash
```

The installer asks one question, then installs whatever is missing and asks you to sign in to Claude. Last step, in KiCad: **Plugin and Content Manager → Install from File...**, then pick the file the installer shows you.

More detail: [docs/INSTALL.md](docs/INSTALL.md).

## How to use it

1. Make an empty folder for your board and open it in Claude Code.
2. Type `/boardwright:pcb-doctor` to check that everything is set up.
3. Type `/boardwright:pcb-new guided` and describe your board in a sentence or two.
4. Answer Claude's questions. It works through eight stages and stops after each one to show you what it did.

You can also open a board in KiCad and click the **Boardwright** chat button on the toolbar.

Other commands:

| Command | What it does |
|---|---|
| `/boardwright:pcb-run` | Continues where you left off |
| `/boardwright:pcb-gates` | Runs every check and changes nothing |
| `/boardwright:pcb-review` | Reviews a board you already have and writes a report |
| `/boardwright:pcb-auto <idea>` | Designs a whole board with as few stops as possible |
| `/boardwright:pcb-undo` | Lists the saved steps and goes back to an earlier one |
| `/boardwright:pcb-plan on` | Optional, for bigger boards: Claude proposes where tracks may run, and only you approve |

## The eight stages

| Stage | What happens | The check that must pass |
|---|---|---|
| 1. Spec | Write down what the board must do | Every requirement has a value |
| 2. Parts | Choose the parts and save their datasheets | Every part has a datasheet and a checked pin list |
| 3. Power | Work out the current each part needs | Every power supply has spare capacity |
| 4. Schematic | Draw the circuit | No wiring errors |
| 5. Layout | Place the parts and draw the copper tracks | No spacing or connection errors |
| 6. Interference | Look for things that could cause radio interference | No serious problem found |
| 7. Parts list | Check that the parts can be bought | No part is out of stock or discontinued |
| 8. Release | Make the factory files | Files made, plus a list of things you must check yourself |

## What it checks

- **Wiring and spacing.** KiCad's own checks, run at every stage.
- **Safety on mains boards.** Boards that plug into the wall need enough distance between the dangerous side and the safe side. Boardwright works out the distance the safety standard asks for, makes KiCad enforce it, and measures it a second way to be sure. It also checks the fuse, the safety capacitors and how fast the board discharges after you unplug it.
- **Radio interference (EMC).** It looks for common layout mistakes that make a board noisy, and lists the frequencies to test first.
- **Fast signals.** For USB and other fast connections, it checks track lengths, the layer changes and the estimated impedance.
- **Power.** It estimates whether each power supply has enough small capacitors near the chips.
- **Factory limits.** Profiles for JLCPCB, PCBWay, OSH Park and Eurocircuits. Each value comes from the factory's own page, with the page and date. A value the factory does not publish is marked "unverified".
- **Out-of-date factory files.** The release check fails if any file in `fab/` is older than the board or circuit drawing.
- **Part lifecycle.** For parts with an LCSC number, it reads LCSC's public product data and fails on a discontinued part. This is the seller's status, not the maker's.

## Undo

After every edit, Boardwright saves a snapshot of your design files. It is kept out of your way, in a hidden place inside git (or in a hidden folder if your board is not in a git repository). Type `/boardwright:pcb-undo` to see the steps and go back to one. Before it goes back, it saves the current state, so you can undo the undo. Only one Claude session can edit a board at a time, so two windows cannot overwrite each other.

## Cheap models do the work, the strongest one checks it

Most commands run on the cheaper Sonnet or Haiku models. At the end of most stages a helper on the strongest model, Opus, checks the work before the stage counts. Details: [plugin/README.md](plugin/README.md).

New to these words? See the [glossary](docs/GLOSSARY.md).

## Important limits

- **Boardwright does not make a board safe or certified.** Its reports help a qualified person check the design. They are not a safety certificate or a lab test.
- **Mains boards can kill.** A qualified person must check them before they are switched on.
- Some numbers, such as the safety distances, come from published summaries of the standards, not from the standards themselves. The reports say so.
- Interference and many safety properties can only be measured on a real, built board.
- To sell a product, you need lab tests and your own declaration. In India that can mean BIS registration; in the US, FCC rules; in Europe, the CE rules.
- Boardwright never sees your passwords or keys. Signing in is done by Claude Code itself.

## Example

[examples/usb-sensor-test](examples/usb-sensor-test) is a small USB temperature and humidity sensor board made with Boardwright, with the report from every stage.

## More documents

- [Install guide](docs/INSTALL.md): installing, updating, removing, fixing problems
- [Glossary](docs/GLOSSARY.md): the circuit-board words used here, explained simply
- [Test guide](docs/TESTING.md): what to try if you are helping test Boardwright
- [How the pipeline works](plugin/README.md): the commands, checks and helpers
- [The KiCad chat button](kicad-addon/README.md)
- [What is planned next](docs/ROADMAP.md)
- [For maintainers](docs/RELEASING.md)
- [Other projects used](THIRD_PARTY.md)

## Licence

MIT, free to use and change. See [LICENSE](LICENSE).
