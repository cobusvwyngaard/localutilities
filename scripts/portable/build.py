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
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

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


def download(url: str, dst: Path) -> None:
    """Stream to `dst`; a transfer that ends early (fewer bytes than announced) is an error."""
    partial = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, partial.open("wb") as fh:  # noqa: S310 - pinned https URL
        expected = int(resp.headers.get("Content-Length") or -1)
        shutil.copyfileobj(resp, fh, 1 << 20)
    received = partial.stat().st_size
    if expected >= 0 and received != expected:
        partial.unlink()
        raise OSError(f"transfer cut off after {received} of {expected} bytes")
    partial.replace(dst)


def fetch(entry: dict, attempts: int = 3) -> Path:
    """Download once into the cache (retrying cut-off transfers); always verify the pinned SHA-256."""
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / f"{entry['sha256'][:16]}-{entry['url'].rsplit('/', 1)[-1]}"
    for attempt in range(1, attempts + 1):
        if not target.is_file():
            log(f"Downloading {entry['name']} {entry['version']}")
            try:
                download(entry["url"], target)
            except OSError as exc:
                if attempt == attempts:
                    raise SystemExit(f"{entry['url']}: {exc}") from None
                log(f"  {exc}; trying again")
                continue
        actual = sha256(target)
        if actual == entry["sha256"]:
            return target
        target.unlink()
        if attempt == attempts:
            raise SystemExit(f"{entry['url']}: SHA-256 {actual} does not match the pinned {entry['sha256']}")
        log("  checksum mismatch; downloading again")
    raise AssertionError("unreachable")


def seven_zip() -> str:
    for candidate in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe"):
        if candidate and Path(candidate).is_file():
            return candidate
    raise SystemExit("7-Zip (7z) is needed to unpack the Tesseract installer without running it.")


