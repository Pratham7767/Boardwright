# Boardwright: working rules

Read `HANDOFF.md` first: where the work stands, what is open, how to resume. These rules come from the owner and apply to every session, on any computer.

- **Commits:** the owner's own git identity only. No `Co-Authored-By: Claude` or other Claude attribution line in commit messages (it puts Claude in the GitHub contributors list). Push to `origin main` only when the owner asks. Never rewrite pushed history without asking.
- **One product, one download:** keep the repo an MCP server (`plugin/scripts/bw_mcp.py`, registered in `plugin/.mcp.json`) and a Claude Code plugin. The KiCad add-on (`kicad-addon/`, built by `kicad-addon/build.py`) is the single thing a user installs; every feature must be reachable from it, and anything that needs installing is offered from the chat's Setup checks, asking first. Rebuild the add-on after changes.
- **Cheap models work, the strong model checks:** hand implementation, lookups and mechanical work to Sonnet or Haiku subagents; Opus verifies before anything is called done. The pipeline itself follows the same split (skill `model:` frontmatter; the Opus `gate-reviewer`).
- **Never loosen a check:** no rule is lowered, waived or filtered to make a gate or the routing engine pass. The engine keeps KiCadRoutingTools in strict mode and accepts copper only when KiCad's DRC shows no new error.
- **The user's decisions stay the user's:** routing-plan approval, diagnostics consent, undo, the choices file. No tool or hook makes them.
- **Nothing is sent, ordered, uploaded or published** without the owner's explicit OK. No password, API key or token is ever stored, printed or committed (that includes OmniRoute keys: they stay in OmniRoute's own settings on each computer).
- **Measure before claiming:** routing changes are judged by `tools/bench/engine_bench.py` on the KiCad demo boards; write results, including what got worse, in `docs/benchmark-engine.md`.
- **Smallest complete change** (the owner asked for the ponytail approach): reuse what exists, no options or abstractions nobody asked for, finish callers and tests.
- **Tests before pushing:** `python tools/check_all.py --quick` (about 5 min); routing changes also `python plugin/tests/test_engine.py`. CI runs on Windows and Ubuntu.
