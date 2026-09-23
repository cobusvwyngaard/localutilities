"""Detection of the external programs and Python packages the tools depend on (DESIGN.md §6.3).

Every dependency id here must match `dependencyIds` in packages/shared (a test enforces it), so
the UI can disable a tool whose dependency is missing and show the fix-it command below.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from werkbank_engine.procs import ExecResult, ProcessError, run_exec

Platform = str  # "windows" | "darwin" | "linux"


def current_platform() -> Platform:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


@dataclass(frozen=True)
class ProgramSpec:
    id: str
    name: str
    required: bool
    needed_for: str
    executables: dict[Platform, tuple[str, ...]]
    version_args: tuple[str, ...]
    version_pattern: str
    fix: dict[Platform, str]


_REINSTALL = {
    "windows": r"Re-run scripts\install.ps1",
    "darwin": "Re-run scripts/install.sh",
    "linux": "Re-run scripts/install.sh",
}

PROGRAMS: tuple[ProgramSpec, ...] = (
    ProgramSpec(
        id="ffmpeg",
        name="FFmpeg",
        required=True,
        needed_for="All audio and video tools",
        executables={"windows": ("ffmpeg",), "darwin": ("ffmpeg",), "linux": ("ffmpeg",)},
        version_args=("-hide_banner", "-version"),
        version_pattern=r"ffmpeg version (\S+)",
        fix={
            "windows": "winget install --id Gyan.FFmpeg -e",
            "darwin": "brew install ffmpeg",
            "linux": "sudo apt install ffmpeg",
        },
    ),
    ProgramSpec(
        id="ffprobe",
        name="FFprobe",
        required=True,
        needed_for="Reading media duration and streams (ships with FFmpeg)",
        executables={"windows": ("ffprobe",), "darwin": ("ffprobe",), "linux": ("ffprobe",)},
        version_args=("-hide_banner", "-version"),
        version_pattern=r"ffprobe version (\S+)",
        fix={
            "windows": "winget install --id Gyan.FFmpeg -e",
            "darwin": "brew install ffmpeg",
            "linux": "sudo apt install ffmpeg",
        },
    ),
    ProgramSpec(
        id="deno",
        name="Deno",
        required=True,
        needed_for="YouTube downloads (yt-dlp needs a JavaScript runtime)",
        executables={"windows": ("deno",), "darwin": ("deno",), "linux": ("deno",)},
        version_args=("--version",),
        version_pattern=r"(?m)^deno (\S+)",
        fix={
            "windows": "winget install --id DenoLand.Deno -e",
            "darwin": "brew install deno",
            "linux": "curl -fsSL https://deno.land/install.sh | sh",
        },
    ),
    ProgramSpec(
        id="ghostscript",
        name="Ghostscript",
        required=False,
        needed_for="PDF compression (phase 2)",
        executables={"windows": ("gswin64c", "gswin32c"), "darwin": ("gs",), "linux": ("gs",)},
        version_args=("--version",),
        version_pattern=r"(?m)^(\d+\.\d+(?:\.\d+)?)",
        fix={
            "windows": "winget install --id ArtifexSoftware.GhostScript -e",
            "darwin": "brew install ghostscript",
            "linux": "sudo apt install ghostscript",
        },
    ),
    ProgramSpec(
        id="tesseract",
        name="Tesseract OCR",
        required=False,
        needed_for="OCR of scanned PDFs (phase 3)",
        executables={"windows": ("tesseract",), "darwin": ("tesseract",), "linux": ("tesseract",)},
        version_args=("--version",),
        version_pattern=r"tesseract v?(\d+\.\d+(?:\.\d+)?)",
        fix={
            "windows": "winget install --id UB-Mannheim.TesseractOCR -e",
            "darwin": "brew install tesseract tesseract-lang",
            "linux": "sudo apt install tesseract-ocr tesseract-ocr-afr",
        },
    ),
    ProgramSpec(
        id="libreoffice",
        name="LibreOffice",
        required=False,
        needed_for="Office documents to PDF (phase 3)",
        executables={"windows": ("soffice.com", "soffice"), "darwin": ("soffice",), "linux": ("soffice",)},
        version_args=("--version",),
        version_pattern=r"LibreOffice (\d+(?:\.\d+)+)",
        fix={
            "windows": "winget install --id TheDocumentFoundation.LibreOffice -e",
            "darwin": "brew install --cask libreoffice",
            "linux": "sudo apt install libreoffice-core",
        },
    ),
    ProgramSpec(
        id="pandoc",
        name="Pandoc",
        required=False,
        needed_for="Markdown to DOCX/PDF with citations (phase 3)",
        executables={"windows": ("pandoc",), "darwin": ("pandoc",), "linux": ("pandoc",)},
        version_args=("--version",),
        version_pattern=r"(?m)^pandoc(?:\.exe)? (\S+)",
        fix={
            "windows": "winget install --id JohnMacFarlane.Pandoc -e",
            "darwin": "brew install pandoc",
            "linux": "sudo apt install pandoc",
        },
    ),
    ProgramSpec(
        id="calibre",
        name="Calibre",
        required=False,
        needed_for="E-book conversion (phase 4)",
        executables={
            "windows": ("ebook-convert",),
            "darwin": ("ebook-convert",),
            "linux": ("ebook-convert",),
        },
        version_args=("--version",),
        version_pattern=r"calibre (\d+(?:\.\d+)+)",
        fix={
            "windows": "winget install --id calibre.calibre -e",
            "darwin": "brew install --cask calibre",
            "linux": "sudo apt install calibre",
        },
    ),
)

PYTHON_PACKAGES = (
    ("yt-dlp", "yt-dlp", "Media downloader"),
    ("pikepdf", "pikepdf", "PDF unlock and page tools"),
)

ALL_DEPENDENCY_IDS = tuple(p.id for p in PROGRAMS) + tuple(p[0] for p in PYTHON_PACKAGES)

# Hardware video encoders worth offering as "Fast (hardware)" (DESIGN.md §5.2).
HARDWARE_ENCODERS = (
    "h264_nvenc",
    "hevc_nvenc",
    "av1_nvenc",
    "h264_qsv",
    "hevc_qsv",
    "av1_qsv",
    "h264_amf",
    "hevc_amf",
    "av1_amf",
    "h264_videotoolbox",
    "hevc_videotoolbox",
)


@dataclass
class DependencyResult:
    id: str
    name: str
    required: bool
    needed_for: str
    available: bool
    version: str | None = None
    path: str | None = None
    fix: str | None = None
    detail: str | None = None


@dataclass
class EncoderResult:
    listed: list[str] = field(default_factory=list)
    usable: list[str] = field(default_factory=list)


Runner = Callable[[list[str], float], Awaitable[ExecResult]]


def _windows_registry_path_dirs() -> list[Path]:
    """PATH as stored for new processes; the engine's own PATH may predate a winget install."""
    if sys.platform != "win32":
        return []
    import winreg

    keys = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    )
    dirs: list[Path] = []
    for root, sub_key in keys:
        try:
            with winreg.OpenKey(root, sub_key) as key:
                value, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            continue
        dirs += [Path(p) for p in os.path.expandvars(str(value)).split(";") if p]
    return dirs


