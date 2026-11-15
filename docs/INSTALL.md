# Installing Boardwright

Plan on 15 to 30 minutes on a fresh computer, most of it downloads. You can stop and resume at any step; every step checks first and skips what is already there.

## What you need

| | Why | Where it comes from |
|---|---|---|
| **KiCad 9 or 10** | the design tool | https://www.kicad.org/download/ (Windows: also `winget install KiCad.KiCad`) |
| **Claude Code** + a Claude plan (Pro, Max, Team, Enterprise) or Anthropic API credit | does the design work | https://code.claude.com/docs/en/setup |
| **Python 3.10+** | runs the gate and export scripts | https://www.python.org (tick "Add python.exe to PATH") |
| **Git** | Claude Code needs it on Windows; also used for the plugin marketplace | https://git-scm.com |
| **uv** | runs the two KiCad helper tools | installed for you by the setup script |
| **kicad-buddy** 0.1.0 | live link between Claude and the open KiCad window | installed for you by the setup script |
| **mcp-server-kicad** 0.21.1 | schematic editing tools | downloaded for you by the setup script |

The installer only uses official installers (winget, claude.ai, astral.sh) and pinned versions of the two helpers.

## Option A: the installer (recommended)

### Windows
Open **PowerShell** (Start menu → type PowerShell) and paste:

```powershell
irm https://raw.githubusercontent.com/prathware/boardwright/main/install/install.ps1 | iex
```

If the repository is **private** (shared with you before it went public), this line won't work. Clone it instead:

```powershell
git clone https://github.com/prathware/boardwright.git
cd boardwright
powershell -ExecutionPolicy Bypass -File install\install.ps1
```

### macOS / Linux (untested)

```bash
curl -fsSL https://raw.githubusercontent.com/prathware/boardwright/main/install/install.sh | bash
```
or from a clone: `bash install/install.sh`.

### What the installer does, step by step
1. **KiCad**: looks for `kicad-cli`; offers `winget install KiCad.KiCad` if missing.
2. **Python**: looks for Python 3.10+ (it ignores the Microsoft Store stub); offers `winget install Python.Python.3.12`.
3. **Git**: offers `winget install Git.Git`.
4. **Claude Code**: offers the official installer.
5. **Plugin**: `claude plugin marketplace add prathware/boardwright` (or your clone's folder), then `claude plugin install boardwright@boardwright`.
6. **Helpers**: runs the plugin's `scripts/setup.py`, which installs uv, kicad-buddy and its companion KiCad plugin, downloads the schematic tools, and ticks KiCad's **Enable KiCad API server** setting. It changes that setting only while KiCad is closed, and keeps a `.bak` copy.
7. **KiCad add-on** (Windows): builds or downloads `boardwright-kicad.zip` and shows it in Explorer. KiCad installs add-ons itself, so this last step is yours:
   - KiCad main window → **Plugin and Content Manager** → **Install from File...** → pick `boardwright-kicad.zip` → **Close**.
   - **Restart KiCad**, then open a board in the PCB Editor. The speech-bubble button appears on the top toolbar.
8. **Sign-in**: starts `claude auth login`, Claude Code's own sign-in in your browser.

It ends with a list of anything left for you.

## Option B: by hand

```bash
# 1. the Claude Code plugin
claude plugin marketplace add prathware/boardwright
claude plugin install boardwright@boardwright

# 2. the helper tools: find the plugin folder, then run its setup script
claude plugin list --json          # look for "installPath" of boardwright@boardwright
python "<installPath>/scripts/setup.py"          # python3 on macOS/Linux

# 3. sign in (Claude Code's own browser flow)
claude auth login
```

KiCad add-on (Windows): download `boardwright-kicad.zip` from the repository's **Releases** page, or build it from a clone with `python kicad-addon/build.py` (it lands in `kicad-addon/dist/`). Then install it with **Install from File...** as in step 7 above.

Check everything: open any folder in Claude Code and run `/boardwright:pcb-doctor`.

## Your first board

1. Make an empty folder, for example `Documents\boards\my-first-board`.
2. Open it in Claude Code (terminal: `cd` there and run `claude`; VS Code: File → Open Folder, then the Claude panel).
3. Type `/boardwright:pcb-new guided` and describe the board in a sentence or two, for example: *"A USB-C powered board with a temperature sensor and an LED, about 30 x 40 mm."*
4. Answer the questions. Claude stops after every stage to show you what it did. Keep KiCad open with the project when it gets to layout (stage 5): you'll see the parts and tracks appear.

## Updating

Run the installer again. Or by hand:

```bash
claude plugin marketplace update boardwright
claude plugin update boardwright@boardwright
```

Then restart Claude Code. For the KiCad add-on, install the new zip with **Install from File...** and restart KiCad.

Projects keep their own copy of the gate scripts. After an update, Claude tells you when they are older than the plugin's and offers to refresh them (`init_project.py --update-scripts`).

## Uninstalling

```bash
claude plugin uninstall boardwright@boardwright
claude plugin marketplace remove boardwright
uv tool uninstall kicad-buddy
```
KiCad add-on: **Plugin and Content Manager → Installed → Boardwright → Uninstall**. Your board folders are never touched.

## Troubleshooting

| Problem | Fix |
|---|---|
| The KiCad button doesn't appear | Restart KiCad once after installing or updating the add-on. Check **Preferences → Plugins → Enable KiCad API server** is ticked. Then **Preferences → PCB Editor → Action Plugins**: "Show button" for Boardwright chat. |
| Clicking the button does nothing | Read `%TEMP%\boardwright_launcher.log`. |
| "You've reached your ... limit" | Pick another model in the window's model menu (or `/model` in Claude Code) and send again. |
| Claude can chat but can't see the board | Open the board in KiCad first; run `/boardwright:pcb-doctor`; if "KiCad API connection" is not ok, tick the API server setting and restart KiCad. |
| `python` opens the Microsoft Store | That's Windows' placeholder. Install Python from python.org with "Add to PATH" ticked, or run the installer again. |
| KiCad add-on stuck after a failed install | KiCad keeps a failed add-on "busy" until it restarts. Restart KiCad. |
| Your Documents folder has a non-English name (e.g. OneDrive\文档) | Supported: the add-on needs no Python packages, which avoids a KiCad 10.0.8 pip hang on such paths. |

Still stuck? Open an issue with the output of `/boardwright:pcb-doctor`; see [TESTING.md](TESTING.md).
