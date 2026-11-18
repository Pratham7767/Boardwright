# Plan for 0.7: an MCP server, and a deterministic engine that routes first

Research behind this plan, with sources: [routers](research/routers.md), [placement](research/placement.md), [routing and EMC rules](research/routing-rules.md), [KiCad and MCP](research/kicad-and-mcp.md).

## The idea

Today Claude does most layout work by itself, one tool call at a time. That costs tokens and time, and the result depends on the model. In 0.7 a **deterministic engine** does the work first, following written rules. Claude only handles what the engine could not finish, and the designer only decides what is theirs to decide.

```
netlist + rules -> classify nets -> propose placement -> designer approves (buttons)
  -> critical nets (fast pairs, mains) by our constrained router or by hand
  -> everything else by Freerouting -> our checks
  -> leftovers list -> Claude fixes those -> checks again -> gate
```

Every step is measured on a set of test boards, so we can see the engine get better.

## Part A: Boardwright as an MCP server (keeps the plugin)

- One server, `boardwright`, standard library only, shipped inside the plugin (`.mcp.json`) and usable from any MCP client (Claude Desktop, Codex, Cursor).
- About 13 tools with short descriptions and compact answers: `status`, `check`, `find`, `edit`, `place`, `route`, `engine`, `plan`, `history`, `fab`, `lifecycle`, `diagnostics`, `parts`.
- The same guards as today, built into the server so they also work in clients without hooks: the one-editor lock and a history step for every edit; mains, hazardous and fast nets never auto-routed; routing plans and diagnostics only by the user's own answer (no approve or consent tool exists).
- The plugin's commands and skills call these tools instead of long shell commands. The scripts stay usable from a terminal.
- Measured: the same benchmark jobs before and after, in tokens.

## Part B: the deterministic engine

1. **Classify** every net: ground, power, hazardous (from the safety domains), fast pairs and clocks (from net classes, names and `boardwright.json`), ordinary.
2. **Rules** from the rule catalogue: widths, clearances and spacing by net class and stackup, written as a marked section of the KiCad rules file (the same way as the factory profiles) and into the router's input. Rules geometry cannot decide stay checks or questions for the designer.
3. **Placement proposal** (the method in the placement research): groups by schematic sheet and connectivity, anchors (connectors on edges, mounting holes, mains entry), block leaders, satellites by rule (decoupling next to its pin, crystal next to the chip, protection at the connector), legalized, scored for routability, improved by annealing. The designer approves it with a button before anything is routed.
4. **Critical nets first**: fast pairs and clocks by a constrained router (pairs together, length matched), mains and switch nodes left to a person unless the designer says otherwise.
5. **Freerouting** for the rest: export the board (KiCad's own Specctra export, tested here), run Freerouting headless with only the allowed net classes, read its result with our own importer (KiCad's importer needs its window), lock the critical nets so it cannot move them.
6. **After**: stitching vias, zone refill, length tuning, then every Boardwright check and KiCad's DRC.
7. **Leftovers**: a short list of unrouted connections and rule breaks, handed to Claude (`bw_edit` and its router), then checked again.

Reuse: Freerouting (GPL-3) is downloaded on the user's computer and run as a separate program, never bundled. KiCadRoutingTools (MIT) is the candidate for fan-out, differential pairs and length tuning; its code is credited if used. GPL code (kbplacer, ReplicateLayout) is read for ideas only.

## Honest limits

No autorouter, open source or commercial, finishes a motherboard-class board by itself; DDR, dense BGAs and RF stay under a person's control. Some interface numbers (PCIe, HDMI, MIPI, DDR5) are behind paywalls or NDAs and stay "unverified" until checked. The engine's results always go through the same checks and the strong-model review.

## Phases

1. **A**: the MCP server, skills moved onto it, token benchmark.
2. **B1**: classify, rules, Freerouting integration with our importer, checks and leftovers, and a benchmark on KiCad's own demo boards (2 to 6+ layers).
3. **B2**: the placement proposal with approval.
4. **B3**: critical nets: differential pairs, length tuning, fan-out, stitching vias.
5. **B4**: interface templates (USB, Ethernet, PCIe, DDR) from the rule catalogue.
6. Reverify everything (an independent strong-model review), fix, document, release.
