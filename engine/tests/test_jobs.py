"""Jobs end to end through the API with real FFmpeg and pikepdf (DESIGN.md §9 phase 1)."""

from __future__ import annotations

import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pikepdf
import pytest
from starlette.testclient import TestClient

from tests.conftest import needs_ffmpeg, run_job, upload, wait_for_job
from werkbank_engine.config import Settings

pytestmark = needs_ffmpeg


def outbox_names(settings: Settings) -> list[str]:
    return sorted(p.name for p in settings.outbox.iterdir())


def test_convert_remux_is_lossless_and_never_overwrites(
    real_client: TestClient, settings: Settings, media: dict[str, Path]
) -> None:
    file_id = upload(real_client, media["clip"])
    first = run_job(real_client, "video.convert", [{"fileId": file_id}], {"target": "mkv"})
    assert first["status"] == "done", first
    assert first["notes"] == ["clip.mp4: No quality loss: streams were copied, not re-encoded."]
    second = run_job(real_client, "video.convert", [{"fileId": file_id}], {"target": "mkv"})
    assert second["status"] == "done"
    assert outbox_names(settings) == ["clip (converted) (2).mkv", "clip (converted).mkv"]
    download = real_client.get(f"/api/jobs/{first['id']}/outputs/0")
    assert download.status_code == 200
    assert download.content == (settings.outbox / "clip (converted).mkv").read_bytes()


def test_convert_reencodes_only_the_audio(
    real_client: TestClient, settings: Settings, media: dict[str, Path]
) -> None:
    job = run_job(real_client, "video.convert", [{"fileId": upload(real_client, media["vorbis"])}], {})
    assert job["status"] == "done", job
    assert "Video copied without quality loss; re-encoded audio to AAC." in job["notes"][0]
    assert outbox_names(settings) == ["clip vorbis (converted).mp4"]


def test_compress_video_from_the_inbox(
    real_client: TestClient, settings: Settings, media: dict[str, Path]
) -> None:
    settings.inbox.mkdir(parents=True, exist_ok=True)
    (settings.inbox / "clip.mp4").write_bytes(media["clip"].read_bytes())
    job = run_job(real_client, "video.compress", [{"inbox": "clip.mp4"}], {"preset": "share"})
    assert job["status"] == "done", job
    assert job["progress"] == 1.0
    assert job["outputs"][0]["name"] == "clip (compressed).mp4"
    assert "MB →" in job["notes"][0]


def test_target_size_is_respected(
    real_client: TestClient, settings: Settings, media: dict[str, Path]
) -> None:
    job = run_job(
        real_client, "video.compress", [{"fileId": upload(real_client, media["long"])}],
        {"preset": "target", "targetMb": 1},
    )  # fmt: skip
    assert job["status"] == "done", job
    size = job["outputs"][0]["size"]
    assert size <= 1 * 1_048_576, f"{size} bytes is over the 1 MB target"


def test_audio_compress_and_convert(real_client: TestClient, media: dict[str, Path]) -> None:
    tone = upload(real_client, media["tone"])
    speech = run_job(real_client, "audio.compress", [{"fileId": tone}], {"preset": "speech"})
    assert speech["status"] == "done", speech
    assert speech["outputs"][0]["name"] == "tone (compressed).opus"
    podcast = run_job(real_client, "audio.compress", [{"fileId": tone}], {"preset": "podcast"})
    assert podcast["status"] == "done", podcast
    flac = run_job(real_client, "audio.convert", [{"fileId": tone}], {"target": "flac"})
    assert flac["status"] == "done", flac
    assert "re-encoded audio to FLAC" in flac["notes"][0] or "Re-encoded audio to FLAC" in flac["notes"][0]
    from_video = run_job(
        real_client, "audio.convert", [{"fileId": upload(real_client, media["clip"])}], {"target": "m4a"}
    )
    assert from_video["status"] == "done", from_video
    assert "No quality loss" in from_video["notes"][0]  # AAC copied straight out of the MP4


