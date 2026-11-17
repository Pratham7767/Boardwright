#!/usr/bin/env python3
"""Run every check this repository has, in one go. Used by CI and before a release.

    python tools/check_all.py            all checks that this machine can run
    python tools/check_all.py --quick    skip the KiCad-dependent selftest

Checks: version numbers agree; every Python file compiles; pyflakes (if installed);
installer syntax; the add-on's tests (fake Claude Code, no account needed); the safety,
lifecycle and editing tests (history, lock, bw_edit, router, routing plan, fab rules); the
tool server for other AI agents; the add-on build; the plugin selftest on a copy of examples/usb-sensor-test (needs KiCad 9/10);
`claude plugin validate` (if Claude Code is installed). Exit 0 when everything that
ran passed. Standard library only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# A Windows console or CI log may not be UTF-8: never crash while printing a check's output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
QUICK = "--quick" in sys.argv
results: list = []


def run(name: str, cmd: list, cwd: Path = ROOT, ok_codes=(0,), timeout: int = 900) -> bool:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        ok = p.returncode in ok_codes
        out = (p.stdout + p.stderr).strip().splitlines()
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok, out = False, [str(exc)]
    results.append((name, "ok" if ok else "FAIL"))
    print(f"[{'ok' if ok else 'FAIL'}] {name}")
    if not ok:
        print("    " + "\n    ".join(out[-15:]))
        if os.environ.get("GITHUB_ACTIONS"):
            # an annotation: readable from the run's page and the API without signing in
            print(f"::error title={name}::" + " | ".join(out[-12:]).replace("%", "%25")[:3000])
    return ok


def skip(name: str, why: str) -> None:
    results.append((name, "skipped"))
    print(f"[skip] {name}: {why}")


def check_versions() -> None:
    plugin = json.loads((ROOT / "plugin/.claude-plugin/plugin.json").read_text("utf-8"))["version"]
    addon = json.loads((ROOT / "kicad-addon/metadata.json").read_text("utf-8"))["versions"][0]["version"]
    ok = plugin == addon
    results.append(("versions agree", "ok" if ok else "FAIL"))
    print(f"[{'ok' if ok else 'FAIL'}] versions agree (plugin {plugin}, add-on {addon})")


def main() -> int:
    py = sys.executable
    check_versions()
    files = [str(p) for p in ROOT.rglob("*.py") if "dist" not in p.parts and "examples" not in p.parts]
    run("all Python files compile", [py, "-m", "py_compile", *files])
    import importlib.util
    if importlib.util.find_spec("pyflakes") is None:
        skip("pyflakes", "not installed (pip install pyflakes)")
    else:
        p = subprocess.run([py, "-m", "pyflakes", *files], capture_output=True, text=True, encoding="utf-8", errors="replace")
        # `import pcbnew` only to check that KiCad's Python is in use is deliberate
        bad = [l for l in p.stdout.splitlines() if "'pcbnew' imported but unused" not in l]
        results.append(("pyflakes", "FAIL" if bad else "ok"))
        print(f"[{'FAIL' if bad else 'ok'}] pyflakes" + ("\n    " + "\n    ".join(bad) if bad else ""))
    bash = shutil.which("bash")
    run("install.sh syntax", [bash, "-n", "install/install.sh"]) if bash else skip("install.sh syntax", "no bash")
    if os.name == "nt":
        ps = shutil.which("powershell") or shutil.which("pwsh")
        run("install.ps1 syntax", [ps, "-NoProfile", "-Command",
                                   "$null=[scriptblock]::Create((Get-Content -Raw install/install.ps1))"])
    run("add-on tests (fake Claude Code)", [py, "kicad-addon/tests/test_core.py"])
    run("safety, EMC and high-speed checks (planted faults)", [py, "plugin/tests/test_safety.py"])
    run("lifecycle check (fake LCSC answers)", [py, "plugin/tests/test_lifecycle.py"])
    run("history, lock, edits, router, routing plan, fab rules", [py, "plugin/tests/test_editing.py"])
    if not QUICK:
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="bw-mcp-")) / "usb-sensor-test"
        shutil.copytree(ROOT / "examples/usb-sensor-test", tmp, ignore=shutil.ignore_patterns("fab"))
        subprocess.run([py, str(ROOT / "plugin/scripts/init_project.py"), str(tmp), "--update-scripts"],
                       capture_output=True)
        run("tool server for other AI agents (MCP)", [py, "plugin/tests/test_mcp.py", str(tmp)])
        shutil.rmtree(tmp.parent, ignore_errors=True)
    run("add-on build", [py, "kicad-addon/build.py"])
    if QUICK:
        skip("plugin selftest on the example board", "--quick")
    else:
        sys.path.insert(0, str(ROOT / "plugin/scripts"))
        from run_gates import find_kicad_cli  # noqa: E402
        if find_kicad_cli():
            run("plugin selftest on the example board",
                [py, "plugin/scripts/selftest.py", "examples/usb-sensor-test"])
        else:
            skip("plugin selftest on the example board", "KiCad 9/10 not installed")
    claude = shutil.which("claude")
    if claude:
        run("claude plugin validate (plugin)", [claude, "plugin", "validate", "./plugin"])
        run("claude plugin validate (marketplace)", [claude, "plugin", "validate", "."])
    else:
        skip("claude plugin validate", "Claude Code not installed")
    bad = [n for n, s in results if s == "FAIL"]
    print(f"\n{len(results) - len(bad)} of {len(results)} passed or skipped" + (f"; FAILED: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
