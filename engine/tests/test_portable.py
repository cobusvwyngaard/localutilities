"""The portable app: bundled programs win over PATH, the standalone yt-dlp is used and updated."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from tests.conftest import ALL_REQUIRED_PRESENT, FakeTools
from werkbank_engine import routes, runtime
from werkbank_engine.deps import PORTABLE_FIX, DependencyProber
from werkbank_engine.procs import ExecResult

EXE = ".exe" if sys.platform == "win32" else ""
YTDLP_VERSION_OUTPUT = "2026.08.19\n"


def make_bin(folder: Path, *names: str) -> Path:
    """Files `shutil.which` accepts as programs (the runner is faked, so they never run)."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = folder / f"{name}{EXE}"
        path.write_text("fake", encoding="utf-8")
        path.chmod(0o755)
    return folder


class BundledRunner(FakeTools):
    """Answers version queries for bundled programs by their name without the .exe suffix."""

    async def run(self, args: list[str], limit_seconds: float) -> ExecResult:
        self.calls.append(args)
        name = Path(args[0]).stem
        if name == "yt-dlp":
            return ExecResult(0, YTDLP_VERSION_OUTPUT, "")
        return ExecResult(0, self.present.get(name, ""), "")


def probe(bundled: Path, on_path: dict[str, str]) -> dict:
    fake = BundledRunner(on_path)
    prober = DependencyProber(runner=fake.run, finder=fake.find, env={}, bundled_dir=bundled)
    return {d.id: d for d in asyncio.run(prober.probe_dependencies())}


def test_bundled_programs_are_used_before_path(tmp_path: Path) -> None:
    bundled = make_bin(tmp_path / "bin", "ffmpeg", "ffprobe", "deno", "yt-dlp")
    deps = probe(bundled, ALL_REQUIRED_PRESENT)
    for dep_id in ("ffmpeg", "ffprobe", "deno", "yt-dlp"):
        assert deps[dep_id].available, dep_id
        assert Path(deps[dep_id].path).parent == bundled, dep_id


def test_standalone_ytdlp_replaces_the_python_package(tmp_path: Path) -> None:
    deps = probe(make_bin(tmp_path / "bin", "yt-dlp"), {})
    ytdlp = deps["yt-dlp"]
    assert ytdlp.version == "2026.08.19"
    assert ytdlp.detail.startswith("standalone build with yt-dlp-ejs; released ")
    assert Path(ytdlp.path).stem == "yt-dlp"


def test_missing_bundled_program_asks_for_a_fresh_download(tmp_path: Path) -> None:
    deps = probe(make_bin(tmp_path / "bin", "yt-dlp"), {})
    assert deps["ffmpeg"].available is False
    assert deps["ffmpeg"].fix == PORTABLE_FIX
    # Later-phase programs are not bundled; their own fix stays.
    assert deps["pandoc"].fix != PORTABLE_FIX


def test_without_a_bundle_the_python_package_is_used() -> None:
    fake = BundledRunner(ALL_REQUIRED_PRESENT)
    prober = DependencyProber(runner=fake.run, finder=fake.find, env={})
    deps = {d.id: d for d in asyncio.run(prober.probe_dependencies())}
    assert deps["yt-dlp"].path is None
    assert "yt-dlp-ejs" in deps["yt-dlp"].detail


def test_programs_dir(tmp_path: Path) -> None:
    assert runtime.programs_dir({"WERKBANK_BIN": str(tmp_path)}) == tmp_path
    assert runtime.programs_dir({}) is None  # tests never run frozen
    assert (runtime.resource_root() / "packages" / "shared" / "dist" / "tools.json").is_file()
    assert runtime.ytdlp_executable({"WERKBANK_BIN": str(tmp_path)}) is None
    make_bin(tmp_path, "yt-dlp")
    assert runtime.ytdlp_executable({"WERKBANK_BIN": str(tmp_path)}) == tmp_path / f"yt-dlp{EXE}"


def test_update_uses_the_standalone_self_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_bin(tmp_path, "yt-dlp")
    monkeypatch.setenv("WERKBANK_BIN", str(tmp_path))
    calls: list[list[str]] = []

    async def fake_exec(args: list[str], limit_seconds: float) -> ExecResult:
        calls.append(args)
        return ExecResult(0, "Updated yt-dlp to stable@2026.09.20\n", "")

    monkeypatch.setattr(routes, "run_exec", fake_exec)
    ok, output = asyncio.run(routes.update_ytdlp())
    assert ok
    assert calls == [[str(tmp_path / f"yt-dlp{EXE}"), "--update"]]
    assert output == "Updated yt-dlp to stable@2026.09.20"
