# Projects Boardwright builds on

Boardwright's own code is MIT-licensed (see `LICENSE`). It does **not** include copies of the projects below. They are installed or started on your computer, from their official sources, when you run the installer or use the plugin.

| Project | Used for | Licence | Source |
|---|---|---|---|
| KiCad | the design tool; `kicad-cli` for checks and exports; the IPC API for live edits | GPL-3.0-or-later | https://www.kicad.org |
| KiCAD-Buddy 0.1.0 (Michael Burger) | MCP server for the live link to the open KiCad window | MIT | https://github.com/mburger89/KiCAD-Buddy |
| mcp-server-kicad 0.21.1 | MCP server for schematic editing | GPL-3.0-or-later | https://github.com/ProductOfAmerica/mcp-server-kicad |
| uv (Astral) | installs and runs the two MCP servers | MIT or Apache-2.0 | https://github.com/astral-sh/uv |
| Claude Code (Anthropic) | runs the pipeline; each user brings their own account | Anthropic's terms | https://code.claude.com |

The design rules in `plugin/skills/boardwright/references/` are short paraphrases with citations of public application notes and articles (TI, ST, Raspberry Pi, Espressif, Nordic, ROHM, Vishay, Phil's Lab, Altium, KiCad docs). Each file lists its sources. Read the originals for the full text.
