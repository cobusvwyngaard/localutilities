"""audio.transcribe with the real whisper.cpp.

The real run needs `whisper-cli` on PATH and a model: CI sets WERKBANK_TEST_WHISPER_MODEL to the
tiny model (fast; it stands in for "small") and WERKBANK_TEST_VAD_MODEL to the Silero model.
The sample is JFK's 1961 inaugural address (public domain), from the whisper.cpp repository."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.conftest import HAS_FFMPEG, run_job, upload
from werkbank_engine.config import Settings
from werkbank_engine.tools import audio_transcribe

JFK = Path(__file__).parent / "fixtures" / "jfk.wav"
TEST_MODEL = os.environ.get("WERKBANK_TEST_WHISPER_MODEL")
TEST_VAD = os.environ.get("WERKBANK_TEST_VAD_MODEL")
CAN_TRANSCRIBE = bool(shutil.which("whisper-cli") and TEST_MODEL and HAS_FFMPEG)


def test_arguments() -> None:
    args = audio_transcribe.build_args(
        "whisper-cli", Path("m.bin"), Path("vad.bin"), Path("a.wav"), Path("out"), "af", ("txt", "srt")
    )
    assert args[:9] == ["whisper-cli", "-m", "m.bin", "-f", "a.wav", "-l", "af", "-t", args[8]]
    assert int(args[8]) >= 1
    assert args[-4:] == ["-osrt", "--vad", "-vm", "vad.bin"]
    assert "-otxt" in args and "-pp" in args and "-np" in args
    assert "--vad" not in audio_transcribe.build_args(
        "w", Path("m"), None, Path("a"), Path("o"), "en", ("txt",)
    )


def test_progress_parsing() -> None:
    assert audio_transcribe.parse_progress("whisper_print_progress_callback: progress =  45%") == 0.45
    assert audio_transcribe.parse_progress("output_txt: saving output to 'x.txt'") is None


def test_missing_model_is_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WERKBANK_MODELS", str(tmp_path))
    with pytest.raises(audio_transcribe.ToolError, match=r"ggml-large-v3-turbo-q5_0\.bin is missing"):
        audio_transcribe.model_path("turbo")


@pytest.mark.skipif(not CAN_TRANSCRIBE, reason="whisper-cli or WERKBANK_TEST_WHISPER_MODEL not available")
def test_transcribes_speech(
    real_client: TestClient, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    shutil.copyfile(TEST_MODEL, models / audio_transcribe.MODELS["small"])
    if TEST_VAD:
        shutil.copyfile(TEST_VAD, models / audio_transcribe.VAD_MODEL)
    monkeypatch.setenv("WERKBANK_MODELS", str(models))

    job = run_job(
        real_client,
        "audio.transcribe",
        [{"fileId": upload(real_client, JFK)}],
        {"model": "small", "language": "en"},
    )
    assert job["status"] == "done", job
    assert sorted(o["name"] for o in job["outputs"]) == [
        "jfk (transcript).srt",
        "jfk (transcript).txt",
        "jfk (transcript).vtt",
    ]
    text = (settings.outbox / "jfk (transcript).txt").read_text(encoding="utf-8").lower()
    assert "ask not what your country can do for you" in text
    srt = (settings.outbox / "jfk (transcript).srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:0")
    assert "words" in job["notes"][0]

    turbo = run_job(
        real_client, "audio.transcribe", [{"fileId": upload(real_client, JFK)}], {"model": "turbo"}
    )
    assert turbo["status"] == "failed" and "missing" in turbo["error"]