def extra_search_dirs(platform: Platform, env: Mapping[str, str] = os.environ) -> list[Path]:
    """Well-known install locations that may be missing from PATH (e.g. right after winget)."""
    home = Path.home()
    dirs: list[Path] = []
    if platform == "windows":
        program_files = Path(env.get("ProgramFiles", r"C:\Program Files"))
        if env.get("LOCALAPPDATA"):
            dirs.append(Path(env["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links")
        dirs += [
            home / ".deno" / "bin",
            program_files / "LibreOffice" / "program",
            program_files / "Calibre2",
            program_files / "Tesseract-OCR",
            program_files / "Pandoc",
        ]
        dirs += sorted(program_files.glob("gs/gs*/bin"), reverse=True)
        dirs += _windows_registry_path_dirs()
    elif platform == "darwin":
        dirs += [
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            home / ".deno" / "bin",
            Path("/Applications/LibreOffice.app/Contents/MacOS"),
            Path("/Applications/calibre.app/Contents/MacOS"),
        ]
    else:
        dirs += [home / ".deno" / "bin", home / ".local" / "bin"]
    return dirs


def find_program(names: tuple[str, ...], extra_dirs: list[Path]) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    extra = os.pathsep.join(str(d) for d in extra_dirs if d.is_dir())
    if extra:
        for name in names:
            found = shutil.which(name, path=extra)
            if found:
                return found
    return None


def parse_version(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def parse_listed_encoders(encoders_output: str) -> list[str]:
    """Names from `ffmpeg -encoders` that are in HARDWARE_ENCODERS, in that order."""
    names = set()
    for line in encoders_output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V"):
            names.add(parts[1])
    return [e for e in HARDWARE_ENCODERS if e in names]


def ytdlp_age_days(ytdlp_version: str, today: date | None = None) -> int | None:
    """yt-dlp versions are release dates (2026.08.19 or 2026.8.19)."""
    match = re.match(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})", ytdlp_version)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        released = date(year, month, day)
    except ValueError:
        return None
    return ((today or date.today()) - released).days


class DependencyProber:
    def __init__(
        self,
        platform: Platform | None = None,
        runner: Runner | None = None,
        finder: Callable[[tuple[str, ...], list[Path]], str | None] = find_program,
        env: Mapping[str, str] = os.environ,
    ) -> None:
        self.platform = platform or current_platform()
        self._run: Runner = runner or (lambda args, limit: run_exec(args, limit))
        self._find = finder
        self._extra_dirs = extra_search_dirs(self.platform, env)

    async def probe_program(self, spec: ProgramSpec) -> DependencyResult:
        result = DependencyResult(
            id=spec.id,
            name=spec.name,
            required=spec.required,
            needed_for=spec.needed_for,
            available=False,
        )
        path = self._find(spec.executables[self.platform], self._extra_dirs)
        if path is None:
            result.fix = spec.fix[self.platform]
            result.detail = "Not found on PATH"
            return result
        result.path = path
        try:
            out = await self._run([path, *spec.version_args], 30.0)
        except ProcessError as exc:
            result.fix = spec.fix[self.platform]
            result.detail = f"Found but could not run: {exc}"
            return result
        text = out.stdout + "\n" + out.stderr
        result.version = parse_version(spec.version_pattern, text)
        if out.returncode != 0 and result.version is None:
            result.fix = spec.fix[self.platform]
            result.detail = f"Found but '{' '.join(spec.version_args)}' exited with code {out.returncode}"
            return result
        result.available = True
        return result

    def probe_python_packages(self) -> list[DependencyResult]:
        results = []
        for dep_id, dist, needed_for in PYTHON_PACKAGES:
            res = DependencyResult(
                id=dep_id, name=dist, required=True, needed_for=needed_for, available=False
            )
            try:
                res.version = version(dist)
                res.available = True
            except PackageNotFoundError:
                res.fix = _REINSTALL[self.platform]
                res.detail = "Python package not installed in the engine environment"
            if res.available and dep_id == "yt-dlp" and res.version:
                age = ytdlp_age_days(res.version)
                try:
                    ejs = version("yt-dlp-ejs")
                except PackageNotFoundError:
                    ejs = None
                notes = [f"yt-dlp-ejs {ejs}" if ejs else "yt-dlp-ejs missing (YouTube will not work)"]
                if age is not None:
                    notes.append(f"released {age} days ago")
                res.detail = "; ".join(notes)
            if res.available and dep_id == "pikepdf":
                import pikepdf  # heavy import, only when probing

                res.detail = f"qpdf {pikepdf.__libqpdf_version__}"
            results.append(res)
        return results

    async def probe_encoders(self, ffmpeg_path: str) -> EncoderResult:
        try:
            out = await self._run([ffmpeg_path, "-hide_banner", "-encoders"], 30.0)
        except ProcessError:
            return EncoderResult()
        listed = parse_listed_encoders(out.stdout)
        usable = []
        for enc in listed:  # sequentially: they may share one GPU
            args = [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=256x256:r=30:d=0.2",
                "-frames:v",
                "3",
                "-c:v",
                enc,
                "-f",
                "null",
                "-",
            ]
            try:
                test = await self._run(args, 20.0)
            except ProcessError:
                continue
            if test.returncode == 0:
                usable.append(enc)
        return EncoderResult(listed=listed, usable=usable)

    async def probe_all(self) -> tuple[list[DependencyResult], EncoderResult]:
        programs = await asyncio.gather(*(self.probe_program(spec) for spec in PROGRAMS))
        by_id = {r.id: r for r in programs}
        ffmpeg = by_id["ffmpeg"]
        encoders = (
            await self.probe_encoders(ffmpeg.path) if ffmpeg.available and ffmpeg.path else EncoderResult()
        )
        packages = self.probe_python_packages()
        ordered = sorted([*programs, *packages], key=lambda r: not r.required)  # required first, stable
        return ordered, encoders