def test_live_progress_and_clean_cancel(live_engine, media: dict[str, Path]) -> None:
    """Phase 1 acceptance: progress arrives live over server-sent events, and cancel leaves
    nothing behind (no output, no scratch folder)."""
    client, settings = live_engine
    r = client.post("/api/files", params={"name": "long.mp4"}, content=media["long"].read_bytes())
    file_id = r.json()["fileId"]
    body = {"tool": "video.compress", "params": {"preset": "archive"}, "inputs": [{"fileId": file_id}]}
    job_id = client.post("/api/jobs", json=body).json()["id"]
    progress: list[float] = []
    final = None
    with client.stream("GET", f"/api/jobs/{job_id}/events") as events:
        for line in events.iter_lines():
            if not line.startswith("data: "):
                continue
            snapshot = json.loads(line[6:])
            if snapshot["status"] == "running" and snapshot["progress"]:
                progress.append(snapshot["progress"])
                if len(progress) == 3:
                    assert client.delete(f"/api/jobs/{job_id}").json()["status"] == "cancelled"
            if snapshot["status"] in ("done", "failed", "cancelled"):
                final = snapshot
                break
    assert len(progress) >= 3 and progress == sorted(progress), progress
    assert progress[-1] < 1
    assert final is not None and final["status"] == "cancelled"
    assert final["outputs"] == []
    assert outbox_names(settings) == []
    assert not (settings.work_dir / "jobs" / job_id).exists()


def test_several_files_in_one_job(
    real_client: TestClient, settings: Settings, media: dict[str, Path]
) -> None:
    inputs = [
        {"fileId": upload(real_client, media["clip"])},
        {"fileId": upload(real_client, media["vorbis"])},
    ]
    job = run_job(real_client, "audio.convert", inputs, {"target": "mp3"})
    assert job["status"] == "done", job
    assert job["title"] == "clip.mp4 and 1 more"
    assert outbox_names(settings) == ["clip (converted).mp3", "clip vorbis (converted).mp3"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"tool": "nope", "inputs": []}, "Unknown engine tool"),
        (
            {"tool": "video.convert", "params": {"target": "avi"}, "inputs": [{"url": "https://x.test/a"}]},
            "one of",
        ),
        ({"tool": "video.convert", "params": {"shell": "rm"}, "inputs": []}, "unknown parameter"),
        ({"tool": "video.convert", "inputs": [{"url": "https://x.test/a"}]}, "does not take web addresses"),
        ({"tool": "video.convert", "inputs": [{"inbox": "../secret.mp4"}]}, "Invalid Inbox file name"),
        ({"tool": "video.convert", "inputs": [{"fileId": "unknown"}]}, "Unknown or expired file"),
        ({"tool": "video.convert", "inputs": []}, "input(s)"),
        ({"tool": "download.media", "inputs": [{"url": "file:///etc/passwd"}]}, "http:// or https://"),
        ({"tool": "download.media", "inputs": [{"url": "https://x.test/a b"}]}, "http:// or https://"),
        ({"tool": "download.media", "inputs": [{"fileId": "x"}]}, "takes a web address"),
    ],
)
def test_bad_job_requests_are_rejected(real_client: TestClient, body: dict, message: str) -> None:
    r = real_client.post("/api/jobs", json=body)
    assert r.status_code == 400, r.text
    assert message in r.json()["detail"]


def test_wrong_file_type_is_rejected(real_client: TestClient, media: dict[str, Path]) -> None:
    r = real_client.post(
        "/api/jobs", json={"tool": "pdf.unlock", "inputs": [{"fileId": upload(real_client, media["clip"])}]}
    )
    assert r.status_code == 400
    assert "not a supported file type" in r.json()["detail"]


def test_input_needs_exactly_one_reference(real_client: TestClient) -> None:
    r = real_client.post(
        "/api/jobs", json={"tool": "pdf.unlock", "inputs": [{"fileId": "a", "url": "https://x"}]}
    )
    assert r.status_code == 422


# --- PDF unlock (DESIGN.md §5.4) --------------------------------------------------------------


def make_pdf(path: Path, user_password: str | None) -> Path:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    if user_password is None:
        pdf.save(path)
    else:
        restricted = pikepdf.Permissions(extract=False, print_highres=False, modify_other=False)
        pdf.save(
            path, encryption=pikepdf.Encryption(owner="owner-secret", user=user_password, allow=restricted)
        )
    return path


