# Publishing and releasing (for the maintainer)

Nothing in this repository uploads anything by itself. These are the steps you run.

## First push to GitHub
1. Create an empty repository named `boardwright` on GitHub, without a README or licence: this repository already has both. Public is easiest for testers; with a private repository, add each friend as a collaborator.
2. The repository is `github.com/Pratham7767/Boardwright`; every link, the plugin marketplace and the add-on identifier (`com.github.pratham7767.boardwright`) already point there.
3. Push:
   ```
   git remote add origin https://github.com/Pratham7767/Boardwright.git
   git push -u origin main
   ```
   The **checks** workflow runs on Windows and on Ubuntu with KiCad 10. Wait for it to pass (Actions tab).

## A release (needed once, so the installers can download the KiCad add-on)
1. Make sure the version is the same in `plugin/.claude-plugin/plugin.json` and `kicad-addon/metadata.json`, and that `CHANGELOG.md` starts with that version's section.
2. Run `python tools/check_all.py` locally.
3. Tag and push:
   ```
   git tag v0.3.0
   git push origin v0.3.0
   ```
   The **release** workflow builds the add-on and publishes a GitHub release with `boardwright-kicad-0.3.0.zip`, `boardwright-kicad.zip` (the fixed name the installers download) and `metadata.repository.json`.

## Telling testers
Send them the repository link and `docs/TESTING.md`. Installing is one command (README), plus one manual step in KiCad: **Install from File...** for the add-on.

## Later: the official KiCad add-on list
See `kicad-addon/README.md`, section "Getting it into the KiCad official repository". It needs the release above, and a merge request on GitLab that you open yourself.
