# Install guide

Setting up a new computer takes 15 to 30 minutes, mostly downloads. You can stop and start again at any point: each step checks first and skips what is already done.

## What gets installed

| Program | What it is for |
|---|---|
| KiCad 9 or 10 | The program you design the board in |
| Claude Code | Does the design work. Needs a paid Claude plan or an Anthropic API account. |
| Python 3.10 or newer | Runs Boardwright's checks |
| Git | Claude Code needs it on Windows |
| uv, kicad-buddy, mcp-server-kicad | Small helper tools that let Claude work inside KiCad |

Everything comes from its official source.

## The easy way: the installer

### Windows

1. Open **PowerShell**: press the Start button and type PowerShell.
2. Paste this line and press Enter:

```powershell
irm https://raw.githubusercontent.com/Pratham7767/Boardwright/main/install/install.ps1 | iex
```

### Linux

Open a terminal, paste this line and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/Pratham7767/Boardwright/main/install/install.sh | bash
```

Works on Ubuntu 22.04 and 24.04, and other distributions that install KiCad 9 or 10 as a normal package. Two cases don't work: KiCad installed as a Flatpak, and Ubuntu 20.04, which is too old.

### What happens next

The installer asks **Set up everything? [Y/n]**. Press Enter. It then:

1. installs KiCad, Python, Git and Claude Code if they are missing;
2. adds the Boardwright plugin to Claude Code;
3. installs the helper tools and turns on KiCad's API setting, which lets Claude talk to KiCad;
4. prepares the KiCad chat button and shows you where the file is;
5. opens your browser so you can sign in to Claude.

At the end it lists anything left for you to do.

### Last step: the KiCad chat button

KiCad installs add-ons itself, so this step is yours:

1. Open KiCad.
2. Click **Plugin and Content Manager**, then **Install from File...**.
3. Pick `boardwright-kicad.zip`, the file the installer showed you, and close the window.
4. Restart KiCad. Open a board in the PCB Editor: a speech-bubble button appears on the toolbar.

### If the repository is private

If someone shared Boardwright with you before it was public, the one-line install won't work. Use these instead:

```powershell
git clone https://github.com/Pratham7767/Boardwright.git
cd Boardwright
powershell -ExecutionPolicy Bypass -File install\install.ps1
```

## Check that it works

Open any folder in Claude Code and type:

```
/boardwright:pcb-doctor
```

It lists anything missing and how to fix it.

## Your first board

1. Make an empty folder, for example `Documents\boards\my-first-board`.
2. Open it in Claude Code. In a terminal, go to the folder and type `claude`. In VS Code, use File → Open Folder and open the Claude panel.
3. Type `/boardwright:pcb-new guided` and describe your board, for example: *"A USB-C powered board with a temperature sensor and an LED, about 30 x 40 mm."*
4. Answer the questions. Keep KiCad open when Claude reaches the layout stage: you will see the parts and tracks appear.

## Updating

Run the installer again. Or type these two commands:

```bash
claude plugin marketplace update boardwright
```
```bash
claude plugin update boardwright@boardwright
```

Then restart Claude Code. To update the KiCad chat button, install the new zip file the same way as before and restart KiCad.

## Removing it

```bash
claude plugin uninstall boardwright@boardwright
```
```bash
claude plugin marketplace remove boardwright
```

For the KiCad chat button: **Plugin and Content Manager → Installed → Boardwright → Uninstall**. Your board folders are never touched.

The installer also set up a few helpers. Remove them only if no other project uses them:

- The live link to KiCad (kicad-buddy), which the installer put in with uv:

```bash
uv tool uninstall kicad-buddy
```

  If you set it up by some other route, remove it the same way you installed it. The companion plugin it added inside KiCad is small and can stay.
- The setting "Enable KiCad API server" in KiCad's Preferences → Plugins can stay on. Other tools use it too.
- The chat button unpacks its own copy of the plugin the first time it runs. Delete that folder to get the space back:
  - Windows: `%LOCALAPPDATA%\Boardwright`
  - Linux and macOS: `~/.cache/Boardwright`

## Installing by hand

If you prefer not to use the installer:

```bash
claude plugin marketplace add Pratham7767/Boardwright
claude plugin install boardwright@boardwright
claude plugin list --json
```

The last command shows where the plugin is installed (`installPath`). Run the setup script from there:

```bash
python "<installPath>/scripts/setup.py"
```

Then sign in with `claude auth login`. Get the KiCad chat button from the **Releases** page of the repository.

## Fixing problems

| Problem | What to do |
|---|---|
| The chat button doesn't appear in KiCad | Restart KiCad once. Check **Preferences → Plugins → Enable KiCad API server** is ticked. |
| Clicking the button does nothing | Look at the log file: `%TEMP%\boardwright_launcher.log` on Windows, `/tmp/boardwright_launcher.log` on Linux. |
| "You've reached your limit" | Choose another model in the chat window's Model menu and send again. |
| Claude can chat but can't see the board | Open the board in KiCad first, then run `/boardwright:pcb-doctor`. |
| Typing `python` opens the Microsoft Store | Install Python from python.org and tick "Add python.exe to PATH". |
| Linux: "no Python with wxPython found" | Run `sudo apt install python3-wxgtk4.0`. |
| Linux: the button opens the wrong board | Open the board you want last, or install `wmctrl`. |

Still stuck? Open an issue on GitHub and include the output of `/boardwright:pcb-doctor`.
