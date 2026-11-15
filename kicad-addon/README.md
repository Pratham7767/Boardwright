# Boardwright for KiCad (the add-on)

Most people should use the repository's installer; see `../docs/INSTALL.md`. This page is about the add-on itself. It runs on Windows and Linux (`platforms` in `metadata.json`). Linux needs wxPython for the system Python and a terminal emulator; see INSTALL.md.

A KiCad 10 add-on. It puts a **Boardwright chat** button on the PCB Editor toolbar. The button opens a chat window that talks to **your own Claude Code**, started in the folder of the open project with the boardwright plugin loaded.

## What you need
- KiCad 10.0 or newer, with **Preferences → Plugins → Enable KiCad API server** ticked.
- Claude Code installed and signed in with your own Claude account. If either is missing, the window walks you through it the first time.
- Nothing else: KiCad sets up a small Python environment for the add-on the first time, and the add-on needs no extra packages.

## Install from the zip (works today, no review needed)
1. Build it: `python build.py` (any Python 3.9+). This writes `dist/boardwright-kicad-<version>.zip`.
2. In KiCad's main window: **Plugin and Content Manager → Install from File...** and pick the zip.
3. Close the dialog. The add-on is installed straight away. Open the PCB Editor: KiCad first sets up a small Python environment for the add-on, which takes about 10 seconds, and then adds the button. If you are **updating** the add-on, or the button doesn't appear, restart KiCad once.
4. Open a board in the PCB Editor and click the speech-bubble button **Boardwright chat**. If you don't see it: **Preferences → PCB Editor → Action Plugins**, and tick "Show button" for Boardwright chat.

## First run
The **Setup** box at the top of the window checks three things:

| Check | If it fails |
|---|---|
| Claude Code installed | **How to install** opens the official page (code.claude.com/docs/en/setup) and copies `irm https://claude.ai/install.ps1 \| iex` to the clipboard. Paste it into PowerShell, then press **Check again**. |
| Signed in | **Sign in** runs `claude auth login`, which is Claude Code's own sign-in: a console window opens and your browser asks you to log in. The chat window waits and carries on by itself. The add-on never sees a password, key or token. |
| boardwright plugin | If it is missing, the chat loads the copy inside the add-on. **Install** adds it for every Claude Code session by running `claude plugin marketplace add %LOCALAPPDATA%\Boardwright\claude-plugin-<hash>` and then `claude plugin install boardwright@boardwright` (the window shows the exact path). |

It also lists `kicad-buddy`, `uvx` and `kicad-cli`. Without them the chat still works, but Claude can't drive KiCad. **Install helpers** opens a console that runs the plugin's `setup.py`, which asks before installing each one and can tick KiCad's API setting.

## Using it
- Type your message. **Enter** sends it; **Shift+Enter** starts a new line. **Stop** (or Esc) ends the current turn.
- Each tool call shows up as one line. When Claude wants to do something that needs your OK, an **Allow / Allow, don't ask again / Deny** bar appears.
- Mode menu: **Ask before edits** (Claude Code's default), **Auto-accept file edits**, **Plan only**. A new mode takes effect from the next message, in the same chat.
- Model menu: **your default** (whatever Claude Code uses), **Opus**, **Sonnet**, **Haiku**. If Claude Code answers that you've reached a model's usage limit, pick another one and send again; the chat carries on.
- **New chat** starts over. Every message counts against your Claude plan.
- The window sits next to KiCad. It can't dock inside KiCad, because KiCad has no API for third-party panels.
- If nothing happens when you click the button, read `%TEMP%\boardwright_launcher.log`.

## Why it is built this way (findings from testing on KiCad 10.0.8, Windows 11)
- **IPC plugin, not a classic pcbnew action plugin.** KiCad's docs call the IPC API the stable interface; the SWIG action-plugin API is the legacy one. An IPC plugin runs outside KiCad, so a slow Claude reply can't freeze the editor. Action buttons only exist in the PCB Editor in KiCad 9 and 10, which is why the button is there.
- **`requirements.txt` exists but lists no packages.** KiCad marks a Python plugin ready only after `pip install -r requirements.txt` succeeds, so the file must be there. When the KiCad documents folder has a non-English name (here `OneDrive\文档`), pip writes hundreds of KB of encoding errors that KiCad doesn't read while pip runs, and pip hangs forever. So the add-on needs no packages: it finds the open project from the PCB Editor's window title plus KiCad's recent-files list, and uses kicad-python only if it happens to be installed.
- **The Claude Code plugin is zipped inside the add-on.** KiCad reads every file named `plugin.json` under the add-on folder, and it rejects the whole add-on when it meets Claude Code's `.claude-plugin/plugin.json`. The copy is unpacked to `%LOCALAPPDATA%\Boardwright\` when it is first needed.
- **Restart after a failed setup.** When an add-on's environment setup fails, KiCad keeps it marked "busy" until KiCad restarts, so reloading plugins doesn't help.

## Getting it into the "KiCad official repository" list
For that, KiCad's team has to review a merge request. **None of the steps below has been done.** Each one needs your decision.
1. **Public source with an issue tracker.** Push this repository to `github.com/Pratham7767/Boardwright` and make it public. `metadata.json` already points its homepage and contact there.
2. **Licence.** The code is MIT, which KiCad accepts because it is GPL-compatible. The bundled `plugin/` folder is the same MIT code; the third-party tools are not bundled (see `../THIRD_PARTY.md`).
3. **Public download URL.** Attach `dist/boardwright-kicad-<version>.zip` and `dist/boardwright-kicad.zip` (the fixed name the installer downloads) to a GitHub release, then run `python build.py --download-url <that URL>`. This fills `dist/metadata.repository.json` with `download_url`, `download_sha256`, `download_size` and `install_size`. Rebuild whenever the zip changes, because the hash changes.
4. **Merge request.** You need a GitLab account. Fork https://gitlab.com/kicad/addons/metadata, add `packages/com.github.pratham7767.boardwright/metadata.json` (the content of `dist/metadata.repository.json`) and `icon.png` (from `resources/`), and open the merge request. Do not send it to `kicad/addons/repository`, which is generated automatically.
5. **Likely review questions:** the add-on starts a separate program (Claude Code) and needs a paid Claude account. Say both plainly in the merge request. The KiCad rule for "commercial services" is aimed at fab and part-ordering services. If the reviewers count Claude as one, they will ask you to write to plugins@kicad.org.

## Alternative: your own repository (no review)
`python build.py --repo-url https://<your host>/kicad` writes `dist/repo/` (`repository.json`, `packages.json`, `resources.zip`, the zip). Put that folder on any static web host (GitHub Pages works). Users then add `https://<your host>/kicad/repository.json` under **Plugin and Content Manager → Manage...**, and get updates from there. Nothing has been uploaded.

## Files
- `metadata.json`: the PCM package metadata that goes inside the zip (schema v2).
- `plugins/plugin.json`: the IPC-API plugin manifest (toolbar action).
- `plugins/launch.py`: runs when the button is clicked. It asks KiCad for the project folder and starts the window.
- `plugins/bw_chat.py`: the window (wxPython, run with KiCad's own Python).
- `plugins/bw_core.py`: finds Claude Code, runs the first-run checks and talks to Claude Code (its stream-json protocol, the same one the Agent SDK uses).
- `build.py`, `make_icons.py`, `tests/`: build, icons, tests (`python tests/test_core.py` uses a fake Claude Code, so it needs no account).
