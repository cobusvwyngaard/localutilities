from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from werkbank_engine.config import Settings, load_settings
from werkbank_engine.deps import DependencyProber
from werkbank_engine.health import HealthService
from werkbank_engine.main import create_app
from werkbank_engine.procs import ExecResult

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_REGISTRY = REPO_ROOT / "packages" / "shared" / "dist" / "tools.json"

SAMPLE_TOOL = {
    "id": "video.sample",
    "title": "Sample",
    "description": "A tool used only in tests.",
    "category": "video",
    "runsIn": ["engine"],
    "inputs": {"kinds": ["file"], "accept": [".mp4"], "min": 1, "max": 5},
    "params": {
        "preset": {
            "type": "enum",
            "label": "Preset",
            "options": [{"value": "share", "label": "Share"}, {"value": "balanced", "label": "Balanced"}],
            "default": "balanced",
        },
        "targetMb": {
            "type": "number",
            "label": "Target",
            "min": 1,
            "max": 4000,
            "default": 25,
            "integer": True,
        },
        "crf": {"type": "number", "label": "CRF", "min": 0, "max": 51, "default": 23.5},
        "hardware": {"type": "boolean", "label": "Fast (hardware)", "default": False},
        "title": {"type": "text", "label": "Title", "maxLength": 20},
    },
    "requires": ["ffmpeg"],
}

FFMPEG_VERSION_OUTPUT = (
    "ffmpeg version 7.1.1-full_build-www.gyan.dev Copyright (c) 2000-2025 the FFmpeg developers\n"
    "built with gcc 14.2.0 (Rev1, Built by MSYS2 project)\n"
)
FFMPEG_ENCODERS_OUTPUT = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D h264_amf             AMD AMF H.264 Encoder (codec h264)
 V....D h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)
 V..... h264_qsv             H264 (Intel Quick Sync Video acceleration) (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)
"""


class FakeTools:
    """Pretends some programs exist; everything else is missing."""

    def __init__(self, present: dict[str, str], usable_encoders: tuple[str, ...] = ("h264_nvenc",)) -> None:
        self.present = present  # executable name -> version output
        self.usable_encoders = usable_encoders
        self.calls: list[list[str]] = []

    def find(self, names: tuple[str, ...], extra_dirs: list[Path]) -> str | None:
        for name in names:
            if name in self.present:
                return f"/fake/bin/{name}"
        return None

    async def run(self, args: list[str], limit_seconds: float) -> ExecResult:
        self.calls.append(args)
        name = Path(args[0]).name
        if "-encoders" in args:
            return ExecResult(0, FFMPEG_ENCODERS_OUTPUT, "")
        if "-c:v" in args:
            enc = args[args.index("-c:v") + 1]
            ok = enc in self.usable_encoders
            return ExecResult(0 if ok else 1, "", "" if ok else "No capable devices found")
        return ExecResult(0, self.present[name], "")


ALL_REQUIRED_PRESENT = {
    "ffmpeg": FFMPEG_VERSION_OUTPUT,
    "ffprobe": "ffprobe version 7.1.1-full_build-www.gyan.dev Copyright (c) 2007-2025\n",
    "deno": "deno 2.9.6 (stable, release, x86_64-pc-windows-msvc)\nv8 14.0\ntypescript 5.9.2\n",
}


def make_prober(fake: FakeTools) -> DependencyProber:
    return DependencyProber(platform="windows", runner=fake.run, finder=fake.find, env={})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><head><title>Werkbank</title></head><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log('hi')", encoding="utf-8")
    (dist / "version.json").write_text('{"commit":"local"}', encoding="utf-8")
    (dist / "_headers").write_text("/*\n  X-Test: 1\n", encoding="utf-8")
    registry = tmp_path / "tools.json"
    shipped = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
    shipped["tools"] = [SAMPLE_TOOL]
    registry.write_text(json.dumps(shipped), encoding="utf-8")
    env = {
        "WERKBANK_HOME": str(tmp_path / "home"),
        "WERKBANK_FOLDERS": str(tmp_path / "folders"),
        "WERKBANK_WEB_DIST": str(dist),
        "WERKBANK_REGISTRY": str(registry),
    }
    return load_settings(env)


@pytest.fixture
def fake_tools() -> FakeTools:
    return FakeTools(dict(ALL_REQUIRED_PRESENT))


@pytest.fixture
def client(settings: Settings, fake_tools: FakeTools):
    service = HealthService(settings, tool_count=1, prober=make_prober(fake_tools))
    app = create_app(settings, health_service=service)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50123)) as c:
        yield c


@pytest.fixture
def auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.token}"}