def copy_member(read: Callable[[], BinaryIO], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with read() as src, dest.open("wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)
    dest.chmod(0o755)


def place(entry: dict, app_dir: Path) -> None:
    """Copy a pinned download (or chosen files from inside it) into the app folder.
    `files` keys are paths inside the archive; "folder/*" copies every file in that folder."""
    archive = fetch(entry)
    if "file" in entry:
        copy_member(lambda: archive.open("rb"), app_dir / entry["file"])
        return
    if entry.get("archive") == "7z":  # e.g. an NSIS installer: unpacked, never run
        unpacked = CACHE / f"{entry['sha256'][:16]}-unpacked"
        if not unpacked.is_dir():
            partial = unpacked.with_name(unpacked.name + ".part")
            shutil.rmtree(partial, ignore_errors=True)
            subprocess.run(  # noqa: S603 - fixed argument list; the archive is SHA-256 checked
                [seven_zip(), "x", "-y", f"-o{partial}", str(archive)], check=True, stdout=subprocess.DEVNULL
            )
            partial.rename(unpacked)
        members = {p.relative_to(unpacked).as_posix(): p for p in unpacked.rglob("*") if p.is_file()}
        opener = {name: (lambda p=path: p.open("rb")) for name, path in members.items()}
    else:
        zf = zipfile.ZipFile(archive)
        opener = {
            info.filename: (lambda n=info.filename: zf.open(n)) for info in zf.infolist() if not info.is_dir()
        }
    for member, rel in entry["files"].items():
        if member.endswith("/*"):
            folder = member[:-1]
            matches = [name for name in opener if name.startswith(folder) and "/" not in name[len(folder) :]]
            if not matches:
                raise SystemExit(f"{entry['name']}: nothing matches {member}")
            for name in matches:
                copy_member(opener[name], app_dir / rel / name[len(folder) :])
        elif member in opener:
            copy_member(opener[member], app_dir / rel)
        else:
            raise SystemExit(f"{entry['name']}: {member} is not in the download")


# Windows' own DLLs: a bundled program may import these; anything else must be in the bundle.
WINDOWS_DLLS = frozenset(
    name.lower()
    for name in [
        "advapi32.dll",
        "avicap32.dll",
        "avrt.dll",
        "bcrypt.dll",
        "bcryptprimitives.dll",
        "cfgmgr32.dll",
        "comctl32.dll",
        "comdlg32.dll",
        "crypt32.dll",
        "d3d11.dll",
        "d3d12.dll",
        "dbghelp.dll",
        "dwmapi.dll",
        "dxgi.dll",
        "gdi32.dll",
        "imm32.dll",
        "iphlpapi.dll",
        "kernel32.dll",
        "mf.dll",
        "mfplat.dll",
        "mfreadwrite.dll",
        "msimg32.dll",
        "msvcrt.dll",
        "ncrypt.dll",
        "ntdll.dll",
        "ole32.dll",
        "oleaut32.dll",
        "opengl32.dll",
        "powrprof.dll",
        "psapi.dll",
        "secur32.dll",
        "setupapi.dll",
        "shell32.dll",
        "shlwapi.dll",
        "ucrtbase.dll",
        "user32.dll",
        "userenv.dll",
        "uxtheme.dll",
        "version.dll",
        "winmm.dll",
        "winspool.drv",
        "ws2_32.dll",
        "wsock32.dll",
    ]
)


def check_windows_imports(bin_dir: Path) -> None:
    """Fail the build if a bundled program needs a DLL that is neither next to it nor part of
    Windows (e.g. the Visual C++ runtime, which a clean Windows 11 may not have)."""
    import pefile

    problems = []
    for binary in sorted([*bin_dir.rglob("*.exe"), *bin_dir.rglob("*.dll")]):
        pe = pefile.PE(str(binary), fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        local = {p.name.lower() for p in binary.parent.iterdir()}
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            name = entry.dll.decode().lower()
            if name in local or name in WINDOWS_DLLS or name.startswith(("api-ms-win-", "ext-ms-win-")):
                continue
            problems.append(f"{binary.relative_to(bin_dir)} needs {name}")
        pe.close()
    if problems:
        raise SystemExit("Bundled programs need DLLs that are not bundled:\n  " + "\n  ".join(problems))
    log("Every DLL the bundled programs import is bundled or part of Windows")


def copy_local_programs(app_dir: Path) -> list[dict]:
    """Test bundles on Linux: FFmpeg, Deno, whisper-cli and Tesseract from PATH (not redistributed)."""
    placed = []
    for name, folder in (
        ("ffmpeg", ""),
        ("ffprobe", ""),
        ("deno", ""),
        ("whisper-cli", "whisper"),
        ("tesseract", "tesseract"),
    ):
        found = shutil.which(name)
        if not found:
            raise SystemExit(f"--local-programs: {name} is not on PATH")
        dest = app_dir / "bin" / folder / name
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
        # Libraries that load data files or native libraries at run time.
        "--collect-all", "pypdfium2", "--collect-all", "pypdfium2_raw",
        "--collect-data", "reportlab", "--collect-data", "pdfminer",
        "--collect-all", "pyhanko", "--collect-all", "pyhanko_certvalidator",
        "--copy-metadata", "pyhanko",
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
    else:
        check_windows_imports(app_dir / "bin")

    shutil.copyfile(HERE / "README.txt", app_dir / "README.txt")
    (app_dir / "THIRD-PARTY.txt").write_text(third_party_text(placed), encoding="utf-8")

    suffix = "windows-x64" if platform == "windows" else "linux-x64-test"
    archive = OUT / f"{APP}-{suffix}.zip"
    log(f"Writing {archive.relative_to(ROOT)}")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo.from_file(path, Path(APP) / path.relative_to(app_dir))
                # Speech models are already dense: storing them saves minutes and costs nothing.
                info.compress_type = zipfile.ZIP_STORED if path.suffix == ".bin" else zipfile.ZIP_DEFLATED
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
