# Projects Boardwright builds on

Boardwright's own code is MIT-licensed (see `LICENSE`). It does **not** include copies of the projects below. They are installed or started on your computer, from their official sources, when you run the installer or use the plugin.

| Project | Used for | Licence | Source |
|---|---|---|---|
| KiCad | the design tool; `kicad-cli` for checks and exports; the IPC API for live edits | GPL-3.0-or-later | https://www.kicad.org |
| KiCAD-Buddy 0.1.0 (Michael Burger) | MCP server for the live link to the open KiCad window | MIT | https://github.com/mburger89/KiCAD-Buddy |
| mcp-server-kicad 0.21.1 | MCP server for schematic editing | GPL-3.0-or-later | https://github.com/ProductOfAmerica/mcp-server-kicad |
| uv (Astral) | installs and runs the two MCP servers | MIT or Apache-2.0 | https://github.com/astral-sh/uv |
| Claude Code (Anthropic) | runs the pipeline; each user brings their own account | Anthropic's terms | https://code.claude.com |
| KiCadRoutingTools 0.24.1 | the routing engine's first router, run in its strict mode (optional; installed by `setup_engine`) | MIT | https://github.com/drandyhaas/KiCadRoutingTools |
| Freerouting 2.5.0 | the routing engine's second router, run as a separate program through Specctra DSN/SES files (optional; installed by `setup_engine`) | GPL-3.0 | https://github.com/freerouting/freerouting |
| Eclipse Temurin 25 (Adoptium) | the Java runtime Freerouting needs (optional; installed by `setup_engine`) | GPL-2.0 with the Classpath Exception | https://adoptium.net |

The routing engine's downloads are pinned to exact versions and checked against fixed SHA-256 checksums before use (`plugin/scripts/setup_engine.ps1` and `setup_engine.sh`). Nothing from them is copied into this repository.

The design rules in `plugin/skills/boardwright/references/` are short paraphrases with citations of public application notes and articles (TI, ST, Raspberry Pi, Espressif, Nordic, ROHM, Vishay, Phil's Lab, Altium, KiCad docs). Each file lists its sources. Read the originals for the full text.

## Ideas, not code

Version 0.6 borrows several ideas from [Backplane](https://github.com/BackplaneWorks/Backplane) (MIT licence): the one-call edit tool that answers with the DRC difference, the router, placing a part next to a pin, snapshots after every edit, one editor at a time, the routing plan the designer approves, factory profiles with the page and date, and flagging out-of-date factory files. No Backplane code was copied.

## Data read at run time

The part lifecycle check (`lifecycle_check.py`) reads LCSC's public product data when you run it. Nothing from LCSC is copied into this repository.
