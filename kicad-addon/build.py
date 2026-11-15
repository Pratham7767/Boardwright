#!/usr/bin/env python3
"""Build the Boardwright KiCad add-on package (the zip that KiCad's Plugin and
Content Manager installs) and print the numbers its repository metadata needs.

    python build.py
        -> dist/boardwright-kicad-<version>.zip          install with "Install from File..."
           dist/boardwright-kicad.zip                    the same file, fixed name, for GitHub releases
           dist/metadata.repository.json                 metadata.json + download_* fields

    python build.py --download-url https://.../boardwright-kicad-0.1.0.zip
        fills download_url in dist/metadata.repository.json (for the official repository)

    python build.py --repo-url https://example.org/kicad
        also writes dist/repo/ : a self-hosted PCM repository (repository.json,
        packages.json, resources.zip, the zip) to be served from that URL.
        A file:// URL works for a local test, e.g. file://E:/some/folder

Nothing is uploaded or published by this script.  Standard library only.
Package layout and fields follow https://dev-docs.kicad.org/en/addons/ (read 2026-11-15).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent                      # pcb-pipeline: plugin/ and .claude-plugin/marketplace.json
DIST = HERE / "dist"
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".history", "*.bak")
ZIP_DATE = (2026, 1, 1, 0, 0, 0)        # fixed, so the same input gives the same SHA-256


def fail(msg: str) -> None:
    sys.exit("build failed: " + msg)


def check_metadata(meta: dict) -> dict:
    """The rules from the PCM documentation and the v2 schema that are easy to get wrong."""
    for key in ("name", "description", "description_full", "identifier", "type", "author",
                "license", "resources", "versions"):
        if key not in meta:
            fail(f"metadata.json: '{key}' is required")
    if len(meta["description"]) > 150:
        fail(f"metadata.json: description is {len(meta['description'])} characters (limit 150)")
    if len(meta["description_full"]) > 1000 * 5:
        fail("metadata.json: description_full is over 5000 characters")
    ident = meta["identifier"]
    if not re.fullmatch(r"[a-zA-Z][-a-zA-Z0-9.]{0,98}[a-zA-Z0-9]", ident) or not 2 <= len(ident) <= 50:
        fail(f"metadata.json: identifier '{ident}' is not valid (letters, digits, '-', '.', 2-50 chars)")
    if "name" not in meta["author"] or "contact" not in meta["author"]:
        fail("metadata.json: author needs 'name' and 'contact'")
    if len(meta["versions"]) != 1:
        fail("metadata.json in the archive must describe exactly one version")
    v = meta["versions"][0]
    for key in ("version", "status", "kicad_version"):
        if key not in v:
            fail(f"metadata.json: versions[0].{key} is required")
    if not re.fullmatch(r"\d{1,4}(\.\d{1,4}(\.\d{1,6})?)?", v["version"]):
        fail(f"metadata.json: version '{v['version']}' must be major[.minor[.patch]]")
    if v["status"] not in ("stable", "testing", "development", "deprecated"):
        fail("metadata.json: bad status")
    if any(k.startswith("download_") or k == "install_size" for k in v):
        fail("metadata.json inside the archive must not contain download_* / install_size")
    return v


def check_icon(path: Path, size: int) -> None:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        fail(f"{path} is not a PNG")
    w, h = struct.unpack(">II", data[16:24])
    if (w, h) != (size, size):
        fail(f"{path} is {w}x{h}, must be {size}x{size}")


def stage(meta: dict) -> Path:
    """Copy exactly what belongs in the archive into dist/stage/."""
    st = DIST / "stage"
    if st.exists():
        shutil.rmtree(st)
    shutil.copytree(HERE / "plugins", st / "plugins", ignore=SKIP)
    (st / "resources").mkdir()
    shutil.copy2(HERE / "resources" / "icon.png", st / "resources" / "icon.png")
    (st / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", "utf-8")

    # the boardwright Claude Code plugin, laid out as a local marketplace and
    # zipped: KiCad reads every plugin.json under the add-on folder and rejects
    # the whole add-on when it meets Claude Code's .claude-plugin/plugin.json.
    bundle = DIST / "bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    shutil.copytree(REPO / "plugin", bundle / "plugin", ignore=SKIP)
    (bundle / ".claude-plugin").mkdir()
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text("utf-8"))
    entry = [p for p in market["plugins"] if p["name"] == "boardwright"]
    if not entry or entry[0]["source"] != "./plugin":
        fail("../.claude-plugin/marketplace.json: expected plugin 'boardwright' with source './plugin'")
    (bundle / ".claude-plugin" / "marketplace.json").write_text(json.dumps(market, indent=2) + "\n", "utf-8")
    make_zip(bundle, st / "plugins" / "claude-plugin.zip")
    shutil.rmtree(bundle)
    extra = [p for p in (st / "plugins").rglob("plugin.json") if p != st / "plugins" / "plugin.json"]
    if extra:
        fail(f"a second plugin.json would make KiCad reject the add-on: {extra}")

    pj = json.loads((st / "plugins" / "plugin.json").read_text("utf-8"))
    for key in ("identifier", "name", "description", "runtime", "actions"):
        if key not in pj:
            fail(f"plugins/plugin.json: '{key}' is required")
    if pj["identifier"] != meta["identifier"]:
        fail("plugins/plugin.json and metadata.json have different identifiers")
    for act in pj["actions"]:
        for rel in [act["entrypoint"]] + act.get("icons-light", []) + act.get("icons-dark", []):
            if not (st / "plugins" / rel).is_file():
                fail(f"plugins/plugin.json points to a missing file: {rel}")
    reqs = st / "plugins" / "requirements.txt"
    if not reqs.is_file():
        fail("plugins/requirements.txt is required: KiCad 10 marks a Python plugin ready only after "
             "'pip install -r requirements.txt' succeeds")
    if any(l.strip() and not l.lstrip().startswith("#") for l in reqs.read_text("utf-8").splitlines()):
        fail("plugins/requirements.txt must list no packages: KiCad 10.0.8's pip step hangs when the "
             "KiCad documents path is not ASCII (pip floods an unread stderr pipe)")
    check_icon(st / "resources" / "icon.png", 64)
    check_icon(st / "plugins" / "icons" / "chat-24.png", 24)
    return st


def make_zip(src: Path, dest: Path) -> int:
    """Deterministic zip. -> uncompressed size in bytes."""
    total = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f.relative_to(src).as_posix(), ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            data = f.read_bytes()
            total += len(data)
            z.writestr(info, data)
    return total


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_repo(repo_url: str, meta_repo: dict, zip_path: Path) -> Path:
    """A self-hosted PCM repository: three small files plus the package."""
    repo_url = repo_url.rstrip("/")
    out = DIST / "repo"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy2(zip_path, out / zip_path.name)
    meta = json.loads(json.dumps(meta_repo))
    meta["versions"][0]["download_url"] = f"{repo_url}/{zip_path.name}"
    (out / "packages.json").write_text(json.dumps({"packages": [meta]}, indent=2, ensure_ascii=False) + "\n", "utf-8")
    with zipfile.ZipFile(out / "resources.zip", "w", zipfile.ZIP_DEFLATED) as z:     # icons shown in the list
        z.writestr(zipfile.ZipInfo(f"{meta['identifier']}/icon.png", ZIP_DATE),
                   (HERE / "resources" / "icon.png").read_bytes())
    now = int(time.time())
    stamp = {"update_timestamp": now,
             "update_time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))}
    repo = {
        "schema_version": 2,
        "name": "Boardwright repository",
        "maintainer": meta["author"],
        "packages": {"url": f"{repo_url}/packages.json", "sha256": sha256(out / "packages.json"), **stamp},
        "resources": {"url": f"{repo_url}/resources.zip", "sha256": sha256(out / "resources.zip"), **stamp},
    }
    (out / "repository.json").write_text(json.dumps(repo, indent=2) + "\n", "utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--download-url", help="public URL the zip will be downloaded from")
    ap.add_argument("--repo-url", help="base URL of a self-hosted PCM repository to generate in dist/repo/")
    a = ap.parse_args()

    meta = json.loads((HERE / "metadata.json").read_text("utf-8"))
    ver = check_metadata(meta)
    DIST.mkdir(exist_ok=True)
    st = stage(meta)
    zip_path = DIST / f"boardwright-kicad-{ver['version']}.zip"
    install_size = make_zip(st, zip_path)
    shutil.rmtree(st)
    shutil.copy2(zip_path, DIST / "boardwright-kicad.zip")   # fixed name for releases/latest/download/
    digest, size = sha256(zip_path), zip_path.stat().st_size

    meta_repo = json.loads(json.dumps(meta))
    meta_repo["versions"][0].update({
        "download_sha256": digest,
        "download_size": size,
        "download_url": a.download_url or "REPLACE-WITH-THE-PUBLIC-URL-OF-THE-ZIP",
        "install_size": install_size,
    })
    (DIST / "metadata.repository.json").write_text(
        json.dumps(meta_repo, indent=2, ensure_ascii=False) + "\n", "utf-8")

    print(f"package          {zip_path}")
    print(f"identifier       {meta['identifier']}")
    print(f"version          {ver['version']} ({ver['status']}, KiCad >= {ver['kicad_version']}, "
          f"runtime {ver.get('runtime', 'swig')})")
    print(f"download_sha256  {digest}")
    print(f"download_size    {size} bytes")
    print(f"install_size     {install_size} bytes")
    print(f"repository metadata  {DIST / 'metadata.repository.json'}")
    if not a.download_url:
        print("  (download_url is a placeholder until the zip has a public address)")
    if not meta["author"]["contact"] or not meta["resources"]:
        print("note: author.contact / resources are empty. Fine for 'Install from File...'; the official\n"
              "      repository needs a public source page with an issue tracker there.")
    if a.repo_url:
        out = write_repo(a.repo_url, meta_repo, zip_path)
        print(f"self-hosted repository  {out}")
        print(f"  serve this folder at {a.repo_url.rstrip('/')}/ ; users add "
              f"{a.repo_url.rstrip('/')}/repository.json under 'Manage...'")


if __name__ == "__main__":
    main()
