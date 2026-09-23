"""Uploaded files, the Inbox and output naming (DESIGN.md §3.3).

The client never supplies filesystem paths: it gets file IDs for uploads and Inbox-relative
names, and both are resolved here with containment checks.
"""

from __future__ import annotations

import re
import secrets
import shutil
import time
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SWEEP_AGE_SECONDS = 24 * 3600
MAX_INBOX_ENTRIES = 1000
MAX_INBOX_DEPTH = 3

_WINDOWS_RESERVED = (
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class FileError(ValueError):
    """A client reference to a file is invalid; the message is safe to show."""


def safe_filename(name: str, fallback: str = "file", max_length: int = 150) -> str:
    """A file name that is valid on Windows, macOS and Linux (no folders, no reserved names)."""
    name = unicodedata.normalize("NFC", name).replace("\\", "/").split("/")[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip().rstrip(". ")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.upper() in _WINDOWS_RESERVED or not stem:
        stem = f"{stem or fallback}_"
    ext = ext[:16]
    stem = stem[: max(1, max_length - len(ext) - 1)]
    return f"{stem}.{ext}" if ext else stem


def unique_path(folder: Path, filename: str) -> Path:
    """`folder/filename`, or `name (2).ext`, `name (3).ext`... so nothing is ever overwritten."""
    candidate = folder / filename
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def output_name(source_name: str, label: str | None, extension: str) -> str:
    """`<original stem> (<label>).<ext>` (DESIGN.md §3.3)."""
    stem = Path(safe_filename(source_name)).stem
    return safe_filename(f"{stem} ({label}){extension}" if label else f"{stem}{extension}")


@dataclass(frozen=True)
class StoredFile:
    id: str
    name: str
    path: Path
    size: int


class FileStore:
    """Uploads kept under `<work>/uploads/<id>/<name>` until the 24-hour sweep."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[str, StoredFile] = {}

    async def save(self, name: str, chunks: AsyncIterator[bytes]) -> StoredFile:
        file_id = secrets.token_urlsafe(12)
        folder = self.root / file_id
        folder.mkdir(parents=True)
        safe = safe_filename(name)
        path = folder / safe
        size = 0
        try:
            with path.open("wb") as fh:
                async for chunk in chunks:
                    fh.write(chunk)
                    size += len(chunk)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        stored = StoredFile(id=file_id, name=safe, path=path, size=size)
        self._files[file_id] = stored
        return stored

    def get(self, file_id: str) -> StoredFile:
        stored = self._files.get(file_id)
        if stored is None or not stored.path.is_file():
            raise FileError("Unknown or expired file. Add it again.")
        return stored


def _inbox_name_parts(name: str) -> tuple[str, ...]:
    if not name or len(name) > 1000 or "\\" in name or "\x00" in name or ":" in name:
        raise FileError("Invalid Inbox file name.")
    posix = PurePosixPath(name)
    if posix.is_absolute() or any(part in ("", ".", "..") for part in posix.parts):
        raise FileError("Invalid Inbox file name.")
    return posix.parts


def resolve_inbox(inbox: Path, name: str) -> Path:
    """Resolve an Inbox-relative name (forward slashes) to a file that is inside the Inbox."""
    parts = _inbox_name_parts(name)
    root = inbox.resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise FileError(f"'{name}' is not in the Inbox.")
    return path


def list_inbox(inbox: Path) -> list[dict]:
    root = inbox.resolve()
    entries: list[dict] = []
    if not root.is_dir():
        return entries

    def walk(folder: Path, depth: int) -> None:
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for child in children:
            if len(entries) >= MAX_INBOX_ENTRIES or child.name.startswith("."):
                continue
            if child.is_symlink():
                continue  # never follow links out of the Inbox
            if child.is_dir() and depth < MAX_INBOX_DEPTH:
                walk(child, depth + 1)
            elif child.is_file():
                stat = child.stat()
                entries.append(
                    {
                        "name": child.relative_to(root).as_posix(),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )

    walk(root, 1)
    return entries


def sweep(folder: Path, max_age_seconds: float = SWEEP_AGE_SECONDS) -> int:
    """Delete entries in `folder` older than `max_age_seconds`; returns how many were removed."""
    if not folder.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for child in folder.iterdir():
        try:
            if child.stat().st_mtime < cutoff:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed
