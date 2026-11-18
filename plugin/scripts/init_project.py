#!/usr/bin/env python3
"""Create a PCB pipeline project folder from the plugin templates.

Usage:  python init_project.py <target_dir> [--name NAME] [--update-scripts]
--update-scripts replaces the gate scripts in <target_dir>/scripts with the plugin's current ones.
Never overwrites existing files.
"""
import shutil
import sys
from pathlib import Path

# Paths and part names can be non-English (e.g. OneDrive\文档); a pipe on Windows defaults to cp1252.
for _s in (sys.stdout, sys.stderr):
    if _s and (getattr(_s, "encoding", "") or "").lower().replace("-", "") != "utf8":
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

GITIGNORE = ["*.kicad_prl", "*-backups/", "fp-info-cache", "__pycache__/",
             ".env", "secrets.env", "~*.lck", ".history/", ".boardwright/"]


def main():
    argv = sys.argv[1:]
    update = "--update-scripts" in argv
    if update:
        argv.remove("--update-scripts")
    name = None
    if "--name" in argv:
        i = argv.index("--name")
        if i + 1 >= len(argv):
            print("--name needs a value")
            return 2
        name = argv[i + 1]
        del argv[i:i + 2]
    if len(argv) != 1:
        print("Usage: python init_project.py <target_dir> [--name NAME]")
        return 2
    target = Path(argv[0]).resolve()
    name = name or target.name
    target.mkdir(parents=True, exist_ok=True)

    tpl = Path(__file__).resolve().parent.parent / "templates" / "project"
    if tpl.is_dir():
        for src in sorted(tpl.rglob("*")):
            rel = src.relative_to(tpl)
            dst = target / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            elif dst.exists():
                print(f"kept     {rel}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    text = src.read_text(encoding="utf-8")
                except (UnicodeDecodeError, ValueError):
                    shutil.copy2(src, dst)
                else:
                    dst.write_text(text.replace("{{PROJECT_NAME}}", name),
                                   encoding="utf-8", newline="")
                print(f"created  {rel}")
    else:
        print(f"templates/project not found at {tpl}; creating folders only")

    # Gate scripts are copied into the project so it works without the plugin path.
    here = Path(__file__).resolve().parent
    (target / "scripts").mkdir(exist_ok=True)
    # the gate scripts and the stage graph they read; not the plugin-only tools
    plugin_only = {"init_project.py", "setup.py", "session_start.py", "selftest.py"}
    # every script and every data file the scripts read (stage graph, spacing tables, factory profiles, prices)
    for src in sorted(list(here.glob("*.py")) + list(here.glob("*.json"))):
        if src.name in plugin_only:
            continue
        dst = target / "scripts" / src.name
        if dst.exists() and dst.read_bytes() != src.read_bytes() and not update:
            print(f"kept     scripts/{src.name} (differs from the plugin version; rerun with --update-scripts to replace it)")
        else:
            shutil.copy2(src, dst)
            print(f"copied   scripts/{src.name}")
    # quiet_site/sitecustomize.py: keeps KiCad's message boxes out of unattended engine runs
    (target / "scripts" / "quiet_site").mkdir(exist_ok=True)
    qsrc, qdst = here / "quiet_site" / "sitecustomize.py", target / "scripts" / "quiet_site" / "sitecustomize.py"
    if qdst.exists() and qdst.read_bytes() != qsrc.read_bytes() and not update:
        print("kept     scripts/quiet_site/sitecustomize.py (differs from the plugin version; rerun with --update-scripts to replace it)")
    else:
        shutil.copy2(qsrc, qdst)
        print("copied   scripts/quiet_site/sitecustomize.py")
    for d in ("reports", "datasheets", "fab"):
        (target / d).mkdir(exist_ok=True)
    gi = target / ".gitignore"
    if gi.exists():
        print("kept     .gitignore")
    else:
        gi.write_text("\n".join(GITIGNORE) + "\n", encoding="utf-8")
        print("created  .gitignore")
    print(f"\nProject folder ready: {target}")
    print("Next step: Open this folder in Claude Code and run /boardwright:pcb-new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
