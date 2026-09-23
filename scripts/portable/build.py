"""Builds the portable Werkbank app (DESIGN.md §6.3): one folder, zipped, that runs without
installing anything and without administrator rights.

    npm run build                     # the UI the engine serves
    uv run --project engine --group portable python scripts/portable/build.py

Output: build/portable/Werkbank-windows-x64.zip containing

    Werkbank/Werkbank.exe             the engine (PyInstaller, with Python and its packages)
    Werkbank/_internal/               ... plus apps/web/dist and tools.json
    Werkbank/bin/                     ffmpeg, ffprobe, deno, yt-dlp (pinned in programs.json)
    Werkbank/README.txt, THIRD-PARTY.txt, licences/

Every download is pinned by version and SHA-256 in programs.json; nothing is committed to git.
On Linux, `--local-programs` builds a test bundle with FFmpeg and Deno copied from PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "build" / "portable"
CACHE = ROOT / "build" / "portable-cache"
APP = "Werkbank"


def log(message: str) -> None:
    print(f"==> {message}", flush=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(entry: dict) -> Path:
    """Download once into the cache; always verify the pinned SHA-256."""
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"{entry['sha256'][:16]}-{entry['url'].rsplit('/', 1)[-1]}"
    if not target.is_file() or sha256(target) != entry["sha256"]:
        log(f"Downloading {entry['name']} {entry['version']}")
        partial = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(entry["url"], timeout=120) as resp, partial.open("wb") as fh:  # noqa: S310 - pinned https URL
            shutil.copyfileobj(resp, fh, 1 << 20)
        partial.replace(target)
    actual = sha256(target)
    if actual != entry["sha256"]:
        target.unlink()
        raise SystemExit(f"{entry['url']}: SHA-256 {actual} does not match the pinned {entry['sha256']}")
    return target


def place(entry: dict, app_dir: Path) -> None:
    archive = fetch(entry)
    if "file" in entry:
        dest = app_dir / entry["file"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive, dest)
        dest.chmod(0o755)
        return
    with zipfile.ZipFile(archive) as zf:
        for member, rel in entry["files"].items():
            dest = app_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            dest.chmod(0o755)


def copy_local_programs(app_dir: Path) -> list[dict]:
    """Test bundles on Linux: FFmpeg and Deno from PATH (not redistributed)."""
    placed = []
    for name in ("ffmpeg", "ffprobe", "deno"):
        found = shutil.which(name)
        if not found:
            raise SystemExit(f"--local-programs: {name} is not on PATH")
        dest = app_dir / "bin" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(found).resolve(), dest)
        placed.append({"name": name, "version": "local copy", "licence": "-", "source": found})
    return placed


def third_party_text(entries: list[dict]) -> str:
    lines = [
        "Programs included with Werkbank",
        "===============================",
        "",
        "Werkbank runs these programs from its bin folder. Each is unmodified and distributed",
        "under its own licence; the source code is available at the address given.",
        "",
    ]
    for e in entries:
        lines += [f"{e['name']} {e['version']}", f"  Licence: {e['licence']}", f"  Source:  {e['source']}"]
        if e.get("url"):
            lines += [f"  Binary:  {e['url']}", f"  SHA-256: {e['sha256']}"]
        lines.append("")
    lines += [
        "The engine itself bundles Python and Python packages (FastAPI, Starlette, Uvicorn, Pydantic,",
        "pikepdf with qpdf, and their dependencies) under their own open-source licences; their licence",
        "files are in _internal (look for *.dist-info folders).",
        "",
    ]
    return "\n".join(lines)


def run_pyinstaller(work: Path, dist: Path) -> None:
    web_dist = ROOT / "apps" / "web" / "dist"
    registry = ROOT / "packages" / "shared" / "dist" / "tools.json"
    if not (web_dist / "index.html").is_file():
        raise SystemExit("apps/web/dist is missing: run `npm run build` first")
    sep = os.pathsep
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onedir", "--console",
        "--name", APP,
        "--distpath", str(dist), "--workpath", str(work / "build"), "--specpath", str(work),
        "--add-data", f"{web_dist}{sep}apps/web/dist",
        "--add-data", f"{registry}{sep}packages/shared/dist",
        "--copy-metadata", "werkbank-engine",
        "--copy-metadata", "pikepdf",
        "--collect-submodules", "uvicorn",
        "--collect-submodules", "werkbank_engine",
        # The portable app runs the standalone yt-dlp from bin (it can update itself).
        "--exclude-module", "yt_dlp", "--exclude-module", "yt_dlp_ejs",
        "--exclude-module", "tkinter",
        str(HERE / "entry.py"),
    ]  # fmt: skip
    log("Packaging the engine with PyInstaller")
    subprocess.run(args, check=True, cwd=ROOT)  # noqa: S603 - fixed argument list


def build(platform: str, local_programs: bool) -> Path:
    manifest = json.loads((HERE / "programs.json").read_text(encoding="utf-8"))
    shutil.rmtree(OUT, ignore_errors=True)
    dist = OUT / "dist"
    run_pyinstaller(OUT / "work", dist)
    app_dir = dist / APP

    entries = manifest["linux-test" if local_programs else platform]
    for entry in entries:
        place(entry, app_dir)
    placed = list(entries)
    if local_programs:
        placed += copy_local_programs(app_dir)

    shutil.copyfile(HERE / "README.txt", app_dir / "README.txt")
    (app_dir / "THIRD-PARTY.txt").write_text(third_party_text(placed), encoding="utf-8")

    suffix = "windows-x64" if platform == "windows" else "linux-x64-test"
    archive = OUT / f"{APP}-{suffix}.zip"
    log(f"Writing {archive.relative_to(ROOT)}")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo.from_file(path, Path(APP) / path.relative_to(app_dir))
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as src, zf.open(info, "w") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
    size_mb = archive.stat().st_size / 1024**2
    log(f"Done: {archive} ({size_mb:.0f} MB); unpacked app in {app_dir}")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--local-programs",
        action="store_true",
        help="Linux test bundle: FFmpeg and Deno from PATH, the Linux standalone yt-dlp",
    )
    args = parser.parse_args()
    if sys.platform == "win32":
        platform = "windows"
    elif args.local_programs:
        platform = "linux"
    else:
        raise SystemExit(
            "The portable app is built on Windows; on Linux use --local-programs for a test build."
        )
    build(platform, args.local_programs)


if __name__ == "__main__":
    main()
