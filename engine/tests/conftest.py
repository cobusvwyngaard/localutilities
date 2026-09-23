from __future__ import annotations

import shutil
import subprocess
import time
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
    env = {
        "WERKBANK_HOME": str(tmp_path / "home"),
        "WERKBANK_FOLDERS": str(tmp_path / "folders"),
        "WERKBANK_WEB_DIST": str(dist),
        "WERKBANK_REGISTRY": str(SHIPPED_REGISTRY),
        "WERKBANK_WORK": str(tmp_path / "work"),
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


# --- Phase 1: real media, real tools --------------------------------------------------------------

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")
LOCAL_ORIGIN = {"Origin": "http://127.0.0.1:8765"}


def make_media(
    path: Path,
    seconds: float,
    size: str = "320x240",
    video: tuple[str, ...] = ("-c:v", "libx264"),
    audio: tuple[str, ...] = ("-c:a", "aac"),
) -> Path:
    """A small test clip generated by ffmpeg (nothing binary is committed)."""
    args = ["ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s={size}:r=25:d={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:d={seconds}",
            *video, "-pix_fmt", "yuv420p", *audio, "-shortest", str(path)]  # fmt: skip
    subprocess.run(args, check=True, timeout=120)  # noqa: S603 - test helper, fixed argument list
    return path


@pytest.fixture(scope="session")
def media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    d = tmp_path_factory.mktemp("media")
    return {
        "clip": make_media(d / "clip.mp4", 3),
        "vorbis": make_media(d / "clip vorbis.mkv", 2, audio=("-c:a", "libvorbis")),
        "long": make_media(d / "long.mp4", 40, size="1280x720"),
        "tone": make_media(d / "tone.wav", 3, video=("-vn",), audio=("-c:a", "pcm_s16le")),
    }


@pytest.fixture
def real_client(settings: Settings):
    """The app with real dependency probing (ffmpeg, pikepdf, ...) and real tools."""
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 50124)) as c:
        c.headers.update({"Authorization": f"Bearer {settings.token}", **LOCAL_ORIGIN})
        yield c


def upload(client: TestClient, path: Path) -> str:
    r = client.post("/api/files", params={"name": path.name}, content=path.read_bytes())
    assert r.status_code == 201, r.text
    return r.json()["fileId"]


def wait_for_job(client: TestClient, job_id: str, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish: {job}")


def run_job(client: TestClient, tool: str, inputs: list[dict], params: dict | None = None) -> dict:
    r = client.post("/api/jobs", json={"tool": tool, "params": params or {}, "inputs": inputs})
    assert r.status_code == 201, r.text
    return wait_for_job(client, r.json()["id"])


@pytest.fixture
def live_engine(tmp_path: Path):
    """The real app under uvicorn in a thread: true streaming (TestClient buffers responses)."""
    import socket
    import threading

    import httpx2
    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        "WERKBANK_HOME": str(tmp_path / "home"),
        "WERKBANK_FOLDERS": str(tmp_path / "folders"),
        "WERKBANK_WEB_DIST": str(tmp_path / "no-ui"),
        "WERKBANK_REGISTRY": str(SHIPPED_REGISTRY),
        "WERKBANK_WORK": str(tmp_path / "work"),
        "WERKBANK_PORT": str(port),
    }
    settings = load_settings(env)
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    headers = {"Authorization": f"Bearer {settings.token}", "Origin": f"http://127.0.0.1:{port}"}
    with httpx2.Client(base_url=f"http://127.0.0.1:{port}", headers=headers, timeout=60) as client:
        yield client, settings
    server.should_exit = True
    thread.join(timeout=20)
