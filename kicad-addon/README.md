# The KiCad chat button

This folder is the KiCad add-on. It puts a speech-bubble button on the toolbar of KiCad's PCB Editor. The button opens a chat window, next to KiCad, that talks to **your own** Claude Code in the folder of the board you have open.

Works on Windows and Linux with KiCad 10. Most people get it through the main installer: see the [install guide](../docs/INSTALL.md).

## Install

1. Get `boardwright-kicad.zip`: the installer makes it, or download it from the repository's **Releases** page.
2. In KiCad: **Plugin and Content Manager → Install from File...**, pick the zip and close the window.
3. Restart KiCad and open a board. The speech-bubble button appears on the toolbar.

KiCad must have **Preferences → Plugins → Enable KiCad API server** ticked. The installer does this for you.

## The first time you open it

The **Setup** box at the top checks three things and offers a button for anything missing:

- **Claude Code installed.** If not, the button opens the official install page.
- **Signed in.** If not, **Sign in** starts Claude Code's own sign-in in your browser. The add-on never sees your password or keys.
- **Boardwright plugin.** If it is missing, the window uses the copy that comes with the add-on, and **Install** adds it to Claude Code permanently.

It also checks the helper tools. **Install helpers** installs any that are missing, asking before each one.

## Using it

- Type a message. **Enter** sends it; **Shift+Enter** starts a new line.
- **Stop** (or Esc) stops the current answer.
- Each action Claude takes shows as a short line. When Claude wants to change something, **Allow**, **Always allow** and **Deny** buttons appear.
- **Mode** sets how careful Claude is: ask before edits, accept file edits automatically, or plan only.
- **Model** picks the Claude model. If you hit a usage limit, pick another one and send again.
- **New chat** starts over. Every message uses your Claude plan.
- The window sits beside KiCad. It can't be docked inside KiCad, because KiCad doesn't allow that for add-ons.
- If nothing happens when you click the button, look at `%TEMP%\boardwright_launcher.log` (Windows) or `/tmp/boardwright_launcher.log` (Linux).

## Files

| File | What it does |
|---|---|
| `plugins/launch.py` | Runs when you click the button: finds the board's folder and opens the window |
| `plugins/bw_chat.py` | The chat window |
| `plugins/bw_core.py` | Finds Claude Code, runs the setup checks and talks to Claude Code |
| `metadata.json`, `plugins/plugin.json` | Tell KiCad what the add-on is |
| `build.py` | Builds the zip file |
| `tests/` | Tests that use a stand-in for Claude Code, so they need no account |

## Notes for developers

- **Why a separate window.** It runs outside KiCad, so a slow answer can never freeze the editor. It uses KiCad's newer IPC plugin system rather than the older one.
- **Why no extra Python packages.** KiCad installs an add-on's packages with pip. On a computer whose Documents folder has a non-English name, that step can hang forever in KiCad 10.0.8. So the add-on needs none: it finds the open board from the window title and KiCad's recent-files list.
- **Why the Claude Code plugin is zipped inside.** KiCad rejects an add-on that contains another program's `plugin.json` file. The copy is unzipped the first time it is needed.
- **Restart after a failed install.** KiCad keeps a failed add-on marked "busy" until it restarts.
- **Listing it in KiCad's official add-on store** needs a review by the KiCad team: a merge request to `gitlab.com/kicad/addons/metadata` with the release zip's address. Run `python build.py --download-url <release zip address>` first; it writes the details the store needs. You can also host your own add-on list with `python build.py --repo-url <web address>`.
