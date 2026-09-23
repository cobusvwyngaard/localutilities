from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from werkbank_engine.files import (
    FileError,
    list_inbox,
    output_name,
    resolve_inbox,
    safe_filename,
    sweep,
    unique_path,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lecture.mp4", "lecture.mp4"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\evil.exe", "evil.exe"),
        ('a<b>c:"d|e?f*.mp4', "a_b_c__d_e_f_.mp4"),
        ("CON.txt", "CON_.txt"),
        ("nul", "nul_"),
        ("trailing dots... ", "trailing dots"),
        ("", "file_"),
        ("Afrikaans ê ô.mp3", "Afrikaans ê ô.mp3"),
    ],
)
def test_safe_filename(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


def test_outputs_never_overwrite(tmp_path: Path) -> None:
    (tmp_path / "clip (compressed).mp4").write_text("1")
    (tmp_path / "clip (compressed) (2).mp4").write_text("2")
    assert unique_path(tmp_path, "clip (compressed).mp4").name == "clip (compressed) (3).mp4"
    assert unique_path(tmp_path, "new.mp4").name == "new.mp4"


def test_output_name() -> None:
    assert output_name("My lecture.mkv", "compressed", ".mp4") == "My lecture (compressed).mp4"
    assert output_name("x.pdf", None, ".pdf") == "x.pdf"


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    root = tmp_path / "Inbox"
    (root / "sub").mkdir(parents=True)
    (root / "a.mp4").write_text("a")
    (root / "sub" / "b.mp3").write_text("b")
    (root / ".hidden").write_text("h")
    (tmp_path / "secret.txt").write_text("outside the inbox")
    return root


def test_list_inbox(inbox: Path) -> None:
    assert [e["name"] for e in list_inbox(inbox)] == ["a.mp4", "sub/b.mp3"]


def test_resolve_inbox(inbox: Path) -> None:
    assert resolve_inbox(inbox, "sub/b.mp3") == (inbox / "sub" / "b.mp3").resolve()


@pytest.mark.parametrize(
    "name",
    ["../secret.txt", "sub/../../secret.txt", "/etc/passwd", "C:/x", "sub\\b.mp3", "", ".", "missing.mp4"],
)
def test_resolve_inbox_rejects_escapes(inbox: Path, name: str) -> None:
    with pytest.raises(FileError):
        resolve_inbox(inbox, name)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinks_out_of_the_inbox_are_refused(inbox: Path) -> None:
    (inbox / "link.txt").symlink_to(inbox.parent / "secret.txt")
    with pytest.raises(FileError):
        resolve_inbox(inbox, "link.txt")
    assert "link.txt" not in [e["name"] for e in list_inbox(inbox)]


def test_sweep_removes_only_old_entries(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    assert sweep(tmp_path) == 1
    assert not old.exists() and new.exists()