def test_owner_restricted_pdf_unlocks_without_a_password(
    real_client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    job = run_job(
        real_client, "pdf.unlock", [{"fileId": upload(real_client, make_pdf(tmp_path / "r.pdf", ""))}]
    )
    assert job["status"] == "done", job
    assert "No password was needed" in job["notes"][0]
    with pikepdf.open(settings.outbox / "r (unlocked).pdf") as out:
        assert not out.is_encrypted
        assert out.allow.extract


def test_user_password_pdf_needs_the_right_password(
    real_client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    file_id = upload(real_client, make_pdf(tmp_path / "locked.pdf", "open-sesame"))
    missing = run_job(real_client, "pdf.unlock", [{"fileId": file_id}])
    assert missing["status"] == "failed" and "open (user) password" in missing["error"]
    wrong = run_job(real_client, "pdf.unlock", [{"fileId": file_id}], {"password": "guess"})
    assert wrong["status"] == "failed" and "does not open" in wrong["error"]
    right = run_job(real_client, "pdf.unlock", [{"fileId": file_id}], {"password": "open-sesame"})
    assert right["status"] == "done", right
    assert outbox_names(settings) == ["locked (unlocked).pdf"]
    with pikepdf.open(settings.outbox / "locked (unlocked).pdf") as out:
        assert not out.is_encrypted
    # The password is never echoed back, in any job, list or log.
    everything = json.dumps([wrong, right, real_client.get("/api/jobs").json()])
    assert "open-sesame" not in everything and "guess" not in everything


def test_unprotected_pdf_needs_nothing(real_client: TestClient, settings: Settings, tmp_path: Path) -> None:
    job = run_job(
        real_client, "pdf.unlock", [{"fileId": upload(real_client, make_pdf(tmp_path / "p.pdf", None))}]
    )
    assert job["status"] == "done"
    assert "nothing to do" in job["notes"][0]
    assert job["outputs"] == []


# --- Downloader (yt-dlp), against a local web server ---------------------------------------------


@pytest.fixture
def web_server(media: dict[str, Path]):
    handler = partial(SimpleHTTPRequestHandler, directory=str(media["clip"].parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_download_from_a_web_server(real_client: TestClient, settings: Settings, web_server: str) -> None:
    health = real_client.get("/api/health").json()
    if not next(d for d in health["dependencies"] if d["id"] == "deno")["available"]:
        pytest.skip("Deno is not installed")
    job = run_job(real_client, "download.media", [{"url": f"{web_server}/clip.mp4"}])
    assert job["status"] == "done", job
    assert job["notes"] == ["Downloaded 1 file."]
    [name] = outbox_names(settings)
    assert name.endswith(".mp4") and "[clip]" in name


def test_download_failure_is_reported(real_client: TestClient, web_server: str) -> None:
    health = real_client.get("/api/health").json()
    if not next(d for d in health["dependencies"] if d["id"] == "deno")["available"]:
        pytest.skip("Deno is not installed")
    job = run_job(real_client, "download.media", [{"url": f"{web_server}/missing.mp4"}])
    assert job["status"] == "failed"
    assert "yt-dlp failed" in job["error"] and "404" in job["error"]


def test_queued_job_can_be_cancelled(real_client: TestClient, media: dict[str, Path]) -> None:
    """Only one heavy job runs at a time; the second waits and can be cancelled while queued."""
    file_id = upload(real_client, media["long"])
    body = {"tool": "video.compress", "params": {"preset": "archive"}, "inputs": [{"fileId": file_id}]}
    first = real_client.post("/api/jobs", json=body).json()
    second = real_client.post("/api/jobs", json=body).json()
    time.sleep(0.3)
    assert real_client.get(f"/api/jobs/{second['id']}").json()["status"] == "queued"
    assert real_client.delete(f"/api/jobs/{second['id']}").json()["status"] == "cancelled"
    assert real_client.delete(f"/api/jobs/{first['id']}").json()["status"] == "cancelled"
    assert wait_for_job(real_client, first["id"])["status"] == "cancelled"
