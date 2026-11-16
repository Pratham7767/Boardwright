# For maintainers: releasing a new version

Nothing in this repository uploads anything by itself. These are the steps you run.

## Before a release

1. Put the same version number in `plugin/.claude-plugin/plugin.json` and `kicad-addon/metadata.json`.
2. Add a section for that version at the top of `CHANGELOG.md`. It becomes the release notes.
3. Run every check:

```bash
python tools/check_all.py
```

4. Commit and push to `main`. GitHub then runs the same checks on Windows and on Ubuntu with KiCad 10 (the **Actions** tab). Wait until they pass.

## Publish the release

Tag the version and push the tag (use your version number):

```bash
git tag -a v0.5.0 -m "Boardwright 0.5.0"
```
```bash
git push origin v0.5.0
```

GitHub then builds the KiCad chat-button zip and publishes a release with three files:

- `boardwright-kicad-<version>.zip`, the add-on;
- `boardwright-kicad.zip`, the same file under the fixed name the installers download;
- `metadata.repository.json`, the details KiCad's add-on store needs.

## After a check against the safety standard

When you have checked a spacing table against the purchased standard, record it, then commit:

```bash
python tools/mark_table_checked.py creepage_F5 --by "Your Name" --against "IEC 60664-1:2020 Table F.5"
```

Run `python tools/mark_table_checked.py` on its own to see every table and its status.

## Telling testers

Send them the repository link and `docs/TESTING.md`. Installing is one command, plus one step in KiCad (**Install from File...**).

## KiCad's official add-on store (optional)

This needs a review by the KiCad team. See the end of [kicad-addon/README.md](../kicad-addon/README.md).
