# KiCad engine and MCP server: research notes

Date: 2026-11-17. Machine: Windows 11, KiCad 10.0.8 at `E:\KiCad` (Python 3.11.5), Java 1.8 (old).
Everything marked "tested" was run here on a copy of `examples/usb-sensor-test` (2 copper layers, 33 footprints, 149 tracks, 29 vias). Anything not run is marked "unverified".

## Short answer

1. KiCad 10's Python can export a Specctra DSN and import a Specctra SES headless, in about 10 ms for this board. Tested. `kicad-cli` can do neither. The old SWIG `pcbnew` module is deprecated but still works in 10.0.8.
2. Freerouting can be driven headless from a command line. The DSN KiCad writes carries widths, clearances, via types, keepouts and planes per net class, but not differential pairs, length rules or the `.kicad_dru` custom rules. This machine's Java (1.8) is too old for the jar (section 2).
3. The IPC API (`kipy`) is the future for live editing, but its documented board API has no router, push-and-shove, differential pair or length tuning. For the engine, keep `pcbnew` (headless, file based) and use IPC only to show results in an open editor.
4. An MCP server saves tokens mainly by staying small and by returning compact rows. Boardwright already ships a read-only one (`plugin/scripts/bw_mcp.py`: 8 tools, 2,754 characters of tool list). Section 4 grows it to 13 tools and keeps the plugin's hooks and guards working.

---

## 1. KiCad 10 Python, `kicad-cli` and the IPC API

### 1.1 DSN export and SES import (tested)

```python
# Run with E:\KiCad\bin\python.exe -I script.py
import pcbnew
b = pcbnew.LoadBoard("board.kicad_pcb")
ok = pcbnew.ExportSpecctraDSN(b, "board.dsn")      # True
# ... router writes board.ses ...
b2 = pcbnew.LoadBoard("board.kicad_pcb")
ok = pcbnew.ImportSpecctraSES(b2, "board.ses")     # True, tracks and vias added
pcbnew.SaveBoard("routed.kicad_pcb", b2)
```

What happened:

- `ExportSpecctraDSN` returned `True` in 0.01 s and wrote a 53 KB file. No GUI or display needed. Both functions exist in `pcbnew` 10.0.8.
- Output noise: many harmless `Adding duplicate image handler for ...` lines on stderr. Wrappers should drop them.
- `ImportSpecctraSES`: no Freerouting jar was downloaded, so there is no real router result. Instead I removed all tracks, exported a DSN, and wrote a SES by hand from the `(wiring)` section of the DSN KiCad had exported from the routed board. Import returned `True` and added 178 items (149 tracks, 29 vias), the same counts as the original. That proves the import path and the SES shape; it does not prove how a real Freerouting result imports. Connectivity after that import: unverified (my one reading, 100 unconnected, was taken before connectivity was rebuilt; call `board.BuildConnectivity()` first).
- `kicad-cli` 10.0.8 `pcb export` formats: 3dpdf, brep, drill, dxf, gencad, gerbers, glb, hpgl (removed), ipc2581, ipcd356, odb, pdf, ply, pos, ps, stats, step, stl, stpz, svg, u3d, vrml, xao. Other `pcb` subcommands: `drc`, `import`, `render`, `upgrade`. There is no DSN export and no SES import, so that step must run in KiCad's Python.

What the DSN KiCad wrote contains (read from the file):

| Item | In the DSN? |
|---|---|
| Board outline, layers | Yes (`boundary`, `layer F.Cu`, `B.Cu`) |
| Footprint positions, pad shapes | Yes (`placement`, `library`) |
| Net class width, clearance, via choice | Yes: `class` blocks (`kicad_default`, `Power` width 400, `USB` width 250, clearance 200, in µm) |
| Default rule and `smd_smd` clearance | Yes (`rule` in `structure`) |
| Keepouts (rule areas) | Yes, as `keepout` polygons (4 here) |
| Copper pours | Only as a `plane` on the net's layer, not the filled shape |
| Existing tracks and vias | Yes, as `(wiring)` (so the router can keep or rip them) |
| Differential pairs, length rules | No (no `diffpair`, `pair` or `length` text), although the project's net classes carry diff pair gap and width |
| `.kicad_dru` custom rules (hole clearance, per-class minimum width) | No |
| Stackup, impedance | No (layer names and type only) |

So anything beyond width, clearance, vias and keepouts is checked after the import by KiCad's own DRC (`kicad-cli pcb drc --format json`, 2.8 s here, 17 violations on the example). Boardwright already runs DRC after every edit.

### 1.2 Reading and editing the board from Python (tested unless noted)

```python
import pcbnew
from pcbnew import FromMM, ToMM
b = pcbnew.LoadBoard(path)
b.BuildConnectivity()
b.GetConnectivity().GetUnconnectedCount(True)        # ratsnest: 0 on the routed example
ds = b.GetDesignSettings()
for name, nc in ds.m_NetSettings.GetNetclasses().items():
    nc.GetTrackWidth(), nc.GetClearance(), nc.GetViaDiameter(), nc.GetDiffPairGap(), nc.GetDiffPairWidth()
b.GetNetInfo().NetsByName()["/USB_DP"].GetNetClassName()     # "USB"
ds.m_MinClearance, ds.m_TrackMinWidth, ds.m_ViasMinSize, ds.m_MinThroughDrill
fp = b.FindFootprintByReference("U1")
cy = fp.GetCourtyard(pcbnew.F_CrtYd)                 # SHAPE_POLY_SET; cy.BBox() = 10.45 x 10.45 mm
fp.SetPosition(pcbnew.VECTOR2I(fp.GetX() + FromMM(1), fp.GetY()))
fp.SetOrientationDegrees(fp.GetOrientationDegrees() + 90)
fp.Flip(fp.GetPosition(), True)                      # moved C1 from F.Cu to B.Cu
pcbnew.ZONE_FILLER(b).Fill(b.Zones())                # True, 0.16 s
pcbnew.SaveBoard(out, b)
```

Findings and traps:

- Ratsnest: `BuildConnectivity()` then `GetConnectivity().GetUnconnectedCount(True)` works.
- Net classes, per-net class name, minimum track/via/hole sizes: work as above. Net classes hold diff pair gap and width, but there is no "this net is half of a pair" flag; pairs are found by name (`_P/_N`, `DP/DM`, `+/-`), so pair detection stays Boardwright code.
- Stackup: `ds.GetStackupDescriptor()` returns a bare `SwigPyObject` with no usable methods in 10.0.8, so layer thicknesses cannot be read from Python. This example stores no stackup (`ds.m_HasStackup` is `False`). Workaround (unverified): parse the `(stackup ...)` block from the `.kicad_pcb` text, or use IPC `Board.get_stackup()` (the `pcb_stackup` tool).
- Courtyards: `fp.GetCourtyard(layer)` gives a polygon set; `fp.GetBoundingBox(False)` the box without text. Enough for overlap tests.
- Zones: `b.Zones()` gives net, layer, `IsFilled()`, `GetFilledArea()`, priority, and `GetIsRuleArea()` for keepouts (4 here).
- Traps: after removing every track, `b.GetTracks()` raises `TypeError: 'SwigPyObject' object is not iterable` (guard the empty case); `b.Remove(t)` prints "memory leak" warnings, `b.RemoveNative(t)` is clean. Run KiCad's Python with `-I` so the project folder cannot shadow a module.
- DRC inside Python: no DRC class is exposed (`dir(pcbnew)` has no `DRC*` names). Use `kicad-cli pcb drc`.
- Length: no length-tuning helper. Track length is the sum of `PCB_TRACK.GetLength()` per net (15.99 mm on `/USB_DP`). Length checks stay Boardwright code.

### 1.3 What is deprecated

