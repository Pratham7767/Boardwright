---
name: pcb-doctor
description: Check that KiCad, the live link and the helper tools are set up for the PCB pipeline
model: haiku
disable-model-invocation: true
allowed-tools: Bash(python *scripts/doctor.py*), Bash(python3 *scripts/doctor.py*), PowerShell(python *scripts/doctor.py*)
---

Run `python "${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" .` and show its table.

For each row marked FAIL or warn, give the fix in one plain sentence. The usual ones:
- kicad-cli not found: install KiCad 9 or 10 from kicad.org, or set the `KICAD_CLI` environment variable to the full path of kicad-cli.
- uv, kicad-buddy or the KiCad API server missing: the plugin's setup script fixes all three. Show the user this command and offer to run it for them:
  `python "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --yes`
  Run it only after the user says yes in chat, and show its summary. It installs pinned versions of uv, kicad-buddy and mcp-server-kicad and ticks the KiCad API setting (only while KiCad is closed).
- live link not connected while KiCad is open: Preferences > Plugins > Enable KiCad API server, restart KiCad, open the board.

Never install anything without the user's yes in chat.
