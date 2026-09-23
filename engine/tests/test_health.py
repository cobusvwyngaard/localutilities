from __future__ import annotations

import asyncio
import shutil
from datetime import date

import pytest
from starlette.testclient import TestClient

from tests.conftest import ALL_REQUIRED_PRESENT, FakeTools, make_prober
from werkbank_engine.config import Settings
from werkbank_engine.deps import (
    ALL_DEPENDENCY_IDS,
    PROGRAMS,
    DependencyProber,
    parse_listed_encoders,
    parse_version,
    ytdlp_age_days,
)
from werkbank_engine.health import HealthService


def test_health_reports_versions_encoders_and_disk(client: TestClient, auth: dict[str, str]) -> None:
    body = client.get("/api/health", headers=auth).json()
    assert body["status"] == "ok"
    assert body["engine"]["version"]
    deps = {d["id"]: d for d in body["dependencies"]}
    assert deps["ffmpeg"]["available"] is True
    assert deps["ffmpeg"]["version"] == "7.1.1-full_build-www.gyan.dev"
    assert deps["deno"]["version"] == "2.9.6"
    assert deps["yt-dlp"]["available"] is True
    assert deps["pikepdf"]["detail"].startswith("qpdf ")
    assert deps["ghostscript"]["available"] is False
    assert deps["ghostscript"]["required"] is False
    assert deps["ghostscript"]["fix"] == "winget install --id ArtifexSoftware.GhostScript -e"
    assert body["hardwareEncoders"] == {
        "listed": ["h264_nvenc", "h264_qsv", "h264_amf"],
        "usable": ["h264_nvenc"],
    }
    assert body["disk"]["freeBytes"] > 0
    assert body["tools"] == 1
    # required dependencies come first
    required_flags = [d["required"] for d in body["dependencies"]]
    assert required_flags == sorted(required_flags, reverse=True)


def test_missing_required_dependency_degrades_status(settings: Settings) -> None:
    fake = FakeTools({k: v for k, v in ALL_REQUIRED_PRESENT.items() if k != "deno"})
    service = HealthService(settings, tool_count=0, prober=make_prober(fake))
    report = asyncio.run(service.report())
    assert report.status == "degraded"
    deno = next(d for d in report.dependencies if d.id == "deno")
    assert deno.available is False
    assert deno.fix == "winget install --id DenoLand.Deno -e"
    assert report.hardware_encoders.listed  # ffmpeg is still there


def test_no_ffmpeg_means_no_encoder_probing(settings: Settings) -> None:
    fake = FakeTools({"deno": ALL_REQUIRED_PRESENT["deno"]})
    report = asyncio.run(HealthService(settings, tool_count=0, prober=make_prober(fake)).report())
    assert report.hardware_encoders.listed == []
    assert not any("-encoders" in call for call in fake.calls)


def test_results_are_cached_until_refresh(settings: Settings) -> None:
    fake = FakeTools(dict(ALL_REQUIRED_PRESENT))
    service = HealthService(settings, tool_count=0, prober=make_prober(fake))

    async def scenario() -> tuple[int, int, int]:
        await service.report()
        first = len(fake.calls)
        await service.report()
        second = len(fake.calls)
        await service.report(refresh=True)
        return first, second, len(fake.calls)

    first, second, third = asyncio.run(scenario())
    assert first > 0
    assert second == first
    assert third > second


def test_dependency_ids_match_the_shared_registry(client: TestClient) -> None:
    assert sorted(client.app.state.registry.dependencyIds) == sorted(ALL_DEPENDENCY_IDS)


def test_every_program_has_a_fix_for_every_platform() -> None:
    for spec in PROGRAMS:
        assert set(spec.fix) == {"windows", "darwin", "linux"}, spec.id
        assert set(spec.executables) == {"windows", "darwin", "linux"}, spec.id


@pytest.mark.parametrize(
    ("dep_id", "output", "expected"),
    [
        ("ffmpeg", "ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023", "6.1.1-3ubuntu5"),
        ("ffmpeg", "ffmpeg version n7.1 Copyright (c) 2000-2024 the FFmpeg developers", "n7.1"),
        ("deno", "deno 2.9.6 (stable, release, aarch64-apple-darwin)\nv8 14.0", "2.9.6"),
        ("ghostscript", "10.05.1\n", "10.05.1"),
        ("tesseract", "tesseract v5.5.0.20241111\n leptonica-1.85.0", "5.5.0"),
        ("tesseract", "tesseract 5.3.4\n leptonica-1.82.0", "5.3.4"),
        ("libreoffice", "LibreOffice 25.2.3.2 bbb074479178df812d175f709636b368952c2ce3", "25.2.3.2"),
        ("pandoc", "pandoc 3.6.2\nFeatures: +server +lua", "3.6.2"),
        ("pandoc", "pandoc.exe 3.6.2\nFeatures: +server +lua", "3.6.2"),
        ("calibre", "ebook-convert.exe (calibre 8.4.0)\nCreated by: Kovid Goyal", "8.4.0"),
    ],
)
def test_version_parsing(dep_id: str, output: str, expected: str) -> None:
    spec = next(p for p in PROGRAMS if p.id == dep_id)
    assert parse_version(spec.version_pattern, output) == expected


def test_parse_listed_encoders_ignores_audio_and_software() -> None:
    out = " V....D libx264  x\n V....D hevc_nvenc  y\n A....D h264_nvenc fake-audio-line\n"
    assert parse_listed_encoders(out) == ["hevc_nvenc"]


def test_ytdlp_age() -> None:
    assert ytdlp_age_days("2026.08.19", today=date(2026, 9, 23)) == 35
    assert ytdlp_age_days("2026.8.19.232313", today=date(2026, 8, 20)) == 1
    assert ytdlp_age_days("not-a-date") is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_ffmpeg_is_detected() -> None:
    prober = DependencyProber()
    spec = next(p for p in PROGRAMS if p.id == "ffmpeg")
    result = asyncio.run(prober.probe_program(spec))
    assert result.available is True
    assert result.version