- The official developer docs say the SWIG Python bindings have been deprecated since KiCad 9.0, with removal planned for KiCad 11.0 (taken from a search summary of https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/; I did not read the page text, so the exact version is unverified). Third-party notes saying "removed in 10.0" are wrong for 10.0.8, where the module imports and works.
- Consequence: the engine can rely on `pcbnew` for KiCad 9 and 10 now. Keep every `pcbnew` call behind one small adapter module so a later switch touches one file.

### 1.4 The IPC API and `kipy`

- Overview: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/index.html . Protocol buffers over NNG on a local socket; KiCad is the server; requests are handled one at a time, so they can time out when KiCad is busy and clients should retry.
- Python client `kicad-python` (import name `kipy`) 0.8.0, 30 Aug 2026; needs KiCad 9+ running with the API server enabled; `pip install kicad-python`. https://pypi.org/project/kicad-python/ . Docs: https://docs.kicad.org/kicad-python-main/ . It is not installed in KiCad's bundled Python here (`import kipy` fails); I did not install it.
- Board API, from https://docs.kicad.org/kicad-python-main/board.html (first 100,000 of about 292,000 characters read): `get_tracks()` (tracks and arcs), `get_stackup()`, `refill_zones()`, `place_footprint_from_library()`, `flip_items()`, `interactive_move()` (starts a move in the editor; other calls return busy meanwhile), `import_netlist()`, `get_items_by_net()`, `get_connected_items()`, `set_design_rules()`. I found no router, push-and-shove, differential pair or length-tuning calls in what I read; unverified for the rest.
- Limits: needs a running KiCad GUI. Per a search summary of https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/ (unverified), KiCad 9 and 10 have no plot/export through it, and KiCad 10 has no schematic editing commands.
- Fit: the engine writes a routed result; the agent pushes it into an open board with `pcb_add_tracks` (this is how `bw_edit.py route --dry-run` already works when KiCad holds the board's lock file).

---

## 2. Freerouting from an engine

Sources: https://github.com/freerouting/freerouting , https://github.com/freerouting/freerouting/releases (v2.5.0, 05 Oct 2026), and `docs/command_line_arguments.md` (master branch, raw). Nothing was downloaded or run.

- Java: the README says install a JRE, choose version 25, run `java -jar path/to/freerouting.jar`. Release notes say v2.2.0 requires Java 25. This machine has Java 1.8, so the jar will not start here. v2.5.0 also lists native CLI binaries (GraalVM; Linux x64, macOS, Windows x64) that "eliminate the Java JRE requirement for CLI users". The release page shows `freerouting-2.5.0.jar` (61.6 MB) and an `.msi` (84.6 MB); I did not see the CLI file names, so check the asset list.
- Documented flags that matter:
  - `-de file.dsn` load the design. It also accepts `.ses`, `.rules`, `.kicad_dru`, `.kicad_pro` joined with `+`; what it does with `.kicad_dru` is unverified.
  - `-do file.ses` save the session when routing ends (`.dsn`, `.scr` by extension).
  - `-drc file.json` write a design rules check in KiCad's JSON DRC format.
  - `--gui.enabled=false` the closest documented headless switch (the doc defines no "headless mode" as such).
  - `--router.autorouter.max_passes=N`, `--router.max_threads=N`, `--router.optimizer.enabled=true|false`, `--router.optimizer.improvement_threshold=2.5`, `--router.optimizer.item_selection_strategy=sequential|prioritized`, `--router.layers.routable=false,true`, `--router.via_costs=N`.
  - `-inc GND,Power` net classes the autorouter skips. This is the hook for Boardwright's rule that mains, hazardous and fast nets are never auto-routed.
  - `-da` no analytics, `--user_data_path=DIR` (needs the `=` form), `--logging.console.level=WARN`.
  - Removed in 2.5.0: `-hr`, `-us`, `-im`. Deprecated aliases: `-mp`, `-mt`, `-oit`, `-is`.
- Exit codes: not documented in the sources I read. Do not rely on them. Treat "the `.ses` exists and is newer than the `.dsn`" as success, then always run DRC.
- API server: `--gui.enabled=false --api_server.enabled=true --api_server.authentication.enabled=false --api_server.endpoints=http://127.0.0.1:37864` (default endpoint `http://127.0.0.1:37864`, authentication on by default). v2.5.0 adds a one-call `POST /v1/autoroute` and an MCP tool `autoroute_board`. A public hosted API exists at `https://api.freerouting.app/v1`; never send a customer's board there. Self-hosting notes are in `docs/self-hosting.md` (not read).
- v2.5.0 also has a KiCad 10 IPC mode that falls back to DSN/SES when IPC is unavailable. Boardwright should use DSN/SES because it needs no running editor.

Untested command shape:

```bash
freerouting --gui.enabled=false -da -de board.dsn -do board.ses \
  --router.autorouter.max_passes=40 --router.optimizer.enabled=true \
  -inc "Mains,HS" --logging.console.level=WARN
```

What is lost, which the engine must cover itself:

1. Differential pairs, length limits, impedance. Route those by hand or with Boardwright's `bw_router.py` (a grid A* with no pair support), and keep them out of Freerouting with `-inc`.
2. `.kicad_dru` rules (mounting-hole clearance, per-class minimum width). Catch them with KiCad DRC after import.
3. Copper pours: Freerouting sees `plane` layers; run `ZONE_FILLER.Fill` after import (0.16 s here).
4. Teardrops, silkscreen, soldermask: untouched.
5. Existing tracks: the DSN carries them as `(wiring)`. Decide per run whether to keep hand routes (delete only unprotected tracks before export).

Repeatability: the autorouter is documented as single-threaded with a pass limit, which suggests the same input and flags give the same output, but this is unverified. Store the DSN hash, flags and Freerouting version in the history step.

---

## 3. MCP server design for tokens

### 3.1 What costs tokens

Counted in this session:

| Server | Tools |
|---|---|
| `kicad-live` (kicad-buddy) | 62 |
| `kicad-schematic` (mcp-server-kicad) | 42 |
| `bw_mcp.py` (Boardwright today) | 8; `tools/list` is 2,754 characters, about 700 tokens (estimate at 4 characters per token) |

Levers:

- Tool definitions. Claude Code defers MCP tools by default ("tool search"): only tool names and server instructions load at session start; a schema loads when the model searches for it. `ENABLE_TOOL_SEARCH`: unset or `true` = deferred; `auto` / `auto:N` = load upfront while definitions are under N% of context (default 10%); `false` = all upfront. A tool can set `_meta["anthropic/alwaysLoad"]: true` to stay upfront; the user's `alwaysLoad` setting can override a plugin's. https://code.claude.com/docs/en/mcp . With tool search the cost of many tools is lower but each search is a round trip; other clients may load every definition every turn (unverified), so keep the list short anyway.
- Descriptions. Claude Code cuts server instructions and upfront-tool descriptions at 4,096 characters, deferred-tool descriptions at 16,384. Tool search matches on the start of the description, so put the key words first. `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH` changes both limits.
- Results. A warning above 10,000 tokens, truncation at 25,000 tokens by default (`MAX_MCP_OUTPUT_TOKENS`), text over 50,000 characters saved to a file; a tool can raise its own limit with `_meta["anthropic/maxResultSizeChars"]`, up to 500,000. Target: most results under 1,000 tokens.
- Few batch tools beat many thin tools. Every tool costs a name and a schema. One tool per verb with an `op` list (what `bw_edit.py` does with JSON ops) is one round trip and one result. kicad-schematic shows the opposite: 42 tools, one per primitive, many calls per symbol.
- Structured output. The spec (https://modelcontextprotocol.io/specification/2025-06-18/server/tools) allows `outputSchema` plus `structuredContent`, and says a tool returning structured content SHOULD also return the JSON as a text block. A model reads the text block, so the schema adds definition tokens and saves no result tokens. Skip `outputSchema` for model-facing tools. Set `annotations.readOnlyHint` on read tools (the spec says clients treat annotations as untrusted unless the server is trusted).
- Compact shape: a header row and arrays, not repeated keys.

```
cols: ref,x,y,rot,side
C1,101.2,118.5,180,F
C2,103.0,118.5,0,F
total 33, more: cursor 2
```

  This is roughly a third of the tokens of a list of JSON objects (estimate, not measured). Always return `total` and a cursor instead of everything. Today's `MAX_CHARS` is 20,000; lower it to about 6,000.
- Resources versus tools. Resources (`boardwright://status`, `boardwright://report/stage5`) are chosen by the client or user (`@` mentions), not by the model, and suit big stable documents. Tools suit anything with arguments or side effects. Client support for resources varies (unverified for Codex and Cursor), so give the same text through a tool too.
- Instructions. Put the short working rules in the server `instructions` (under 4,096 characters), not in each tool description.

### 3.2 SDK or no SDK

- Official Python SDK: https://github.com/modelcontextprotocol/python-sdk (FastMCP decorators build schemas from type hints). Pros: protocol upgrades, pagination, HTTP transport. Cons: a dependency; KiCad's bundled Python has `pip` but not `mcp`, so it needs `uvx` (the plugin already uses `uvx` for `mcp-server-kicad`).
- Dependency-free stdio (what `bw_mcp.py` does): JSON-RPC lines on stdin/stdout; methods `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`. About 200 lines, no install, matches Boardwright's standard-library-only rule. Tested skeleton with `structuredContent`:

```python
import json, sys
TOOLS = {"board_find": {"description": "Find board items. Compact rows.",
  "inputSchema": {"type": "object", "properties": {"kind": {"type": "string"}}, "required": ["kind"]},
  "annotations": {"readOnlyHint": True}}}
def call(name, a):
    sc = {"rows": [["C1", 101.2, 118.5]], "more": False}
    return {"content": [{"type": "text", "text": json.dumps(sc, separators=(",", ":"))}],
            "structuredContent": sc}
for line in sys.stdin:
    m = json.loads(line); i = m.get("id"); meth = m.get("method")
    if i is None: continue                       # notifications get no reply
    r = ({"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "bw", "version": "0"}}
         if meth == "initialize" else
         {"tools": [dict(name=k, **v) for k, v in TOOLS.items()]} if meth == "tools/list" else
         call(m["params"]["name"], m["params"].get("arguments", {})) if meth == "tools/call" else {})
    print(json.dumps({"jsonrpc": "2.0", "id": i, "result": r}), flush=True)
```

  Piping an `initialize` and a `tools/call` into it gave the expected replies. Recommendation: stay dependency-free. Board work runs as a child process under KiCad's Python (as `kicad_python.ensure()` already does), so each call sees a fresh board; the start-up cost per call is unmeasured.

### 3.3 Bundling in the Claude Code plugin

From https://code.claude.com/docs/en/plugins-reference and /mcp:

- A plugin ships servers in `.mcp.json` at the plugin root, or inline under `mcpServers` in `.claude-plugin/plugin.json`; both merge, later names win. `${CLAUDE_PLUGIN_ROOT}` (install dir, changes on update), `${CLAUDE_PLUGIN_DATA}` (kept across updates) and `${CLAUDE_PROJECT_DIR}` resolve in `command`, `args` and `env` of stdio servers.
- Tool name seen by the model, permissions, skill `allowed-tools` and hook matchers: `mcp__plugin_<plugin>_<server>__<tool>`, with characters outside `A-Za-z0-9_-` replaced by `_`. A matcher written `mcp__<server>__.*` never fires for a plugin server. For plugin `boardwright` and a new server `boardwright`: `mcp__plugin_boardwright_boardwright__status`. The existing servers already show up as `mcp__plugin_boardwright_kicad-live__...`.
- New entry beside the two existing ones in `plugin/.mcp.json` (shape from the docs, not run):

```json
"boardwright": {
  "type": "stdio",
  "command": "python",
  "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/bw_mcp.py"],
  "env": {"BW_PROJECT": "${CLAUDE_PROJECT_DIR}"}
}
```

  The server's working directory for a plugin stdio server is not stated in what I read (unverified), hence the `project` argument already on every tool; `BW_PROJECT` is a proposal (today the server falls back to its working directory). On Windows a bare `python` may be the Store stub; the hooks use `python ... || python3 ...`, so a small launcher that tries `py -3`, `python`, `python3` is safer (unverified on a clean machine).
- Hooks (https://code.claude.com/docs/en/hooks): a matcher with only letters, digits, `_`, `-`, `,`, `|` is an exact list; anything else is an unanchored JavaScript regex. Boardwright's `hooks.json` already uses `mcp__plugin_boardwright_.*`, so the new server's calls reach `edit_hooks.py pre|post` with no hooks.json change. What does need changing: the `WRITE_MCP` regex in `edit_hooks.py` only knows `kicad-live` and `kicad-schematic`; add the new write tools (`edit|place|route|history|fab`) or the lock and history step will not fire. `PreToolUse` can return `permissionDecision: "deny"` with a reason (or exit code 2) for MCP tools like any tool. Whether `PostToolUse` can rewrite an MCP result: unverified (my read of the page stopped before that section).
- A hook can itself be `"type": "mcp_tool"` and call a tool on a connected server. Not needed here.

### 3.4 Other clients

- Codex (https://learn.chatgpt.com/docs/extend/mcp?surface=cli): `~/.codex/config.toml` or project `.codex/config.toml` (trusted projects only):

```toml
[mcp_servers.boardwright]
command = "python"
args = ["C:/path/to/plugin/scripts/bw_mcp.py"]
cwd = "E:/PCB/my-board"
tool_timeout_sec = 300
```

  or `codex mcp add boardwright -- python C:/path/to/bw_mcp.py`. Defaults are 10 s startup and 60 s per tool, so engine runs need `tool_timeout_sec` raised. `enabled_tools` / `disabled_tools` can hide write tools.
- Cursor: `.cursor/mcp.json` or `~/.cursor/mcp.json`, `{"mcpServers": {"boardwright": {"command": "python", "args": ["..."]}}}` (from memory, unverified).
- Claude Desktop: `claude_desktop_config.json`, same `mcpServers` shape (from memory, unverified).
- Cursor and Desktop have no Claude Code hooks, so every guard must live inside the server (section 4.3). All use stdio with one JSON message per line; `bw_mcp.py` already speaks protocol `2025-06-18`.

### 3.5 Existing KiCad MCP servers

| Server | Size | How it reaches KiCad | Good | Wasteful or risky |
|---|---|---|---|---|
| kicad-buddy, https://github.com/mburger89/KiCAD-Buddy (MIT; the `kicad-live` entry in `plugin/.mcp.json`; command `kicad-buddy`) | 62 tools: session/escape hatch 8, PCB 25, schematic 12, validation/manufacturing 7, libraries 10; plus a catalogue of about 850 KiCad actions (`kicad_list_actions`, `kicad_run_action`) | IPC API for live board edits; `kicad-cli` for DRC/ERC/exports; direct file edits for schematics and libraries (writes `.bak`) | Undoable live edits; one escape hatch instead of hundreds of tools; honest about the schematic gap | 62 definitions; needs KiCad running with the API enabled; `kicad_run_action` can do anything, so hooks must guard it |
| mixelpixx/KiCAD-MCP-Server, https://github.com/mixelpixx/KiCAD-MCP-Server (MIT, 3.4k stars) | tool count not stated on the README (the "228 tools" figure belongs to a separate closed project); categories include routing, DRC/ERC, export, JLCPCB parts, Freerouting | SWIG `pcbnew`, experimental IPC backend; Python and TypeScript | Closest in scope; has Freerouting through Java or Docker | Large surface; SWIG-based so exposed to the deprecation |
| lamaalrajih/kicad-mcp, https://github.com/lamaalrajih/kicad-mcp (MIT, 537 stars) | few tools (DRC via `kicad-cli`, BOM, netlist, thumbnails), a resource `kicad://projects`, a prompt `debug_pcb_issues` | CLI and file parsing | Small; uses resources and prompts; cross-platform | Read-mostly; docs aimed at Claude Desktop |
| mcp-server-kicad (the `kicad-schematic` entry, pinned `0.21.1` via `uvx`) | 42 tools | direct `.kicad_sch` edits | Covers schematic editing IPC cannot | One tool per primitive; long repeated server instructions (this session lists the same server twice, doubling that cost) |
| `mcp-kicad` on PyPI, https://pypi.org/project/mcp-kicad/ | unverified | IPC API (per search listing) | unverified | unverified |

Lesson: none of them offers a deterministic place-and-route engine behind a small tool surface. The wasteful pattern is many primitive tools plus long repeated instructions; the good pattern is one escape hatch plus batch operations.

---

## 4. Recommendation

### 4.1 Architecture

- Keep the plugin as is (skills, slash commands, agents, hooks, `.mcp.json`) and add a third server entry, `boardwright`. Keep the two external servers for now; make them optional in the docs once the new tools cover their use.
- The MCP server is a thin front on the existing scripts, as `bw_mcp.py` is now: each tool maps to a script call (`status.py`, `plan.py`, `run_gates.py`, `bw_edit.py`, `history.py`). The CLI, slash commands and tools then give identical results and share one test suite (`plugin/tests/test_mcp.py` exists).
- The engine is `bw_engine.py`, run under KiCad's Python via `kicad_python.ensure()`, with one adapter module over `pcbnew` (load, courtyards, move, DSN export, SES import, fill, save).
- Route steps: 1. list protected nets (mains, hazardous, fast, differential), as today's refusals do, and pass their classes to `-inc`; 2. export DSN; 3. run Freerouting headless; 4. import SES; 5. refill zones; 6. DRC before/after (reuse `drc_diff` in `bw_edit.py`); 7. keep the result only if DRC is not worse, else restore the files; 8. history step with DSN hash, flags, Freerouting version.
- Place steps: a seeded search over courtyard polygons (`SHAPE_POLY_SET` overlap), fixed connectors and holes, keepouts and decoupling-distance rules, scored by ratsnest length; the same seed gives the same board. `op_place` / `_place` in `bw_edit.py` are the base.

### 4.2 Tools (13)

All results are compact rows with `total` and `more`. `project` is optional on every tool. RO = read only (set `readOnlyHint`).

| Tool | Purpose | Inputs | Compact output |
|---|---|---|---|
| `status` (RO) | Where the project is and what is next (merges today's `status` and `plan`) | `view`: `status` or `plan` | stage table, READY steps, failed gates; at most 40 lines |
| `check` | Run a check; writes `reports/` | `what`: `gates`, `sch`, `drc`, `erc`, `fab`; `since` | pass/fail, counts by severity, first N findings as `id,sev,where,msg`, cursor |
| `find` (RO) | Search board items | `selector`, `limit`, `cursor` | header row plus rows |
| `edit` | Batch board edit: move, set, add, delete, netclass, rule, refill | `ops` array, `dry_run` | one line per op, DRC delta (`errors +0/-1`), step id |
| `place` | Engine: place footprints | `refs` or `block`, `region`, `seed`, `dry_run` | ref,x,y,rot,side; overlap and wirelength score |
| `route` | Engine: route unprotected nets with Freerouting | `nets` or `classes`, `passes`, `dry_run` | protected list, routed/failed nets, total length, DRC delta |
| `engine` (RO) | Engine readiness | none | KiCad Python, Freerouting and Java versions, ready or not |
| `routing_plan` (RO) | Show corridors and status | none | one row per corridor |
| `history` | List, diff, restore design steps | `op`, `id` | step rows; `restore` needs consent (4.3) |
| `fab` | Factory minimums check; build release files | `op`: `check`, `release`; `fab` | gaps table; file list for `release` |
| `parts` (RO) | Lifecycle, stock, register | `refs` | one row per part, `unverified` where unknown |
| `lifecycle` | Stage steps, retro, lock/unlock | `op` | stage line |
| `diag` (RO) | Doctor and diagnostics summary | `op` | pass/fail lines |

Live editing in an open KiCad stays with kicad-buddy (`kicad_run_action` and the `pcb_*` tools). With one-line descriptions the 13 definitions should fit in roughly 4,000 characters (about 1,000 tokens; estimate); document `edit` ops by example in the server instructions, not in the schema. Mapping from today's 8: `status` + `plan` -> `status`; `run_gates`, `sch_check` -> `check`; `fab_check` -> `fab`; `history_list` -> `history`; `routing_plan_show` -> `routing_plan`; `board_find` -> `find`. Keep the old names as aliases for one release.

### 4.3 Guards

- Edit lock. `edit_hooks.py pre` takes the project's one-editor lock before a tool changes a design file; this only works in Claude Code. Make the server take the same lock (the `history` module's) before any write tool (`edit`, `place`, `route`, `history restore`, `fab release`). Codex, Cursor and Desktop then get the lock too; in Claude Code it is taken twice by the same holder. The KiCad lock-file test in `bw_edit.py` (`~name.lck` means KiCad has the board open; refuse unless `--dry-run`) carries over unchanged.
- History. `post` saves a step after any edit when a design file changed. Have the server save a step after its own write tools as well; add the new tool names to `WRITE_MCP` so the hook still fires, and a second save is a no-op because nothing changed.
- Approvals. Routing-plan approval comes from what the designer typed (the `UserPromptSubmit` hook), so the model cannot approve its own plan. A server cannot tell who typed. So no approve, reject or consent tool: the server reads the recorded approval and `route` refuses corridors that are not approved; `routing_plan` only shows. Outside Claude Code, approval is a command the human runs (`python scripts/routing_plan.py . approve c1`). MCP elicitation (the server asks the user through the client) could give an in-client approval; client support is unverified.
- Consent (diagnostics, anything that sends data) stays user-typed only; the server sends nothing anywhere. The engine must refuse a Freerouting API URL that is not local.
- No order, send or publish tool. `fab release` writes `fab/` and stops. `history restore` and `fab release` refuse unless the user's slash command or CLI left a one-time token file in `.boardwright/`; that also gives other clients a manual path.
- Output size: `MAX_CHARS` from 20,000 to about 6,000, with cursors.

### 4.4 Order of work

1. Write the `bw_engine.py` adapter and a DSN round-trip unit test (KiCad's Python only; the experiment in section 1.1 is the test body).
2. On a machine with Java 21 or newer, or the native CLI, run the Freerouting command in section 2 once; record exit code and run time. Nothing here depends on that run having succeeded.
3. Grow `bw_mcp.py` to the 13 tools; add the `boardwright` entry to `plugin/.mcp.json`; widen `WRITE_MCP`; extend `plugin/tests/test_mcp.py`.
4. Measure `tools/list` tokens and a typical session (status, check, find, edit, route) before and after. No token saving is measured yet; every figure above is a character count or estimate.

## Sources

- KiCad IPC API: https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/index.html , https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/
- KiCad pcbnew bindings status: https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/ (search summary only)
- kicad-python (kipy): https://pypi.org/project/kicad-python/ , https://docs.kicad.org/kicad-python-main/board.html
- Freerouting: https://github.com/freerouting/freerouting , https://github.com/freerouting/freerouting/releases , https://raw.githubusercontent.com/freerouting/freerouting/master/docs/command_line_arguments.md
- Claude Code: https://code.claude.com/docs/en/mcp , https://code.claude.com/docs/en/hooks , https://code.claude.com/docs/en/plugins-reference
- MCP: https://modelcontextprotocol.io/specification/2025-06-18/server/tools , https://github.com/modelcontextprotocol/python-sdk
- Codex MCP: https://learn.chatgpt.com/docs/extend/mcp?surface=cli
- KiCad MCP servers: https://github.com/mburger89/KiCAD-Buddy , https://github.com/mixelpixx/KiCAD-MCP-Server , https://github.com/lamaalrajih/kicad-mcp
